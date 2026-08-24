"""Canonical project setup read contract."""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as error:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = error

PROJECT = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
USER = "11111111-1111-4111-8111-111111111111"
TAKE_1 = "22222222-2222-4222-8222-222222222222"
TAKE_2 = "33333333-3333-4333-8333-333333333333"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ProjectSetupEndpointTests(unittest.TestCase):
    """Setup is minimal, latest-spoken-take, and owner-only."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, takes, *, owned=True):
        with self.app.test_request_context():
            request.user_id = USER
            with patch(
                "routes.v2.arcs._arc_owned_by_caller",
                return_value=(owned, takes),
            ):
                out = v2.v2_explore_arc_setup.__wrapped__(PROJECT)
                response, status = out if isinstance(out, tuple) else (out, 200)
                return response.get_json(), status

    def test_latest_take_context_wins(self):
        takes = [
            {"id": TAKE_1, "take_index": 1, "recording_kind": "spoken",
             "intake_context": {"topic": "old topic", "audience": "team",
                                "target_length_seconds": 120}},
            {"id": TAKE_2, "take_index": 2, "recording_kind": "spoken",
             "intake_context": {"topic": "the talk", "audience": "investors",
                                "strategic_context": "board wants the raise",
                                "target_length_seconds": 300,
                                "slides": [{"title": "one"}],
                                "presentation_ref": "deck.pdf"}},
        ]
        body, status = self._get(takes)
        self.assertEqual(status, 200)
        self.assertEqual(body["topic"], "the talk")
        self.assertEqual(body["audience"], "investors")
        self.assertEqual(body["strategic_context"], "board wants the raise")
        self.assertEqual(body["target_length_seconds"], 300)
        self.assertEqual(body["slides"], [{"title": "one"}])
        self.assertEqual(body["presentation_ref"], "deck.pdf")

    def test_payload_is_exactly_the_setup_fields(self):
        takes = [{
            "id": TAKE_1,
            "take_index": 1,
            "recording_kind": "spoken",
            "intake_context": {"topic": "t"},
        }]
        body, _ = self._get(takes)
        self.assertEqual(
            set(body),
            {"arc_id", "topic", "audience", "strategic_context",
             "target_length_seconds", "slides", "presentation_ref"},
        )

    def test_reads_are_not_a_setup_source(self):
        takes = [
            {"id": TAKE_1, "take_index": 1, "recording_kind": "spoken",
             "intake_context": {"topic": "the spoken topic"}},
            {"id": TAKE_2, "take_index": 1, "recording_kind": "read",
             "paired_session_id": TAKE_1,
             "intake_context": {"topic": "a read",
                                "read_target": "ideal_text"}},
        ]
        body, _ = self._get(takes)
        self.assertEqual(body["topic"], "the spoken topic")

    def test_unowned_and_empty_projects_are_not_exposed(self):
        _, status = self._get([], owned=False)
        self.assertEqual(status, 404)
        _, status = self._get([])
        self.assertEqual(status, 404)

    def test_setup_never_leaks_scores_or_take_data(self):
        import json

        takes = [{
            "id": TAKE_1,
            "take_index": 1,
            "recording_kind": "spoken",
            "intake_context": {"topic": "t", "audience": "a"},
        }]
        body, _ = self._get(takes)
        raw = json.dumps(body)
        for banned in ("take_count", "overall_score", "power_score",
                       "take_index", "session_id", "charisma"):
            self.assertNotIn(banned, raw)


if __name__ == "__main__":
    unittest.main()
