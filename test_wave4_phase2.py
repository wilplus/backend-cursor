"""UX Wave 4 Phase 2 — snippet→slide alignment (BE-S4). Pure, runs everywhere.

Run: python3 -m unittest test_wave4_phase2
"""
from __future__ import annotations

import unittest

from services.slide_alignment import (
    slide_index_for_offset, slide_for_snippet,
)

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


if __name__ == "__main__":
    unittest.main()
