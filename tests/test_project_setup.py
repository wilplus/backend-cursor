"""Canonical project setup read contract."""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request

    from routes.v2 import arcs as v2_arcs
    _IMPORT_ERROR = None
except Exception as error:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = error

PROJECT = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
USER = "11111111-1111-4111-8111-111111111111"
TAKE_1 = "22222222-2222-4222-8222-222222222222"


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
                out = v2_arcs.v2_explore_arc_setup.__wrapped__(PROJECT)
                response, status = out if isinstance(out, tuple) else (out, 200)
                return response.get_json(), status


    def test_every_take_inherits_take_ones_presentation(self):
        """Founder 2026-10-16: the second Take mirrors the first. A later
        take that was somehow recorded against other slides must not carry
        them into the next Take; the words still follow the latest take."""
        takes = [{
            "id": "33333333-3333-4333-8333-333333333333",
            "take_index": 2,
            "recording_kind": "spoken",
            "intake_context": {
                "topic": "t2", "audience": "a2",
                "slides": [{"title": "Other", "body": "deck"}],
                "presentation_ref": None,
            },
        }, {
            "id": TAKE_1,
            "take_index": 1,
            "recording_kind": "spoken",
            "intake_context": {
                "topic": "t1", "audience": "a1",
                "slides": [{"title": "One", "body": "first"}],
                "presentation_ref": "https://example.test/deck.pdf",
            },
        }]
        with patch("routes.v2.arcs.refreshed_media_url", side_effect=lambda r: r):
            body, status = self._get(takes)
        self.assertEqual(status, 200)
        self.assertEqual(body["topic"], "t2")
        self.assertEqual(body["slides"], [{"title": "One", "body": "first"}])
        self.assertEqual(body["presentation_ref"], "https://example.test/deck.pdf")

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
