"""The machine heard (D-CP-3; the coach panel lock, flow 5 "What happened":
You · the speaker · The machine heard).

Pins: the moment read's `heard` lists, in words, what the machine heard
for every kind: the error labels on an error moment, the confident cues
behind the praise, the clearer version's reason, everything on a note
(ambiguity), and an explicit "nothing"; never a number; the read is still
behind the blind gate (409 before this coach's own rating, and nothing is
read about the moment before it)."""
from __future__ import annotations

import uuid
from unittest.mock import patch

from flask import Flask, request


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
