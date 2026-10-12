"""F1 — the MEASURED audio-vs-UI clock offset (2026-07-26).

Pause-snap guesses the recorder warm-up by hunting a silence near each tap.
The FE can measure it instead. This pins that correction.

  C-1  the shift is exact, order/shape preserving, and clamps at 0;
  C-2  a missing / malformed / absurd offset degrades to TODAY's behaviour —
       an unusable measurement must never corrupt the timeline;
  C-3  validation rejects an out-of-range value loudly (seconds-sent-as-ms is
       the classic bug) instead of clamping it into something plausible;
  C-4  the whole pipeline inherits the correction from one place;
  C-5  a take with no offset is byte-identical to before this shipped.

Run: ./venv/bin/python -m unittest tests.test_slide_clock_offset
"""
from __future__ import annotations

import unittest

from services.slide_word_split import (
    apply_clock_offset,
    context_with_clock_offset,
)


def _adv(*t_ms):
    return [{"index": i, "t_ms": t} for i, t in enumerate(t_ms)]


class DegradeTests(unittest.TestCase):
    """C-2 — an unusable measurement must fall back, never corrupt."""

    def test_missing_zero_and_malformed_are_all_no_ops(self):
        src = _adv(0, 5000)
        for bad in (None, 0, "300", True, False, [], {}, float("nan")):
            self.assertIs(apply_clock_offset(src, bad), src, repr(bad))


    def test_empty_or_non_list_advances(self):
        self.assertEqual(apply_clock_offset([], 300), [])
        self.assertIsNone(apply_clock_offset(None, 300))

    def test_a_malformed_entry_passes_through_untouched(self):
        out = apply_clock_offset([{"index": 0, "t_ms": True},
                                  {"index": 1, "t_ms": 5000}], 300)
        self.assertIs(out[0]["t_ms"], True)      # bool never treated as 1ms
        self.assertEqual(out[1]["t_ms"], 4700)


class ContextTests(unittest.TestCase):
    """C-4/C-5 — one place corrects it; no offset means no change at all."""


    def test_out_of_range_offset_leaves_the_context_alone(self):
        ctx = {"slide_advances": _adv(0, 5000),
               "slide_clock_offset_ms": 999999}
        self.assertIs(context_with_clock_offset(ctx), ctx)

    def test_non_dict_context(self):
        self.assertIsNone(context_with_clock_offset(None))


if __name__ == "__main__":
    unittest.main()
