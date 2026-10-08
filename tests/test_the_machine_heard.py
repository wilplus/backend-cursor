"""The machine heard (D-CP-3; the coach panel lock, flow 5 "What happened":
You · the speaker · The machine heard).

Pins: the moment read's `heard` lists, in words, what the machine heard
for every kind: the error labels on an error moment, the confident cues
behind the praise, the clearer version's reason, everything on a note
(ambiguity), and an explicit "nothing"; never a number; the read is still
behind the blind gate (409 before this coach's own rating, and nothing is
read about the moment before it)."""
from __future__ import annotations

import json
import re
import uuid
from unittest.mock import patch

from flask import Flask, request

from services.coach_moment_read import HEARD_NOTHING, machine_heard, moment_read
from services.delivery_cues import CUE_KEYS
from services.tracked_changes import CLEARER_VERSION_REASONS


class _Db:
    def __init__(self, *, request=None, suggestion=None, suggestion_error=None):
        self.request = request
        self.suggestion = suggestion
        self.suggestion_error = suggestion_error

    def get_snippets_by_session(self, _take):
        return [{"id": "snip-1", "transcript": "We rebuilt it.", "slide_index": 0}]

    def list_take_feedback_self_reports_by_snippet(self, _snip):
        return []

    def get_own_state_ratings_for_session(self, _take, _rater):
        return {"snip-1": {"value": "no", "unrateable": False}}

    def get_user_profile(self, _uid):
        return {}

    def get_exercise_coach_request(self, _take, _snip):
        return self.request

    def get_moment_suggestion(self, _snip):
        if self.suggestion_error:
            raise self.suggestion_error
        return self.suggestion

    def list_speaking_errors(self, active_only=True):
        return [{"error_id": "rushing", "label": "Rushing"},
                {"error_id": "hedging", "label": "Hedging"}]

    def get_confident_voice_exercise_assignment(self, _t, _s):
        return None

    def list_diagnostic_exercises(self):
        return []


def _request(kind, tags=(), answer_kind=None):
    return {"id": "req-1", "take_session_id": "take-1", "snippet_id": "snip-1",
            "kind": kind, "answer_kind": answer_kind, "observed_tags": list(tags),
            "resolution": None}


PRAISE = {"snippet_id": "snip-1", "kind": "emphasize", "trigger": "confident",
          "cue_keys": ["wide_range", "landed_ending", "not_a_cue"]}
CLEARER = {"snippet_id": "snip-1", "kind": "replace", "trigger": "unconfident"}


def _heard(db):
    return machine_heard(db, db.request, "snip-1")


def test_an_error_moment_hears_the_error_labels():
    db = _Db(request=_request("error", ["rushing", "hedging"]), suggestion=PRAISE)
    assert _heard(db) == [
        {"kind": "error", "key": "rushing", "label": "Rushing"},
        {"kind": "error", "key": "hedging", "label": "Hedging"},
    ]


def test_a_praise_moment_hears_the_confident_cues_behind_it():
    db = _Db(request=_request("praise"), suggestion=PRAISE)
    assert _heard(db) == [{"kind": "cue", "key": "wide_range"},
                          {"kind": "cue", "key": "landed_ending"}]
    assert all(item["key"] in CUE_KEYS for item in _heard(db))


def test_a_clearer_version_moment_hears_its_reason():
    db = _Db(request=_request("rewrite"), suggestion=CLEARER)
    assert _heard(db) == [{"kind": "reason", "key": "weak_delivery_read"}]
    assert _heard(db)[0]["key"] in CLEARER_VERSION_REASONS.values()
    # A trigger outside the fixed reasons is not a reason.
    db = _Db(request=_request("rewrite"), suggestion={**CLEARER, "trigger": "polish"})
    assert _heard(db) == [HEARD_NOTHING]


def test_a_note_hears_everything_the_machine_heard():
    db = _Db(request=_request("praise", ["rushing"], answer_kind="ambiguity"),
             suggestion=PRAISE)
    assert _heard(db) == [
        {"kind": "error", "key": "rushing", "label": "Rushing"},
        {"kind": "cue", "key": "wide_range"},
        {"kind": "cue", "key": "landed_ending"},
    ]


def test_nothing_heard_is_said_as_nothing():
    for db in (_Db(request=_request("error")),
               _Db(request=_request("praise")),
               _Db(request=_request("rewrite")),
               _Db(request=_request("ambiguity")),
               _Db(request=None),
               _Db(request=_request("praise"), suggestion_error=RuntimeError("down"))):
        assert _heard(db) == [{"kind": "nothing", "key": "nothing"}]


def test_the_read_carries_heard_in_words_and_no_number():
    db = _Db(request=_request("error", ["rushing"]), suggestion=PRAISE)
    out = moment_read(db, take_session_id="take-1", snippet_id="snip-1",
                      rater_id="coach-1", owner_user_id=None)
    assert out["heard"] == [{"kind": "error", "key": "rushing", "label": "Rushing"}]
    assert not re.search(r"\d", json.dumps(out["heard"]))
    for item in out["heard"]:
        assert all(isinstance(value, str) for value in item.values())


def test_the_read_is_still_behind_the_blind_gate():
    from routes.v2 import coach as route

    session_id, snippet_id = str(uuid.uuid4()), str(uuid.uuid4())

    class _GateDb:
        def v2_get_session_by_id(self, _sid):
            return {"id": session_id, "user_id": "owner-1"}

    app = Flask(__name__)
    with patch.object(route, "db", _GateDb()), \
            patch.object(route, "_snippet_owner_map",
                         lambda _sid: {snippet_id: session_id}), \
            patch.object(route, "_coach_state_map", lambda *_a, **_k: {}), \
            patch("services.coach_moment_read.moment_read") as read:
        with app.test_request_context("/v2/x"):
            request.user_id = "coach-1"
            response, status = route.v2_coach_moment_read.__wrapped__(
                session_id, snippet_id)
        assert status == 409
        assert response.get_json()["code"] == "BLIND_RATING_REQUIRED"
        read.assert_not_called()
        # Audio unclear is an abstention: the door stays shut.
        with patch.object(route, "_coach_state_map", lambda *_a, **_k: {
                snippet_id: {"rating_value": None, "rating_unrateable": True}}):
            with app.test_request_context("/v2/x"):
                request.user_id = "coach-1"
                response, status = route.v2_coach_moment_read.__wrapped__(
                    session_id, snippet_id)
        assert status == 409
        read.assert_not_called()
