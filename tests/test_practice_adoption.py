"""Practice is judged after every attempt; an adopted attempt feeds the
paragraph (contract 29a / 35d, founder 2026-09-25, Q17 A / Q18 A)."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from services.data_purge_registry import DEPENDENCIES
from services.practice_adoption import (
    ADOPTING,
    helper_words_from_practice,
    judge_attempt,
    judgeable_attempt,
    outcome,
    passage_span,
    phrase_in_transcript,
    splice,
)

TEXT = "We cut onboarding.\n\nFrom nine days to two, fast. Every hire ships."
DOC = {
    "pieces": [
        {"snippet_id": "s1", "start": 0, "end": 18, "text": "We cut onboarding."},
        {"snippet_id": "s2", "start": 20, "end": 48,
         "text": "From nine days to two, fast."},
        {"snippet_id": "s3", "start": 49, "end": 66, "text": "Every hire ships."},
    ],
    "paragraphs": [
        {"slide_index": 0, "start": 0, "end": 18},
        {"slide_index": 1, "start": 20, "end": 66},
    ],
}


@pytest.mark.parametrize("answer,attempts,expected", [
    ("yes", 1, "adopt"), ("in_between", 2, "adopt"), ("not_sure", 3, "adopt"),
    ("no", 1, "again"), ("audio_unclear", 2, "again"),
    ("no", 3, "closed"), ("audio_unclear", 3, "closed"),
])
def test_the_loop(answer, attempts, expected):
    assert outcome(answer, attempts) == expected


def test_only_yes_in_between_and_not_sure_adopt():
    assert ADOPTING == {"yes", "in_between", "not_sure"}


def test_only_the_latest_unjudged_attempt_is_judgeable():
    rows = [{"id": "a1", "attempt_index": 1, "user_answer": "no"},
            {"id": "a2", "attempt_index": 2, "user_answer": None}]
    assert judgeable_attempt(rows)["id"] == "a2"
    rows[1]["user_answer"] = "no"
    assert judgeable_attempt(rows) is None
    assert judgeable_attempt([]) is None


def test_the_passage_is_found_by_its_piece_never_by_fuzzy_text():
    assert passage_span(DOC, TEXT, "s2") == (20, 48)
    assert passage_span(DOC, TEXT, "gone") is None
    moved = TEXT.replace("nine", "ten")
    assert passage_span(DOC, moved, "s2") is None


def test_splice_replaces_only_the_passage_and_moves_every_offset():
    new_text, new_doc = splice(TEXT, DOC, 20, 48, "Nine days became two.")
    assert new_text == ("We cut onboarding.\n\nNine days became two. "
                        "Every hire ships.")
    for piece in new_doc["pieces"]:
        assert new_text[piece["start"]:piece["end"]] == piece["text"]
    last = new_doc["paragraphs"][1]
    assert new_text[last["start"]:last["end"]] == (
        "Nine days became two. Every hire ships.")


def test_helper_words_must_be_exact_practice_words():
    said = "  From nine days\n to two  "
    assert phrase_in_transcript("nine days to", said) == "nine days to"
    assert phrase_in_transcript("ten days", said) is None
    assert phrase_in_transcript("**nine**", said) is None


class _Db:
    def __init__(self, attempts, status="open"):
        self.practice = {"id": "p", "project_id": "arc", "snippet_id": "s2",
                         "status": status, "take_session_id": "t"}
        self.attempts = attempts
        self.updates = []

    def list_confident_voice_practice_attempts(self, practice_id):
        return self.attempts

    def keep_confident_voice_practice_attempt(self, pid, aid, answer):
        for row in self.attempts:
            if row["id"] == aid:
                row["user_answer"] = answer
                return row
        return None

    def update_confident_voice_practice(self, pid, owner, fields):
        self.updates.append(fields)
        self.practice.update(fields)
        return self.practice


def test_a_no_leaves_the_practice_open_for_another_attempt():
    db = _Db([{"id": "a1", "attempt_index": 1, "user_answer": None}])
    status, body = judge_attempt(db, db.practice, "a1", "no", "u")
    assert (status, body["outcome"]) == (200, "again")
    assert db.updates == []


def test_a_yes_completes_and_adopts():
    db = _Db([{"id": "a1", "attempt_index": 1, "user_answer": None,
               "transcript": "Nine days became two."}])
    with mock.patch("services.practice_adoption.adopt",
                    return_value={"adopted": True, "reason": ""}) as adopt:
        status, body = judge_attempt(db, db.practice, "a1", "in_between", "u")
    assert status == 200 and body["outcome"] == "adopt" and body["adopted"]
    assert body["attempt_transcript"]
    assert db.practice["status"] == "completed"
    assert db.practice["final_user_answer"] == "in_between"
    adopt.assert_called_once()


def test_the_third_no_closes_without_adopting():
    rows = [{"id": f"a{i}", "attempt_index": i,
             "user_answer": "no" if i < 3 else None} for i in (1, 2, 3)]
    db = _Db(rows)
    status, body = judge_attempt(db, db.practice, "a3", "no", "u")
    assert body["outcome"] == "closed" and not body["adopted"]
    assert db.practice["status"] == "completed"


def test_only_the_latest_attempt_and_the_five_answers_are_accepted():
    db = _Db([{"id": "a1", "attempt_index": 1, "user_answer": None}])
    assert judge_attempt(db, db.practice, "a1", "maybe", "u")[0] == 400
    assert judge_attempt(db, db.practice, "other", "yes", "u")[0] == 409
    closed = _Db([{"id": "a1", "attempt_index": 1}], status="completed")
    assert judge_attempt(closed, closed.practice, "a1", "yes", "u")[0] == 409


def test_helper_words_from_practice_need_an_adopting_answer():
    db = _Db([{"id": "a1", "attempt_index": 1, "transcript": "From nine days"}])
    assert helper_words_from_practice(
        db, db.practice, "part", "nine days", "u")[0] == 409
    db.practice.update(status="completed", final_user_answer="not_sure",
                       selected_attempt_id="a1")
    db.takes = mock.Mock(get_arc_sessions=mock.Mock(return_value=[]))
    with mock.patch("services.slide_helper_words.record_pick") as pick:
        status, body = helper_words_from_practice(
            db, db.practice, "part", "nine days", "u")
    assert (status, body["phrase"]) == (200, "nine days")
    pick.assert_called_once()
    assert helper_words_from_practice(
        db, db.practice, "part", "ten days", "u")[0] == 400


def test_the_migration_widens_all_three_answers_and_registers_history():
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "practice_is_judged_after_every_attempt.sql").read_text()
    for name in ("cvp_attempt_user_answer_five",
                 "cvp_original_user_answer_five",
                 "cvp_final_user_answer_five"):
        assert name in sql
    assert "'document_moved'" in sql
    assert "ideal_text_practice_adoptions" in {d.relation for d in DEPENDENCIES}
