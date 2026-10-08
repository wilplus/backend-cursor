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


# ── LOCKIN §5c, contract 34 (W6 2026-10-05): written once ──────────────────

class _Decided(_Db):
    def set_confident_voice_practice_attempt_coach_decision(self, pid, aid, decision, coach):
        self.decisions.append((pid, aid, decision, coach))
        return {"id": aid, "coach_confidence_decision": "in_between",
                "already_decided": True}


def test_a_second_answer_never_overwrites_the_first(_quiet_side_effects):
    after, album = _quiet_side_effects
    status, payload = cpj.judge_selected_attempt(
        _Decided(), take_session_id="take-1", snippet_id="snip-1",
        body={"answer": "yes"}, coach_id="c1")
    assert status == 409
    assert payload["code"] == "PRACTICE_ALREADY_JUDGED"
    assert payload["answer"] == "in_between"
    after.assert_not_called()
    album.assert_not_called()


class _Query:
    """A PostgREST builder double: records every filter, answers per table."""

    def __init__(self, client, table):
        self.client, self.table, self.filters, self.kind = client, table, [], None

    def update(self, payload):
        self.kind, self.payload = "update", payload
        return self

    def select(self, *_a):
        self.kind = "select"
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        self.client.calls.append((self.kind, self.filters))
        rows = self.client.answers[self.kind]
        return type("R", (), {"data": rows})()


class _Client:
    def __init__(self, *, updated, standing):
        self.calls: list = []
        self.answers = {"update": updated, "select": standing}

    def table(self, name):
        assert name == "confident_voice_practice_attempt"
        return _Query(self, name)


def _service(client):
    from services.db import DatabaseService
    service = DatabaseService.__new__(DatabaseService)
    service.client = client
    return service


def test_the_database_writes_the_coach_decision_only_where_none_stands():
    client = _Client(updated=[{"id": "att-1", "coach_confidence_decision": "yes"}],
                     standing=[])
    row = _service(client).set_confident_voice_practice_attempt_coach_decision(
        "pr-1", "att-1", "yes", "c1")
    assert row == {"id": "att-1", "coach_confidence_decision": "yes"}
    kind, filters = client.calls[0]
    assert kind == "update"
    assert ("is", "coach_confidence_decision", "null") in filters


def test_the_database_returns_the_standing_decision_marked_already_decided():
    client = _Client(updated=[], standing=[{"id": "att-1",
                                            "coach_confidence_decision": "no"}])
    row = _service(client).set_confident_voice_practice_attempt_coach_decision(
        "pr-1", "att-1", "yes", "c1")
    assert row == {"id": "att-1", "coach_confidence_decision": "no",
                   "already_decided": True}
    assert [k for k, _ in client.calls] == ["update", "select"]
