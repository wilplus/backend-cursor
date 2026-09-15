"""willab — the coach queue label for annotation-mode sessions.

The audio-only annotation upload route (POST /v2/coach/annotation-uploads,
Stage 4 / T4) was deleted on 2026-09-15 (audit Q-A7: no caller in either
repo). What survives is the queue side: a session tagged annotation_mode
still surfaces in the coach queue with the label the FE keys on.

Run: python3 -m unittest tests.test_annotation_mode
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class QueueLabelTests(unittest.TestCase):
    """The annotation session rides the SAME queue, tagged so the FE can
    distinguish it from a student take."""

    def test_queue_row_carries_annotation_mode(self):
        app = Flask(__name__)
        rows = [
            {"id": "a", "user_id": "coach-1",
             "intake_context": {"topic": "Annotation",
                                "language": "en",
                                "annotation_mode": True}},
            {"id": "b", "user_id": "u2",
             "intake_context": {
                 "topic": "A student take", "language": "en",
             }},
        ]
        with app.test_request_context():
            request.user_id = "coach-1"
            # v2_coach_queue lives in routes.v2.coach and resolves these
            # helpers from THAT module — patching the routes.v2_routes
            # re-export would leave the real helpers running.
            with patch.object(db, "list_review_queue", return_value=rows), \
                 patch.object(db, "get_user_proficient_languages",
                              return_value=["en"]), \
                 patch("routes.v2.coach._coach_state_map", return_value={}), \
                 patch("routes.v2.coach._coach_session_state",
                       return_value="to_review"), \
                 patch("routes.v2.coach._coach_pseudonym",
                       return_value="Falcon"), \
                 patch.object(db, "get_snippets_by_session",
                              return_value=[{"id": "s"}]):
                out = v2_coach.v2_coach_queue.__wrapped__()
                resp, status = out if isinstance(out, tuple) else (out, 200)
        by_id = {r["session_id"]: r for r in resp.get_json()}
        self.assertTrue(by_id["a"]["annotation_mode"])
        self.assertFalse(by_id["b"]["annotation_mode"])


if __name__ == "__main__":
    unittest.main()
