"""`pause_ms` rolls up EXACTLY when the pause counts are known.

THE ARITHMETIC. pause_ms is the MEAN LENGTH of the pauses in a snippet. The
pooled mean across a window is therefore

    sum(every pause length) / count(every pause)

which, from per-snippet means, is the COUNT-weighted mean. Duration-weighting
answers a different question: it assumes pause count scales with snippet
length. Roughly Henderson, but an assumption where an exact figure was one
integer away.

audio_metrics now emits `pause_count` beside `pause_ms`, so a window whose
pieces all carry one is exact. Snippets predating the field fall back to
duration-weighting rather than being dropped — and the fallback is per-window,
not per-piece, because mixing count-weighted and duration-weighted terms in one
mean produces neither quantity.

WHY wpm IS DELIBERATELY NOT COUNT-WEIGHTED: it is already a rate, and the
duration-weighted mean of per-snippet words-per-minute IS total words over
total minutes. Exact already. Weighting it by anything else would break it.

Run: python3 -m unittest tests.test_pause_count_exactness
"""
from __future__ import annotations

import unittest

from services.rate_windows import Piece, build_windows


def _piece(pause_ms, pause_count, duration_ms, start_ms):
    weights = {} if pause_count is None else {"pause_ms": pause_count}
    return Piece(
        snippet_id=f"s{start_ms}",
        recording_id="r",
        start_ms=float(start_ms),
        duration_ms=float(duration_ms),
        words=0,
        values={"pause_ms": pause_ms},
        weights=weights,
    )


def _window_pause_ms(*pieces):
    """pause_ms of the one window two adjacent pieces form (24 s < 60 s)."""
    at, laid_out = 0, []
    for pause_ms, count, duration_ms in pieces:
        laid_out.append(_piece(pause_ms, count, duration_ms, at))
        at += duration_ms
    (window,) = build_windows(laid_out, dimensions=["pause_ms"])
    return window.values["pause_ms"]


class TestTheWindowsPauseMeanIsExact(unittest.TestCase):
    """One long pause in a short snippet, three short pauses in a long one.
    Count-weighted (exact) = (1*900 + 3*300) / 4 = 450; duration-weighted =
    (900*4000 + 300*20000) / 24000 = 400. The fixture is chosen so the two
    disagree, otherwise this would pass without the feature. (wpm stays
    duration-weighted: tests/test_rate_windows.py pins that.)"""

    DURATION_WEIGHTED = (900.0 * 4000 + 300.0 * 20000) / 24000

    def test_counts_make_it_exact_and_anything_less_falls_back_whole(self):
        self.assertAlmostEqual(
            _window_pause_ms((900.0, 1, 4000), (300.0, 3, 20000)), 450.0)
        self.assertAlmostEqual(self.DURATION_WEIGHTED, 400.0)
        # Equal counts reduce to a plain mean, whatever the durations.
        self.assertAlmostEqual(
            _window_pause_ms((400.0, 2, 9000), (600.0, 2, 1000)), 500.0)
        # The fallback is all-or-nothing: one snippet that predates
        # `pause_count`, a zero count (never a divisor, never a silent zero
        # term) or a boolean (bool subclasses int; True is not a count of 1)
        # sends the WHOLE window to duration-weighting, because a mean mixing
        # the two weightings is neither quantity.
        for unusable in (None, 0, True):
            self.assertAlmostEqual(
                _window_pause_ms((900.0, unusable, 4000), (300.0, 3, 20000)),
                self.DURATION_WEIGHTED, msg=repr(unusable))
        # Every snippet written before 2026-08-06: the old behaviour.
        self.assertAlmostEqual(
            _window_pause_ms((900.0, None, 4000), (300.0, None, 20000)),
            self.DURATION_WEIGHTED)


class TestThePipelineEmitsTheCount(unittest.TestCase):

    def test_pause_count_is_wired_into_the_metrics_blob(self):
        """Read the source: audio_metrics needs numpy, which the pure-unit
        env does not have."""
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "services" / "audio_metrics.py").read_text()
        self.assertIn('"pause_count": _compute_pause_count(dbs)', source)

    def test_the_count_and_the_mean_share_one_run_detector(self):
        """Two independent implementations would drift, and the count would
        stop describing the mean it is supposed to weight."""
        import pathlib
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / "services" / "audio_metrics.py").read_text()
        self.assertEqual(source.count("def _pause_runs("), 1)
        for fn in ("_compute_pause_ms", "_compute_pause_count"):
            body = source[source.index(f"def {fn}("):]
            body = body[:body.index("\n\n\n")]
            self.assertIn("_pause_runs(dbs)", body,
                          f"{fn} does not use the shared run detector")


if __name__ == "__main__":
    unittest.main()
