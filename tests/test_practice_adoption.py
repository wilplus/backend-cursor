"""The practice loop (contract 29a, founder lock 2026-09-30, B6, D1, D2):
judged after every attempt, no cap, three kinds of passage, and never a
rewrite of the paragraph."""
from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from services.data_purge_registry import DEPENDENCIES
from services.practice_adoption import (
    DONE_ANSWERS,
    ANSWERS,
    KINDS,
    LEGACY_ROUTE_OF,
    route_matches,
    helper_words_from_practice,
    judge_attempt,
    judgeable_attempt,
    outcome,
    passage_for,
    phrase_in_transcript,
)


@pytest.mark.parametrize("answer,expected", [
    ("yes", "done"), ("in_between", "done"),
    ("no", "again"), ("not_sure", "again"), ("audio_unclear", "again"),
])
def test_the_loop_ends_on_yes_or_in_between_and_never_on_a_count(answer, expected):
    # No cap (D2): the answer alone decides, however many attempts exist.
    assert outcome(answer) == expected


def test_only_yes_and_in_between_are_done():
    # B2: Not sure is another attempt, not a moment to build a cue on.
    assert DONE_ANSWERS == {"yes", "in_between"}


def test_only_the_latest_unjudged_attempt_is_judgeable():
    rows = [{"id": "a1", "attempt_index": 1, "user_answer": "no"},
            {"id": "a2", "attempt_index": 2, "user_answer": None}]
    assert judgeable_attempt(rows)["id"] == "a2"
    rows[1]["user_answer"] = "no"
    assert judgeable_attempt(rows) is None
    assert judgeable_attempt([]) is None


def test_three_kinds_of_passage():
    # D1: the exercise and the plain moment practise the moment's own words;
    # the rewrite practises the Manager's clearer version.
    assert KINDS == ("exercise", "rewrite", "plain")
    assert passage_for("exercise", " We cut onboarding. ", None) == "We cut onboarding."
    assert passage_for("plain", "We cut onboarding.", "ignored") == "We cut onboarding."
    assert passage_for("rewrite", "We cut onboarding.", "  We  cut it. ") == "We cut it."
    assert passage_for("rewrite", "We cut onboarding.", "") is None
    assert passage_for("rewrite", "x", "**bold** words") is None
    assert passage_for("plain", "", None) is None
    assert passage_for("song", "words", "words") is None


def test_helper_words_must_be_exact_practice_words():
    assert phrase_in_transcript("nine days", "From  nine days to two") == "nine days"
    assert phrase_in_transcript("ten days", "From nine days to two") is None
    assert phrase_in_transcript("**nine**", "nine") is None
    assert phrase_in_transcript(None, "nine") is None


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


def test_the_tenth_no_is_another_attempt_too():
    # D2: attempt 10 works like attempt 1.
    rows = [{"id": f"a{i}", "attempt_index": i,
             "user_answer": "no" if i < 10 else None} for i in range(1, 11)]
    db = _Db(rows)
    status, body = judge_attempt(db, db.practice, "a10", "not_sure", "u")
    assert (status, body["outcome"]) == (200, "again")
    assert db.practice["status"] == "open"


def test_a_yes_or_in_between_is_done_and_never_rewrites_the_paragraph():
    for answer in ("yes", "in_between"):
        db = _Db([{"id": "a1", "attempt_index": 1, "user_answer": None,
                   "transcript": "Nine days became two."}])
        status, body = judge_attempt(db, db.practice, "a1", answer, "u")
        assert status == 200 and body["outcome"] == "done"
        # B6: nothing is adopted; the words are for the helper-words picker.
        assert body["adopted"] is False and body["paragraph"] is None
        assert body["attempt_transcript"] == "Nine days became two."
        assert db.practice["status"] == "completed"
        assert db.practice["final_user_answer"] == answer


def test_the_adoption_is_retired_with_its_code():
    import services.practice_adoption as module
    for gone in ("adopt", "splice", "passage_span", "MAX_ATTEMPTS", "ADOPTING"):
        assert not hasattr(module, gone), gone


def test_only_the_latest_attempt_and_the_five_answers_are_accepted():
    db = _Db([{"id": "a1", "attempt_index": 1, "user_answer": None}])
    assert judge_attempt(db, db.practice, "a1", "maybe", "u")[0] == 400
    assert judge_attempt(db, db.practice, "other", "yes", "u")[0] == 409
    closed = _Db([{"id": "a1", "attempt_index": 1}], status="completed")
    assert judge_attempt(closed, closed.practice, "a1", "yes", "u")[0] == 409


def test_helper_words_from_practice_need_a_done_answer():
    db = _Db([{"id": "a1", "attempt_index": 1, "transcript": "From nine days"}])
    assert helper_words_from_practice(
        db, db.practice, "part", "nine days", "u")[0] == 409
    db.practice.update(status="completed", final_user_answer="not_sure",
                       selected_attempt_id="a1")
    # Not sure is not done (B2): no helper words from it.
    assert helper_words_from_practice(
        db, db.practice, "part", "nine days", "u")[0] == 409
    db.practice.update(final_user_answer="in_between")
    db.takes = mock.Mock(get_arc_sessions=mock.Mock(return_value=[]))
    with mock.patch("services.slide_helper_words.record_pick") as pick:
        status, body = helper_words_from_practice(
            db, db.practice, "part", "nine days", "u")
    assert (status, body["phrase"]) == (200, "nine days")
    pick.assert_called_once()
    assert helper_words_from_practice(
        db, db.practice, "part", "ten days", "u")[0] == 400


def test_the_route_has_no_attempt_cap_and_knows_the_three_kinds():
    source = (Path(__file__).resolve().parents[1]
              / "routes/v2/user_sessions.py").read_text()
    assert "ATTEMPT_LIMIT" not in source
    assert '"attempts_remaining"' not in source
    start = source.index("def v2_start_confident_voice_practice")
    end = source.index("@v2_bp.route", start)
    route = source[start:end]
    assert "passage_for(" in route
    assert "_practice_start_gate(" in route
    payload = source[source.index("def _practice_user_payload"):
                     source.index("@v2_bp.route",
                                  source.index("def _practice_user_payload"))]
    assert '"kind": kind' in payload


def test_the_migration_lets_a_practice_stand_without_an_exercise():
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "practice_without_a_library_exercise.sql").read_text()
    assert "ALTER COLUMN exercise_id DROP NOT NULL" in sql
    assert "ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'exercise'" in sql
    assert "CHECK (kind IN ('exercise', 'rewrite', 'plain'))" in sql
    manifest = (Path(__file__).resolve().parents[1] / "migrations"
                / "manifest.txt").read_text()
    assert "practice_without_a_library_exercise.sql" in manifest


def test_the_migration_widens_all_three_answers_and_registers_history():
    sql = (Path(__file__).resolve().parents[1] / "migrations"
           / "practice_is_judged_after_every_attempt.sql").read_text()
    for name in ("cvp_attempt_user_answer_five",
                 "cvp_original_user_answer_five",
                 "cvp_final_user_answer_five"):
        assert name in sql
    assert "'document_moved'" in sql
    assert "ideal_text_practice_adoptions" in {d.relation for d in DEPENDENCIES}


# F-4 (audit 2026-09-22): the stored route is the answer itself; rows from
# before the fix hold the legacy pair and are still read.

def test_a_route_stored_as_the_answer_matches_that_answer_only():
    for answer in ANSWERS:
        assert route_matches(answer, answer)
        for other in ANSWERS:
            if other != answer:
                assert not route_matches(answer, other)


def test_a_legacy_route_matches_every_answer_it_folded():
    assert route_matches("neutral", "in_between")
    assert route_matches("neutral", "not_sure")
    assert route_matches("unrateable", "audio_unclear")
    assert not route_matches("neutral", "yes")
    assert not route_matches("unrateable", "no")
    assert set(LEGACY_ROUTE_OF) == set(ANSWERS)


def test_an_unknown_answer_never_matches():
    assert not route_matches("yes", "maybe")
    assert not route_matches("", "")
