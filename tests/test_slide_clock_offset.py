"""
STORY    As a speaker using slides, I want my words matched to the right slide
         even when the recorder starts late, so that each slide's paragraph of
         my Ideal Text has the words I said while it was on screen.
         (Critical path: record -> process -> Ideal Text.)
OUTCOME
  O1  A measured offset moves every slide tap onto the audio clock by exactly
      that amount (never before 0), so the first words after a tap land on
      the new slide instead of the old one.
  O2  No offset, or one that is unusable (zero, not a number, absurd), leaves
      the timeline exactly as recorded.
  O3  The intake refuses an out-of-range offset loudly (seconds sent as ms is
      the classic bug) and keeps a sane one as sent.
PROVES   O1 -> test_a_measured_offset_moves_the_first_words_onto_the_new_slide
         O2 -> test_no_or_unusable_offset_changes_nothing
         O3 -> test_the_intake_refuses_an_out_of_range_offset
WHY      F1 (2026-07-26): the recorder warm-up put the first words after a tap
         on the previous slide.
"""
from __future__ import annotations

import unittest

from services.intake_context import IntakeContextError, validate_intake_context_body
from services.slide_word_split import build_slide_transcripts, context_with_clock_offset

SLIDES = [{"title": "Intro"}, {"title": "Plan"}, {"title": "Ask"}]


def _adv(*t_ms):
    return [{"index": i, "t_ms": t} for i, t in enumerate(t_ms)]


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


# The speaker taps NEXT at 5.0 s and 9.0 s on the UI clock. The recorder
# started 300 ms late, so on the AUDIO clock the slides changed at 4.7 s and
# 8.7 s, and "budget" (4.8 s) and "please" (8.8 s) were said on the new slide.
WORDS = [_w("hello", 1.0, 1.4), _w("budget", 4.8, 5.2),
         _w("approve", 7.0, 7.4), _w("please", 8.8, 9.2)]


class ClockOffsetTests(unittest.TestCase):

    def test_a_measured_offset_moves_the_first_words_onto_the_new_slide(self):
        raw = {"slide_advances": _adv(100, 5000, 9000)}
        uncorrected = build_slide_transcripts(WORDS, raw["slide_advances"], SLIDES)
        # Without the correction the words sit on the slide before the tap.
        self.assertEqual([s["transcript"] for s in uncorrected],
                         ["hello budget", "approve please", ""])

        ctx = context_with_clock_offset({**raw, "slide_clock_offset_ms": 300})
        # Exact shift, order and shape kept; the first tap clamps at 0.
        self.assertEqual(ctx["slide_advances"], _adv(0, 4700, 8700))
        slides = build_slide_transcripts(WORDS, ctx["slide_advances"], SLIDES)
        self.assertEqual([s["transcript"] for s in slides],
                         ["hello", "budget approve", "please"])

    def test_no_or_unusable_offset_changes_nothing(self):
        for offset in (None, 0, float("nan"), True, "300", 999_999):
            ctx = {"slide_advances": _adv(0, 5000), "slide_clock_offset_ms": offset}
            self.assertIs(context_with_clock_offset(ctx), ctx, repr(offset))
        # A tap that is not a number is passed through untouched; the rest move.
        ctx = context_with_clock_offset({
            "slide_advances": [{"index": 0, "t_ms": True}, {"index": 1, "t_ms": 5000}],
            "slide_clock_offset_ms": 300})
        self.assertEqual(ctx["slide_advances"],
                         [{"index": 0, "t_ms": True}, {"index": 1, "t_ms": 4700}])
        self.assertIsNone(context_with_clock_offset(None))

    def test_the_intake_refuses_an_out_of_range_offset(self):
        with self.assertRaisesRegex(IntakeContextError, "slide_clock_offset_ms"):
            validate_intake_context_body({"slide_clock_offset_ms": 300_000})
        self.assertEqual(
            validate_intake_context_body(
                {"slide_clock_offset_ms": 300})["slide_clock_offset_ms"], 300)


if __name__ == "__main__":
    unittest.main()
