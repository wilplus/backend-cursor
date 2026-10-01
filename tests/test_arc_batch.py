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


def _sessions(n=3, user_id="u1", published=()):
    out = []
    for i in range(1, n + 1):
        out.append({
            "id": f"s{i}", "user_id": user_id, "arc_id": "a1",
            "take_index": i, "created_at": f"2026-07-1{i}T10:00:00Z",
            "intake_context": {"topic": "Quarterly sync",
                               "slides": [{"title": "One"}]},
            "results_published_at": (
                "2026-07-13T12:00:00Z" if i in published else None
            ),
        })
    return out


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

    def test_groups_by_arc_and_includes_deckless(self):
        rows = [
            # decked arc a1, 2 takes
            {"id": "s1", "arc_id": "a1", "take_index": 1,
             "created_at": "2026-07-10T10:00:00Z",
             "intake_context": {"topic": "Deck talk",
                                "slides": [{"title": "One"}]},
             "results_published_at": "2026-07-11T09:00:00Z"},
            {"id": "s2", "arc_id": "a1", "take_index": 2,
             "created_at": "2026-07-11T10:00:00Z",
             "intake_context": {"topic": "Deck talk",
                                "slides": [{"title": "One"}]},
             "results_published_at": None},
            # DECKLESS arc a2 — must appear as its own training
            {"id": "s3", "arc_id": "a2", "take_index": 1,
             "created_at": "2026-07-12T10:00:00Z",
             "intake_context": {"topic": "No-deck story"},
             "results_published_at": None},
        ]
        with patch.object(db.takes, "list_user_arc_sessions",
                          return_value=rows), \
             patch.object(db, "list_arc_batch_deliveries",
                          return_value={"a2": {
                              "arc_id": "a2",
                              "published_at": "2026-07-13T08:00:00Z"}}), \
             patch.object(db, "get_coach_best_presentation_edits",
                          return_value={}):
            body, status = self._call()
        self.assertEqual(status, 200)
        trainings = body["trainings"]
        self.assertEqual(len(trainings), 2)
        by_arc = {t["arc_id"]: t for t in trainings}
        # deckless training exists, is batch_verified + ideal_ready via the
        # delivery row (its publish already required coach_finalized).
        a2 = by_arc["a2"]
        self.assertEqual(a2["topic"], "No-deck story")
        self.assertTrue(a2["batch_verified"])
        self.assertTrue(a2["ideal_ready"])
        self.assertEqual(a2["take_count"], 1)
        # decked training lists its takes in take order with reviewed flags.
        a1 = by_arc["a1"]
        self.assertFalse(a1["batch_verified"])
        self.assertEqual([t["take_index"] for t in a1["takes"]], [1, 2])
        self.assertTrue(a1["takes"][0]["coach_reviewed"])
        self.assertFalse(a1["takes"][1]["coach_reviewed"])
        self.assertEqual(a1["takes_target"], 3)
        # newest training first
        self.assertEqual(trainings[0]["arc_id"], "a2")

    def test_no_arcs_empty_list(self):
        with patch.object(db.takes, "list_user_arc_sessions", return_value=[]), \
             patch.object(db, "list_arc_batch_deliveries",
                          return_value={}):
            body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(body["trainings"], [])

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
