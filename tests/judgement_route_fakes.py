"""A speaker may change a judgement; the first answer stays (D-FW-9; 0440;
founder QA1 A, N51.5).

Pins: a different second Confident Voice answer is stored beside the first
(never 409 any more, never an overwrite); going back to the first answer
after a change is a new revision too; a true replay stays a replay; a
rewrite's answer is still final; every reader's row carries the latest
answer with the first beside it, and an unreadable revision table leaves
the first answers; the Album route and coach routing follow the latest
answer; the canonical ledger and the spend keep the first resolution."""
from __future__ import annotations

import uuid
from unittest.mock import patch

from flask import Flask, request

TAKE = str(uuid.uuid4())
OWNER = str(uuid.uuid4())
SNIP = str(uuid.uuid4())


# ── the readers see the latest answer ────────────────────────────────────


# ── the route ─────────────────────────────────────────────────────────────

class _RouteDb:
    def __init__(self, first_outcome="conflict", change=None):
        self.first_outcome = first_outcome
        self.change = change
        self.album: list = []
        self.canonical: list = []
        self.revise_calls: list = []

    def v2_get_session_by_id(self, _sid):
        return {"id": TAKE, "user_id": OWNER, "arc_id": "arc-1",
                "project_id": str(uuid.uuid4())}

    def insert_take_feedback_self_report(self, **kwargs):
        row = {**kwargs, "id": 7, "snippet_id": SNIP}
        return {"outcome": self.first_outcome, "row": row,
                "selected_keys": []}

    def revise_take_feedback_self_report(self, **kwargs):
        self.revise_calls.append(kwargs)
        return self.change

    def record_canonical_feedback_decision(self, **kwargs):
        self.canonical.append(kwargs)
        return {"id": "d"}

    def get_snippet_by_id(self, _sid):
        return {"metrics": {"piece": {"slide_index": 1}}}

    class takes:  # noqa: N801 -- the attribute the route reads
        @staticmethod
        def get_arc_sessions(_arc):
            return []

    def upsert_owner_voice_album_route(self, **kwargs):
        self.album.append(kwargs)
        return True


def _post(db, family="confident_voice", response="yes"):
    from routes.v2 import user_sessions as route

    body = {"feedback_id": "f-1", "feedback_family": family, "response": response}
    parsed = {"feedback_id": "f-1", "feedback_family": family,
              "response": response, "snippet_id": None}
    app = Flask(__name__)
    with patch.object(route, "db", db), \
            patch("services.take_feedback_responses.parse_feedback_response",
                  lambda _b: (dict(parsed), None)), \
            patch("services.voice_album.refresh_voice_album") as refresh, \
            patch("services.judgement_follow_up.follow_up_for_revision",
                  return_value="rewrite") as revision_follow, \
            patch("services.judgement_follow_up.follow_up_for_judgement",
                  return_value="praise") as first_follow, \
            patch("services.intervention_spend.spend") as spend, \
            patch.object(route, "text_update_for_answer", lambda *a, **k: {}):
        with app.test_request_context("/v2/x", method="POST", json=body):
            request.user_id = OWNER
            response, status = route.v2_post_take_feedback_response.__wrapped__(TAKE)
    return status, response.get_json(), {
        "refresh": refresh, "revision": revision_follow, "first": first_follow,
        "spend": spend}
