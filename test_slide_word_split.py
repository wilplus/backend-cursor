"""Per-slide word-level transcript split (#6). Pure — no network.

Run: python3 -m unittest test_slide_word_split
"""
from __future__ import annotations

import unittest

from services.slide_word_split import slice_words_for_window, split_words_by_slides


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


SLIDES = [{"title": "S1", "body": ""}, {"title": "S2", "body": ""}]
# slide 0 from t=0, slide 1 from t=5s.
ADV = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}]


class SplitWordsBySlidesTests(unittest.TestCase):
    def test_splits_at_the_click_boundary(self):
        # "hi there" before the click (t<5s), "now go" after → two slides.
        words = [_w("hi", 0.0, 0.5), _w("there", 0.6, 1.0),
                 _w("now", 6.0, 6.4), _w("go", 6.5, 7.0)]
        frags = split_words_by_slides(words, ADV, SLIDES)
        self.assertEqual(len(frags), 2)
        self.assertEqual(frags[0]["slide_index"], 0)
        self.assertEqual(frags[0]["transcript"], "hi there")
        self.assertEqual(frags[1]["slide_index"], 1)
        self.assertEqual(frags[1]["transcript"], "now go")

    def test_fragment_audio_span_from_word_times(self):
        words = [_w("a", 6.0, 6.2), _w("b", 6.8, 7.5)]  # all slide 1
        frags = split_words_by_slides(words, ADV, SLIDES)
        self.assertEqual(len(frags), 1)
        f = frags[0]
        self.assertEqual(f["slide_index"], 1)
        self.assertEqual(f["start_offset_ms"], 6000)
        self.assertEqual(f["duration_ms"], 1500)  # 7.5s - 6.0s

    def test_word_before_first_advance_clamps_to_slide_0(self):
        adv = [{"index": 0, "t_ms": 2000}, {"index": 1, "t_ms": 5000}]
        words = [_w("early", 0.5, 0.9)]  # before the first advance t_ms
        frags = split_words_by_slides(words, adv, SLIDES)
        self.assertEqual(frags[0]["slide_index"], 0)

    def test_three_way_split_back_and_forth(self):
        # slide0 → slide1 → (clicked back? no) — model: index follows timeline.
        adv = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 3000},
               {"index": 0, "t_ms": 6000}]
        words = [_w("one", 1.0, 1.2), _w("two", 4.0, 4.2), _w("three", 7.0, 7.2)]
        frags = split_words_by_slides(words, adv, [SLIDES[0], SLIDES[1]])
        self.assertEqual([f["slide_index"] for f in frags], [0, 1, 0])

    def test_no_timeline_returns_empty_for_fallback(self):
        words = [_w("hi", 0.0, 0.5)]
        self.assertEqual(split_words_by_slides(words, None, SLIDES), [])
        self.assertEqual(split_words_by_slides(words, [], SLIDES), [])

    def test_no_words_or_slides_returns_empty(self):
        self.assertEqual(split_words_by_slides([], ADV, SLIDES), [])
        self.assertEqual(split_words_by_slides(None, ADV, SLIDES), [])
        self.assertEqual(split_words_by_slides([_w("x", 0, 1)], ADV, []), [])

    def test_index_clamped_into_range(self):
        # advance names a slide index beyond the deck → clamp to last slide.
        adv = [{"index": 9, "t_ms": 0}]
        frags = split_words_by_slides([_w("x", 0, 1)], adv, SLIDES)
        self.assertEqual(frags[0]["slide_index"], 1)  # clamped to len-1

    def test_blank_and_malformed_words_skipped(self):
        words = [_w("   ", 0.0, 0.2), "nope", {"word": "ok", "start": 0.3, "end": 0.5}]
        frags = split_words_by_slides(words, ADV, SLIDES)
        self.assertEqual(frags[0]["transcript"], "ok")


class SliceWordsForWindowTests(unittest.TestCase):
    def test_overlap_window(self):
        words = [_w("a", 0.0, 0.5), _w("b", 1.0, 1.5), _w("c", 3.0, 3.5)]
        # window [800ms, 2000ms] → only "b" overlaps
        got = slice_words_for_window(words, 800, 2000)
        self.assertEqual([w["word"] for w in got], ["b"])

    def test_partial_overlap_included(self):
        words = [_w("edge", 1.9, 2.4)]  # starts before 2000ms end, ends after
        got = slice_words_for_window(words, 0, 2000)
        self.assertEqual(len(got), 1)

    def test_empty_safe(self):
        self.assertEqual(slice_words_for_window(None, 0, 1000), [])
        self.assertEqual(slice_words_for_window([], 0, 1000), [])


if __name__ == "__main__":
    unittest.main()
