"""willab — arc-grouped trainings + save-at-publish (founder 2026-07-13).

GET  /v2/user/trainings              — the arc-grouped training tab
POST /v2/internal/publish-session-results — inline snippets[] save-at-publish

(The #186 batch-card routes and their tests were DELETED 2026-07-15 after the
FE switched to the delivery layer — see test_delivery_layer.py.)

Route-level tests (the test_wave2_be.py / test_arc_unlock.py harness: patch
db.* on the v2 module, call the unwrapped handler in a test_request_context).

Run: python3 -m unittest tests.test_arc_batch
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request

    from routes.v2 import user_sessions as v2_user_sessions
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


# (CoachArcPublishTests + StudentArcBatchTests DELETED 2026-07-15 with the
#  #186 batch routes; the delivery flow is covered in test_delivery_layer.py.)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class UserTrainingsTests(unittest.TestCase):
    """GET /v2/user/trainings — arc-grouped, deckless included."""

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2_user_sessions.v2_user_list_trainings.__wrapped__()
            return resp.get_json(), status


    def test_decked_ideal_ready_via_cheap_coach_finalized(self):
        rows = [{
            "id": "s1", "arc_id": "a1", "take_index": 1,
            "created_at": "2026-07-10T10:00:00Z",
            "intake_context": {"topic": "T",
                               "slides": [{"title": "A"}, {"title": "B"}]},
            "results_published_at": None,
        }]
        with patch.object(db.takes, "list_user_arc_sessions",
                          return_value=rows), \
             patch.object(db, "list_arc_batch_deliveries",
                          return_value={}), \
             patch.object(db, "get_coach_best_presentation_edits",
                          return_value={0: "Edited.", 1: "Also edited."}):
            body, status = self._call()
        self.assertTrue(body["trainings"][0]["ideal_ready"])
        self.assertFalse(body["trainings"][0]["batch_verified"])


if __name__ == "__main__":
    unittest.main()
