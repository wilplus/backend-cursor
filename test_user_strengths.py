"""GET /v2/user/strengths — grouped strong-sides view.

Deck sessions group strong snippets by slide (timeline-mapped, ranked).
No-deck sessions feed `general`. Empty slides are kept (Q3). Trainings sort
newest-first by SESSION created_at (Q5). Route test mirrors the existing
test_coach_session harness — skips locally without flask, runs in CI.
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
class UserStrengthsTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._origs = {}
        # Two sessions: one with a deck (newer), one without (older).
        DECK_SID, FLAT_SID = "sess-deck", "sess-flat"
        self._patch("get_strong_sides_library", lambda uid, tag=None: [
            # deck session, two strong snippets; library is newest-first
            {"session_id": DECK_SID, "snippet_id": "d1",
             "note": "great open", "tag": "strong", "created_at": "2026-06-10",
             "snippet_ref": {"transcript": "opening line",
                             "audio_ref": "p/deck.wav",
                             "start_offset_ms": 1000, "duration_ms": 7000}},
            {"session_id": DECK_SID, "snippet_id": "d2",
             "note": "good close", "tag": "strong", "created_at": "2026-06-10",
             "snippet_ref": {"transcript": "the wrap-up",
                             "audio_ref": "p/deck.wav",
                             "start_offset_ms": 21000, "duration_ms": 6000}},
            # no-deck session
            {"session_id": FLAT_SID, "snippet_id": "f1",
             "note": "warm voice", "tag": "strong", "created_at": "2026-05-01",
             "snippet_ref": {"transcript": "values moment",
                             "audio_ref": "p/flat.wav",
                             "start_offset_ms": 0, "duration_ms": 8000}},
        ])
        self._patch("v2_get_session_by_id", lambda sid: {
            DECK_SID: {
                "created_at": "2026-06-10T00:00:00Z",
                "intake_context": {
                    "topic": "Q3 launch",
                    "presentation_ref": "https://x/deck.pdf",
                    "slides": [
                        {"title": "Intro", "body": "welcome"},
                        {"title": "Problem", "body": "the pain"},
                        {"title": "Wrap-up", "body": "thank you"},
                    ],
                    "slide_advances": [
                        {"index": 0, "t_ms": 0},
                        {"index": 1, "t_ms": 10000},
                        {"index": 2, "t_ms": 20000},
                    ],
                },
            },
            FLAT_SID: {
                "created_at": "2026-05-01T00:00:00Z",
                "intake_context": {"topic": "casual practice"},  # no slides
            },
        }.get(sid))
        # rank persisted in metrics — d1 rank 2, d2 rank 1 (best)
        self._patch("get_snippets_by_session", lambda sid: [
            {"id": "d1", "metrics": {"rank": 2}},
            {"id": "d2", "metrics": {"rank": 1}},
        ] if sid == DECK_SID else [])

    def tearDown(self):
        for attr, orig in self._origs.items():
            setattr(v2.db, attr, orig)

    def _patch(self, attr, fn):
        self._origs[attr] = getattr(v2.db, attr, None)
        setattr(v2.db, attr, fn)

    def _get(self):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_user_get_strengths.__wrapped__()
            return status, resp.get_json()

    def test_groups_by_session_and_slide(self):
        status, data = self._get()
        self.assertEqual(status, 200)
        # No-deck session → general
        self.assertEqual(len(data["general"]), 1)
        self.assertEqual(data["general"][0]["transcript"], "values moment")
        # Deck session → one training section
        self.assertEqual(len(data["trainings"]), 1)
        t = data["trainings"][0]
        self.assertEqual(t["topic"], "Q3 launch")
        self.assertEqual(t["presentation_ref"], "https://x/deck.pdf")
        # title_slide is the deck's first slide
        self.assertEqual(t["title_slide"]["index"], 0)
        self.assertEqual(t["title_slide"]["title"], "Intro")
        # All 3 slides present (Q3 — empty kept)
        self.assertEqual([s["index"] for s in t["slides"]], [0, 1, 2])

    def test_snippets_placed_under_their_on_screen_slide(self):
        _, data = self._get()
        slides = data["trainings"][0]["slides"]
        # d1 at offset 1000ms is under slide 0 (advance at 0; next at 10000)
        # d2 at offset 21000ms is under slide 2 (advance at 20000)
        self.assertEqual([s["transcript"] for s in slides[0]["strong_snippets"]],
                         ["opening line"])
        self.assertEqual(slides[1]["strong_snippets"], [])    # empty slide kept
        self.assertEqual([s["transcript"] for s in slides[2]["strong_snippets"]],
                         ["the wrap-up"])
        # rank carried through
        self.assertEqual(slides[0]["strong_snippets"][0]["rank"], 2)
        self.assertEqual(slides[2]["strong_snippets"][0]["rank"], 1)

    def test_within_slide_sorted_by_rank_best_first(self):
        # Re-stub: two snippets on the SAME slide with different ranks; the
        # better rank (lower number) must come first.
        self._patch("get_strong_sides_library", lambda uid, tag=None: [
            {"session_id": "s", "snippet_id": "a", "note": "x", "tag": "strong",
             "created_at": "2026-06-10",
             "snippet_ref": {"transcript": "A", "start_offset_ms": 1000,
                             "audio_ref": "p", "duration_ms": 5000}},
            {"session_id": "s", "snippet_id": "b", "note": "y", "tag": "strong",
             "created_at": "2026-06-10",
             "snippet_ref": {"transcript": "B", "start_offset_ms": 2000,
                             "audio_ref": "p", "duration_ms": 5000}},
        ])
        self._patch("v2_get_session_by_id", lambda sid: {
            "created_at": "2026-06-10",
            "intake_context": {
                "slides": [{"title": "Only", "body": "x"}],
                "slide_advances": [{"index": 0, "t_ms": 0}],
            },
        })
        self._patch("get_snippets_by_session", lambda sid: [
            {"id": "a", "metrics": {"rank": 5}},   # worse
            {"id": "b", "metrics": {"rank": 1}},   # best
        ])
        _, data = self._get()
        snips = data["trainings"][0]["slides"][0]["strong_snippets"]
        self.assertEqual([s["transcript"] for s in snips], ["B", "A"])

    def test_trainings_newest_first(self):
        # Two deck sessions; the older one appears FIRST in the library (forcing
        # us to sort by session.created_at, not library order — Q5).
        self._patch("get_strong_sides_library", lambda uid, tag=None: [
            {"session_id": "old", "snippet_id": "o1", "note": "n", "tag": "strong",
             "created_at": "2026-06-09",
             "snippet_ref": {"transcript": "T", "start_offset_ms": 0,
                             "audio_ref": "p", "duration_ms": 5000}},
            {"session_id": "new", "snippet_id": "n1", "note": "n", "tag": "strong",
             "created_at": "2026-06-09",
             "snippet_ref": {"transcript": "T", "start_offset_ms": 0,
                             "audio_ref": "p", "duration_ms": 5000}},
        ])
        self._patch("v2_get_session_by_id", lambda sid: {
            "old": {"created_at": "2026-01-01",
                    "intake_context": {"topic": "old",
                                       "slides": [{"title": "x", "body": ""}],
                                       "slide_advances": [{"index": 0, "t_ms": 0}]}},
            "new": {"created_at": "2026-06-09",
                    "intake_context": {"topic": "new",
                                       "slides": [{"title": "y", "body": ""}],
                                       "slide_advances": [{"index": 0, "t_ms": 0}]}},
        }[sid])
        self._patch("get_snippets_by_session", lambda sid: [
            {"id": "o1" if sid == "old" else "n1", "metrics": {"rank": 1}},
        ])
        _, data = self._get()
        self.assertEqual([t["topic"] for t in data["trainings"]], ["new", "old"])

    def test_empty_library_returns_empty(self):
        self._patch("get_strong_sides_library", lambda uid, tag=None: [])
        status, data = self._get()
        self.assertEqual(status, 200)
        self.assertEqual(data, {"general": [], "trainings": []})


if __name__ == "__main__":
    unittest.main()
