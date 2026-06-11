"""UX Wave 4 Phase 2 — snippet→slide alignment (BE-S4). Pure, runs everywhere.

Run: python3 -m unittest test_wave4_phase2
"""
from __future__ import annotations

import unittest

from services.slide_alignment import (
    slide_index_for_offset, slide_for_snippet, build_compat_input,
)

UID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

SLIDES = [
    {"title": "Intro", "body": "welcome"},
    {"title": "Problem", "body": "the pain point"},
    {"title": "Solution", "body": "our fix"},
]
ADV = [  # tap timeline: slide 0 from 0, →1 at 5s, →2 at 10s, BACK to 1 at 15s
    {"index": 0, "t_ms": 0},
    {"index": 1, "t_ms": 5000},
    {"index": 2, "t_ms": 10000},
    {"index": 1, "t_ms": 15000},
]


class OffsetMappingTests(unittest.TestCase):
    def test_greatest_t_le_offset(self):
        self.assertEqual(slide_index_for_offset(0, ADV), 0)
        self.assertEqual(slide_index_for_offset(4999, ADV), 0)
        self.assertEqual(slide_index_for_offset(5000, ADV), 1)
        self.assertEqual(slide_index_for_offset(12000, ADV), 2)

    def test_back_navigation_is_real(self):
        # after the back-tap at 15s, a later snippet maps to the EARLIER index 1
        self.assertEqual(slide_index_for_offset(16000, ADV), 1)

    def test_before_first_or_empty(self):
        self.assertIsNone(slide_index_for_offset(0, []))
        self.assertIsNone(slide_index_for_offset(0, None))


class SlideForSnippetTests(unittest.TestCase):
    def test_timeline_exact(self):
        sl = slide_for_snippet(
            {"start_offset_ms": 11000, "transcript": "anything"}, ADV, SLIDES)
        self.assertEqual(sl, {"index": 2, "title": "Solution", "body": "our fix"})

    def test_fallback_text_overlap_when_no_timeline(self):
        # no advances → best text overlap; "pain point" → slide 1 (Problem)
        sl = slide_for_snippet(
            {"start_offset_ms": 0, "transcript": "let me describe the pain point here"},
            None, SLIDES)
        self.assertEqual(sl["index"], 1)

    def test_no_slides_returns_none(self):
        self.assertIsNone(slide_for_snippet({"start_offset_ms": 0}, ADV, None))

    def test_out_of_range_index_guarded(self):
        # an advance pointing past the slide list → no slide, not a crash
        bad = [{"index": 9, "t_ms": 0}]
        self.assertIsNone(
            slide_for_snippet({"start_offset_ms": 1000, "transcript": ""}, bad, SLIDES))


class CompatInputTests(unittest.TestCase):
    """BE-S5 pure input-builder: group spoken transcript by its slide."""

    def test_groups_spoken_by_slide(self):
        out = build_compat_input({
            "slides": [{"title": "A", "body": "a"}, {"title": "B", "body": "b"}],
            "snippets": [
                {"transcript": "hello world", "slide": {"index": 0}},
                {"transcript": "more on A", "slide": {"index": 0}},
                {"transcript": "now B", "slide": {"index": 1}},
            ],
        })
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["slide_index"], 0)
        self.assertIn("hello world", out[0]["spoken_while_shown"])
        self.assertIn("more on A", out[0]["spoken_while_shown"])
        self.assertIn("now B", out[1]["spoken_while_shown"])

    def test_empty_without_slides_or_mapping(self):
        self.assertEqual(build_compat_input({}), [])
        self.assertEqual(build_compat_input({"snippets": [{"transcript": "x"}]}), [])
        # slides present but no snippet carries a `slide` → nothing to score
        self.assertEqual(build_compat_input(
            {"slides": [{"title": "A", "body": "a"}], "snippets": [{"transcript": "x"}]}), [])


# ── route shape (skip without flask; run in CI) ──
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
class SlideAlignmentRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._o = getattr(v2.db, "v2_get_session_by_id", None)
        v2.db.v2_get_session_by_id = lambda sid: {"id": sid}

    def tearDown(self):
        if self._o is not None:
            v2.db.v2_get_session_by_id = self._o

    def _call(self, compat):
        import services.slide_alignment as sa
        orig = sa.compute_slide_compatibility
        sa.compute_slide_compatibility = lambda sid: compat
        try:
            with self.app.test_request_context():
                request.user_id = "coach-1"
                resp, status = v2.v2_coach_slide_alignment.__wrapped__(UID)
                return status, resp.get_json()
        finally:
            sa.compute_slide_compatibility = orig

    def test_returns_commentary(self):
        status, data = self._call({
            "per_slide": [{"slide_index": 0, "covered": True, "comment": "ok"}],
            "overall_comment": "good",
        })
        self.assertEqual(status, 200)
        self.assertEqual(data["overall_comment"], "good")

    def test_available_false_when_none(self):
        status, data = self._call(None)
        self.assertEqual(status, 200)
        self.assertFalse(data["available"])


if __name__ == "__main__":
    unittest.main()
