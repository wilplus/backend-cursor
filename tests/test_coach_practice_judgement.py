"""The coach's judgement of a practice recording comes back (founder
2026-10-05, Q6; N45).

Pins: the Read screen carries the speaker's chosen recording and the
coach's own saved answer, never the machine's read; the save takes one of
the five answers on the selected attempt only, records the after-practice
result and reconciles the Album; the route sits behind the blind gate and
the speaker's practice choice.
"""
from __future__ import annotations

import pathlib
from unittest import mock

import pytest

from services import coach_practice_judgement as cpj

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Db:
    def __init__(self, *, selected="att-2"):
        self.practice = {"id": "pr-1", "take_session_id": "take-1", "snippet_id": "snip-1",
                         "selected_attempt_id": selected, "owner_user_id": "u1",
                         "project_id": "arc-1"}
        self.attempts = [
            {"id": "att-1", "audio_ref": "a1.webm", "duration_ms": 3000,
             "coach_confidence_decision": None, "machine_confidence_decision": "yes"},
            {"id": "att-2", "audio_ref": "a2.webm", "duration_ms": 3200,
             "coach_confidence_decision": "in_between", "machine_confidence_decision": "yes"},
        ]
        self.decisions: list = []

    def get_confident_voice_practice_by_moment(self, take, snip):
        return dict(self.practice) if snip == "snip-1" else None

    def list_confident_voice_practice_attempts(self, _pid):
        return list(self.attempts)

    def set_confident_voice_practice_attempt_coach_decision(self, pid, aid, decision, coach):
        self.decisions.append((pid, aid, decision, coach))
        return {"id": aid}


@pytest.fixture(autouse=True)
def _quiet_side_effects():
    with mock.patch("services.practice_more_confident.record_after_coach_decision") as after, \
            mock.patch("services.confident_voice_practice.reconcile_practice_voice_album",
                       return_value=False) as album, \
            mock.patch("services.audio_ref_resolver.resolve_playable_ref",
                       side_effect=lambda ref: f"https://media/{ref}"):
        yield after, album


def test_the_read_carries_the_chosen_recording_and_the_coachs_own_answer():
    out = cpj.selected_practice(_Db(), "take-1", "snip-1")
    assert out == {"attempt_id": "att-2", "audio_ref": "https://media/a2.webm",
                   "duration_ms": 3200, "coach_answer": "in_between"}
    assert "machine" not in str(out)


def test_no_practice_or_nothing_chosen_is_none():
    assert cpj.selected_practice(_Db(), "take-1", "other") is None
    assert cpj.selected_practice(_Db(selected=None), "take-1", "snip-1") is None


def test_the_answer_lands_on_the_selected_attempt(_quiet_side_effects):
    after, album = _quiet_side_effects
    db = _Db()
    status, payload = cpj.judge_selected_attempt(
        db, take_session_id="take-1", snippet_id="snip-1", body={"answer": "yes"}, coach_id="c1")
    assert (status, payload) == (200, {"answer": "yes"})
    assert db.decisions == [("pr-1", "att-2", "yes", "c1")]
    after.assert_called_once_with(db, "pr-1", "att-2")
    album.assert_called_once()


@pytest.mark.parametrize("body", [{}, {"answer": "maybe"}, None, {"answer": 1}])
def test_only_one_of_the_five_answers(body):
    db = _Db()
    status, payload = cpj.judge_selected_attempt(
        db, take_session_id="take-1", snippet_id="snip-1", body=body, coach_id="c1")
    assert (status, payload["code"]) == (400, "INVALID_INPUT")
    assert db.decisions == []


def test_nothing_chosen_yet_is_refused():
    status, payload = cpj.judge_selected_attempt(
        _Db(selected=None), take_session_id="take-1", snippet_id="snip-1",
        body={"answer": "yes"}, coach_id="c1")
    assert (status, payload["code"]) == (409, "NO_SELECTED_ATTEMPT")


def test_the_route_sits_behind_the_blind_gate_and_the_speakers_choice():
    source = (ROOT / "routes/v2/coach.py").read_text()
    start = source.index("def v2_coach_practice_judgement(")
    head = source[:start].rsplit("@v2_bp.route", 1)[1]
    body = source[start:source.index("\n@v2_bp.route", start)]
    assert "/practice-judgement" in head
    assert "@require_admin_or_coach" in head
    assert body.index("_moment_gate(session_id, snippet_id)") < body.index("judge_selected_attempt")
    assert body.index("_speaker_practice_permitted") < body.index("judge_selected_attempt")


def test_the_read_screen_payload_names_the_practice():
    source = (ROOT / "services/coach_moment_read.py").read_text()
    assert '"practice": selected_practice(database, take, snip)' in source
