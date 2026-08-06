"""Unit tests for services/rate_windows.py — D33.

The three that matter, because each fails silently: a denominator inflated by
a pause, a window stitched across two takes, and an idempotency break that
duplicates rows on every pipeline retry.

Run: python3 -m unittest test_rate_windows
"""
from __future__ import annotations

import unittest

from services import rate_windows as rw


def _p(sid, start_s, dur_s, *, rec="r1", words=0, **values):
    return rw.Piece(snippet_id=sid, recording_id=rec,
                    start_ms=start_s * 1000.0, duration_ms=dur_s * 1000.0,
                    words=words, values=values)


class TestTheSixtySecondCase(unittest.TestCase):
    """The recording that motivated the build: 60 s, four ~15 s snippets,
    four refusals and zero usable rate measurements."""

    PIECES = [_p(f"s{i}", i * 15.0, 15.0, words=35, wpm=140.0, fillers=2.0)
              for i in range(4)]

    def test_snippet_grain_would_refuse_all_four(self):
        from services import dimension_registry as registry
        for p in self.PIECES:
            self.assertFalse(registry.meets_minimum("wpm", seconds=15.0))

    def test_windowing_turns_four_refusals_into_a_measurement(self):
        windows = rw.build_windows(self.PIECES, dimensions=["wpm", "fillers"])
        self.assertTrue(any(w.meets for w in windows),
                        "60 s of speech still produced no usable window")

    def test_the_remainder_is_kept_not_dropped(self):
        """F.5 — dropping short windows hides how much speech falls through."""
        windows = rw.build_windows(self.PIECES, dimensions=["wpm"])
        self.assertEqual(len(windows), 2)          # 45 s + 15 s
        self.assertTrue(windows[0].meets)
        self.assertFalse(windows[1].meets)

    def test_every_second_of_speech_is_accounted_for(self):
        windows = rw.build_windows(self.PIECES, dimensions=["wpm"])
        self.assertAlmostEqual(sum(w.seconds for w in windows), 60.0)


class TestGapHandling(unittest.TestCase):
    """The part that has to be right — an inflated denominator is silently
    wrong rather than visibly missing."""

    def test_a_pause_cannot_enter_the_denominator(self):
        """THE guard. Two 20 s snippets five minutes apart: the window's
        seconds are 40, not 340. Wall-clock would put the filler rate off by
        a factor of eight and it would still look like a number."""
        pieces = [_p("a", 0.0, 20.0, fillers=4.0),
                  _p("b", 320.0, 20.0, fillers=4.0)]
        windows = rw.build_windows(pieces, dimensions=["fillers"],
                                   max_gap_seconds=1e9)   # force one window
        self.assertEqual(len(windows), 1)
        self.assertAlmostEqual(windows[0].seconds, 40.0)
        self.assertAlmostEqual(windows[0].values["fillers"], 12.0)  # 8 / (2/3)

    def test_a_long_silence_breaks_the_window(self):
        pieces = [_p("a", 0.0, 20.0), _p("b", 320.0, 20.0)]
        self.assertEqual(len(rw.build_windows(pieces)), 2)

    def test_a_short_pause_does_not_break_the_window(self):
        """A rhetorical pause is part of speaking, not a break in it."""
        pieces = [_p("a", 0.0, 20.0), _p("b", 22.0, 20.0)]
        self.assertEqual(len(rw.build_windows(pieces)), 1)

    def test_windows_never_cross_a_recording(self):
        """A take boundary is a HARD break. `_emit_drift_telemetry` is handed
        every snippet in the SESSION, which spans takes, and a rate averaged
        across two takes measures neither."""
        pieces = [_p("a", 0.0, 20.0, rec="take1"),
                  _p("b", 20.0, 20.0, rec="take2")]
        windows = rw.build_windows(pieces)
        self.assertEqual(len(windows), 2)
        self.assertEqual([w.recording_id for w in windows], ["take1", "take2"])

    def test_takes_with_overlapping_offsets_do_not_interleave(self):
        """Offsets restart near zero in each take, so sorting by start_ms
        alone would zip two takes together — which is exactly how a
        cross-take average gets built by accident."""
        pieces = [_p("a1", 0.0, 15.0, rec="take1"),
                  _p("b1", 0.0, 15.0, rec="take2"),
                  _p("a2", 15.0, 15.0, rec="take1"),
                  _p("b2", 15.0, 15.0, rec="take2")]
        windows = rw.build_windows(pieces)
        for w in windows:
            self.assertIsNotNone(w.recording_id)
        self.assertEqual(len(windows), 2)
        self.assertEqual(sorted(w.recording_id for w in windows),
                         ["take1", "take2"])


class TestAggregation(unittest.TestCase):

    def test_a_rate_is_summed_over_speech_minutes(self):
        """fillers is per_minute in the registry: counts summed, divided by
        the window's own speech time."""
        pieces = [_p("a", 0.0, 30.0, fillers=3.0),
                  _p("b", 30.0, 30.0, fillers=3.0)]
        w = rw.build_windows(pieces, dimensions=["fillers"])[0]
        self.assertAlmostEqual(w.values["fillers"], 6.0)   # 6 marks / 1.0 min

    def test_wpm_is_duration_weighted_which_is_the_exact_ratio(self):
        """A duration-weighted mean of per-snippet words-per-minute IS total
        words over total minutes. An unweighted mean would over-weight the
        short snippet — 150 instead of the true 120."""
        pieces = [_p("long", 0.0, 30.0, words=60, wpm=120.0),
                  _p("short", 30.0, 2.0, words=6, wpm=180.0)]
        w = rw.build_windows(pieces, dimensions=["wpm"])[0]
        exact = w.words / w.minutes
        self.assertAlmostEqual(w.values["wpm"], exact, places=6)
        self.assertNotAlmostEqual(w.values["wpm"], 150.0)

    def test_a_dimension_with_no_values_yields_none_not_zero(self):
        pieces = [_p("a", 0.0, 40.0)]
        w = rw.build_windows(pieces, dimensions=["fillers"])[0]
        self.assertIsNone(w.values["fillers"])

    def test_an_unknown_dimension_is_none_not_a_guessed_mean(self):
        pieces = [_p("a", 0.0, 40.0, invented=5.0)]
        w = rw.build_windows(pieces, dimensions=["invented"])[0]
        self.assertIsNone(w.values["invented"])


class TestIdempotencyAndJunk(unittest.TestCase):

    def test_the_anchor_is_stable_so_a_retry_replaces(self):
        """A window has no id of its own. Writing snippet_id NULL would make
        NULLs DISTINCT in the unique index, so every pipeline retry would
        INSERT duplicates instead of replacing them."""
        pieces = [_p(f"s{i}", i * 15.0, 15.0) for i in range(4)]
        first = rw.build_windows(pieces, dimensions=["wpm"])
        again = rw.build_windows(list(reversed(pieces)), dimensions=["wpm"])
        self.assertEqual([w.anchor_snippet_id for w in first],
                         [w.anchor_snippet_id for w in again])
        self.assertTrue(all(w.anchor_snippet_id for w in first))

    def test_zero_and_missing_durations_are_dropped(self):
        pieces = [_p("ok", 0.0, 40.0), _p("zero", 40.0, 0.0),
                  rw.Piece(snippet_id="", recording_id="r1", start_ms=0.0,
                           duration_ms=10_000.0)]
        windows = rw.build_windows(pieces)
        self.assertEqual(sum(w.pieces for w in windows), 1)

    def test_no_pieces_no_windows(self):
        self.assertEqual(rw.build_windows([]), [])

    def test_the_window_target_is_the_appendix_preferred_figure(self):
        """F.2: minimum 30 s, PREFERRED 40 s. `meets` gates on the minimum;
        the builder targets the preferred."""
        self.assertEqual(rw.WINDOW_SECONDS, 40.0)
        self.assertTrue(rw.Window("a", "r", 30.0, 0, 1).meets)
        self.assertFalse(rw.Window("a", "r", 29.9, 0, 1).meets)


if __name__ == "__main__":
    unittest.main()
