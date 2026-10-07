"""D-ML-1 — the pure measurement math behind scripts/measure_transcripts.py.

Pinned here:
  M-1  WER is Levenshtein edits over reference words; case and punctuation
       are never errors; an empty reference is None, not zero.
  M-2  wrong-slide share judges only pipeline words that align to a hand
       word; insertions are reported as unjudged, never as right or wrong.
  M-3  the offset error is signed (pipeline − truth), per boundary, over the
       boundaries both sides have, and a count mismatch is reported.
  M-4  totals are micro-averaged, per tag over the items carrying it.
"""
from __future__ import annotations

import unittest

from services.transcript_measure import (
    align,
    boundary_offset_error,
    hyp_tokens_with_index,
    normalize_tokens,
    pipeline_boundaries_ms,
    slide_assignment,
    summarize,
    summarize_by_tag,
    true_slide_at,
    word_error_rate,
)


class NormalizeTests(unittest.TestCase):
    def test_case_and_punctuation_fall_away(self):
        self.assertEqual(normalize_tokens("Store, don't — STOP!"),
                         ["store", "dont", "stop"])

    def test_none_is_empty(self):
        self.assertEqual(normalize_tokens(None), [])

    def test_hyp_tokens_keep_source_index(self):
        words = [{"word": "Hi,"}, {"word": "—"}, "junk", {"word": "there"}]
        self.assertEqual(hyp_tokens_with_index(words), (["hi", "there"], [0, 3]))


class WerTests(unittest.TestCase):
    """M-1."""

    def test_identical_is_zero(self):
        r = word_error_rate(["a", "b", "c"], ["a", "b", "c"])
        self.assertEqual((r["errors"], r["wer"]), (0, 0.0))

    def test_counts_each_edit_kind(self):
        r = word_error_rate(["the", "cat", "sat", "down"],
                            ["the", "cap", "sat", "down", "now"])
        self.assertEqual(r["substitutions"], 1)
        self.assertEqual(r["insertions"], 1)
        self.assertEqual(r["deletions"], 0)
        self.assertAlmostEqual(r["wer"], 0.5)

    def test_deletion(self):
        r = word_error_rate(["a", "b", "c"], ["a", "c"])
        self.assertEqual((r["deletions"], r["errors"]), (1, 1))

    def test_empty_reference_is_none_not_zero(self):
        self.assertIsNone(word_error_rate([], ["x"])["wer"])
        self.assertEqual(word_error_rate([], ["x"])["insertions"], 1)

    def test_alignment_is_in_order_and_complete(self):
        pairs = align(["a", "b"], ["b"])
        self.assertEqual(pairs, [(0, None), (1, 0)])


class SlideAssignmentTests(unittest.TestCase):
    """M-2."""

    def test_wrong_slide_share(self):
        ref = [["hello", "world"], ["second", "slide"]]
        hyp = ["hello", "world", "second", "slide"]
        pipeline_slides = [0, 0, 0, 1]          # "second" landed on slide 0
        r = slide_assignment(ref, hyp, pipeline_slides)
        self.assertEqual((r["judged"], r["wrong_slide"]), (4, 1))
        self.assertAlmostEqual(r["wrong_slide_share"], 0.25)
        self.assertEqual(r["per_slide"][1], {"slide_index": 1, "judged": 2, "wrong": 1})

    def test_insertions_are_unjudged(self):
        r = slide_assignment([["a"]], ["a", "um"], [0, 0])
        self.assertEqual((r["judged"], r["unjudged_insertions"]), (1, 1))
        self.assertEqual(r["wrong_slide_share"], 0.0)

    def test_nothing_judged_is_none(self):
        self.assertIsNone(slide_assignment([["a"]], [], [])["wrong_slide_share"])

    def test_true_slide_at(self):
        changes = [10.0, 20.0]
        self.assertEqual(true_slide_at(5.0, changes), 0)
        self.assertEqual(true_slide_at(10.0, changes), 1)
        self.assertEqual(true_slide_at(25.0, changes), 2)


class OffsetTests(unittest.TestCase):
    """M-3."""

    def test_boundaries_drop_start_entry_and_sort(self):
        adv = [{"index": 1, "t_ms": 9000}, {"index": 0, "t_ms": 0},
               {"index": 2, "t_ms": 4000}, {"t_ms": True}, "junk"]
        self.assertEqual(pipeline_boundaries_ms(adv), [4000, 9000])

    def test_signed_error_per_boundary(self):
        r = boundary_offset_error([10.0, 20.0],
                                  [{"index": 0, "t_ms": 0},
                                   {"index": 1, "t_ms": 10150},
                                   {"index": 2, "t_ms": 19900}])
        self.assertEqual(r["errors_ms"], [150, -100])
        self.assertAlmostEqual(r["mean_ms"], 25.0)
        self.assertAlmostEqual(r["mean_abs_ms"], 125.0)
        self.assertEqual(r["max_abs_ms"], 150)
        self.assertFalse(r["count_mismatch"])

    def test_count_mismatch_is_reported(self):
        r = boundary_offset_error([10.0, 20.0], [{"index": 1, "t_ms": 10000}])
        self.assertTrue(r["count_mismatch"])
        self.assertEqual((r["compared"], r["errors_ms"]), (1, [0]))

    def test_no_boundaries_is_none(self):
        r = boundary_offset_error([], [])
        self.assertIsNone(r["mean_ms"])
        self.assertEqual(r["compared"], 0)


class SummaryTests(unittest.TestCase):
    """M-4."""

    ITEMS = [
        {"tags": ["accent:pl"], "wer": {"ref_words": 10, "errors": 2},
         "slide_assignment": {"judged": 8, "wrong_slide": 2},
         "offset": {"errors_ms": [100]}},
        {"tags": ["accent:none", "noise:cafe"], "wer": {"ref_words": 30, "errors": 3},
         "slide_assignment": {"judged": 30, "wrong_slide": 0},
         "offset": {"errors_ms": [-50, 20]}},
    ]

    def test_micro_average(self):
        s = summarize(self.ITEMS)
        self.assertAlmostEqual(s["wer"], 5 / 40)
        self.assertAlmostEqual(s["wrong_slide_share"], 2 / 38)
        self.assertEqual(s["boundaries_compared"], 3)
        self.assertAlmostEqual(s["offset_mean_abs_ms"], 170 / 3)
        self.assertEqual(s["offset_max_abs_ms"], 100)

    def test_per_tag(self):
        by_tag = summarize_by_tag(self.ITEMS)
        self.assertEqual(sorted(by_tag), ["accent:none", "accent:pl", "noise:cafe"])
        self.assertAlmostEqual(by_tag["accent:pl"]["wer"], 0.2)
        self.assertEqual(by_tag["noise:cafe"]["items"], 1)

    def test_empty(self):
        s = summarize([])
        self.assertIsNone(s["wer"])
        self.assertIsNone(s["offset_max_abs_ms"])


if __name__ == "__main__":
    unittest.main()
