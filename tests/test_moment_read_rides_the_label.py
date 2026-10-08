""""What happened" arrives with the coach's saved answer (C2, 2026-10-08).

The coach panel used to save the rating, then GET the moment's Read. The PUT
now carries that same body as ``moment_read``: the same gate, the same read,
computed only after the rating is written (BLIND COACH). A failure or a
gate the GET would refuse omits the key and the rating stays saved.
"""
from __future__ import annotations

import inspect
from unittest.mock import patch

from flask import Flask, request

from routes.v2 import coach as v2_coach
from services.db import db

SNIP = "22222222-2222-4222-8222-222222222222"
SID = "11111111-1111-4111-8111-111111111111"
COACH = "33333333-3333-4333-8333-333333333333"
READ = {"passage": "We, we rebuilt it.", "coach_answer": "no",
        "speaker_answer": "yes", "request": None, "patterns": [],
        "goal": "Sound calm"}


class _World:
    def __init__(self, *, read=READ, gate_open=True):
        self.events: list[str] = []
        self.read = read
        self.gate_open = gate_open
        self.read_calls: list[dict] = []

    def gate(self, session_id, snippet_id):
        self.events.append("gate")
        if not self.gate_open:
            return (Flask.response_class("{}", status=409), 409), None
        return None, session_id

    def moment_read(self, _db, **kwargs):
        self.events.append("read")
        self.read_calls.append(kwargs)
        if isinstance(self.read, Exception):
            raise self.read
        return self.read

    def upsert(self, **_kwargs):
        self.events.append("rating_saved")
        return True


def _patches(world):
    return [
        patch.object(db, "get_snippet_by_id",
                     return_value={"id": SNIP, "session_id": SID, "transcript": "w"}),
        patch.object(db, "v2_get_session_by_id",
                     return_value={"id": SID, "user_id": "speaker-1", "arc_id": "a"}),
        patch.object(db, "get_confidence_labels_by_snippet_ids", return_value={SNIP: []}),
        patch.object(db, "upsert_state_rating", side_effect=world.upsert),
        patch.object(db, "list_take_feedback_self_reports_by_snippet", return_value=[]),
        patch.object(v2_coach, "_rater_language_outcome", return_value=("matched", "en")),
        patch.object(v2_coach, "_session_shows_slides", return_value=False),
        patch("services.coach_judgement_record.canonical_dual_write"),
        patch.object(v2_coach, "_rating_selection",
                     return_value={"selection_reason": "reached_bookmark"}),
        patch.object(v2_coach, "_confidence_chain_judgment", return_value=None),
        patch.object(v2_coach, "_after_coach_judgement"),
        patch.object(v2_coach, "_moment_gate", side_effect=world.gate),
        patch("services.coach_moment_read.moment_read", side_effect=world.moment_read),
    ]


def _call(world, view, *args, method="PUT", body=None):
    app = Flask(__name__)
    raw = inspect.unwrap(view)
    with app.test_request_context(method=method, json=body):
        request.user_id = COACH
        stack = _patches(world)
        for p in stack:
            p.start()
        try:
            result = raw(*args)
        finally:
            for p in reversed(stack):
                p.stop()
    resp, status = result if isinstance(result, tuple) else (result, 200)
    return resp.get_json(), status


def _put(world):
    return _call(world, v2_coach.v2_coach_put_confidence_label, SNIP,
                 body={"state_id": "confidence", "value": "no"})


def test_the_put_carries_exactly_the_moment_get_body():
    put_body, put_status = _put(_World())
    get_body, get_status = _call(_World(), v2_coach.v2_coach_moment_read,
                                 SID, SNIP, method="GET")
    assert (put_status, get_status) == (200, 200)
    assert put_body["saved"] is True
    assert put_body["moment_read"] == get_body == READ


def test_the_read_is_made_only_after_the_rating_is_saved():
    world = _World()
    _put(world)
    assert world.events == ["rating_saved", "gate", "read"]
    assert world.read_calls == [{
        "take_session_id": SID, "snippet_id": SNIP, "rater_id": COACH,
        "owner_user_id": "speaker-1"}]


def test_a_failed_read_omits_the_key_and_the_rating_stays_saved():
    body, status = _put(_World(read=RuntimeError("read broke")))
    assert status == 200 and body["saved"] is True
    assert "moment_read" not in body


def test_a_shut_gate_omits_the_key_as_the_get_would_refuse():
    world = _World(gate_open=False)
    body, status = _put(world)
    assert status == 200 and body["saved"] is True
    assert "moment_read" not in body
    assert "read" not in world.events
