"""GET /v2/user/library enrichment (FE #152) — slide/rank/session_topic/
presentation_ref are added per entry; entries without a deck get nulls so the
FE degrades to the flat list cleanly.

Skips locally without flask; runs in CI.
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _RT_ERR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _RT_ERR = e


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class LibraryEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._origs = {}
        # Two entries from two sessions: one with a deck, one without.
        self._patch("get_strong_sides_library", lambda uid, tag=None: [
            {"id": "e1", "session_id": "deck", "snippet_id": "d1",
             "note": "great open", "tag": "strong", "created_at": "2026-06-10",
             "snippet_ref": {"transcript": "opening line",
                             "start_offset_ms": 1000, "duration_ms": 7000,
                             "audio_ref": "p/d.wav"}},
            {"id": "e2", "session_id": "flat", "snippet_id": "f1",
             "note": "warm", "tag": "strong", "created_at": "2026-05-01",
             "snippet_ref": {"transcript": "warmth",
                             "start_offset_ms": 0, "duration_ms": 5000,
                             "audio_ref": "p/f.wav"}},
        ])
        self._patch("v2_get_session_by_id", lambda sid: {
            "deck": {"intake_context": {
                "topic": "Q3 launch",
                "presentation_ref": "https://x/deck.pdf",
                "slides": [{"title": "Intro", "body": "welcome"},
                           {"title": "Body",  "body": "details"}],
                "slide_advances": [{"index": 0, "t_ms": 0},
                                   {"index": 1, "t_ms": 10000}],
            }},
            "flat": {"intake_context": {"topic": "casual practice"}},
        }.get(sid))
        self._patch("get_snippets_by_session", lambda sid: [
            {"id": "d1", "metrics": {"rank": 2}},
        ] if sid == "deck" else [])

    def tearDown(self):
        for attr, orig in self._origs.items():
            setattr(v2.db, attr, orig)

    def _patch(self, attr, fn):
        self._origs[attr] = getattr(v2.db, attr, None)
        setattr(v2.db, attr, fn)

    def _get(self):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_user_get_library.__wrapped__()
            return status, resp.get_json()

    def test_deck_entry_carries_slide_rank_topic_ref(self):
        status, data = self._get()
        self.assertEqual(status, 200)
        deck = next(e for e in data["entries"] if e["session_id"] == "deck")
        self.assertEqual(deck["slide"], {"index": 0, "title": "Intro", "body": "welcome"})
        self.assertEqual(deck["rank"], 2)
        self.assertEqual(deck["session_topic"], "Q3 launch")
        self.assertEqual(deck["presentation_ref"], "https://x/deck.pdf")

    def test_no_deck_entry_has_nulls_and_topic(self):
        # Degrade path: FE renders this as today's flat "General" list.
        _, data = self._get()
        flat = next(e for e in data["entries"] if e["session_id"] == "flat")
        self.assertIsNone(flat["slide"])
        self.assertIsNone(flat["rank"])
        self.assertIsNone(flat["presentation_ref"])
        self.assertEqual(flat["session_topic"], "casual practice")

    def test_backward_compatible_shape(self):
        # Existing keys + snippet_ref still there for old consumers.
        _, data = self._get()
        e = data["entries"][0]
        for k in ("id", "session_id", "snippet_id", "note", "tag",
                  "created_at", "snippet_ref"):
            self.assertIn(k, e)


if __name__ == "__main__":
    unittest.main()
