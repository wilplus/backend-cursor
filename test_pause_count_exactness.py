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

Run: python3 -m unittest test_pause_count_exactness
"""
from __future__ import annotations

import unittest

from services.rate_windows import Piece, _aggregate


def _piece(pause_ms, pause_count, duration_ms, **kw):
    weights = {} if pause_count is None else {"pause_ms": pause_count}
    return Piece(
        snippet_id=kw.get("sid", "s"),
        recording_id="r",
        start_ms=0.0,
        duration_ms=float(duration_ms),
        words=kw.get("words", 0),
        values={"pause_ms": pause_ms},
        weights=weights,
    )


class TestCountWeightingIsExact(unittest.TestCase):

    def test_it_matches_the_hand_computed_pooled_mean(self):
        """Two snippets: one long pause in a short snippet, three short pauses
        in a long one. Exact answer = (1*900 + 3*300) / 4 = 450."""
        pieces = [_piece(900.0, 1, 4000), _piece(300.0, 3, 20000)]
        got = _aggregate(pieces, "pause_ms", seconds=24.0, words=0)
        self.assertAlmostEqual(got, 450.0)

    def test_duration_weighting_would_have_been_wrong_here(self):
        """The fixture is chosen so the two weightings disagree — otherwise
        this suite would pass without the feature. Duration-weighted:
        (900*4000 + 300*20000) / 24000 = 400.0, not 450.0."""
        pieces = [_piece(900.0, 1, 4000), _piece(300.0, 3, 20000)]
        duration_weighted = (900.0 * 4000 + 300.0 * 20000) / 24000
        self.assertAlmostEqual(duration_weighted, 400.0)
        self.assertNotAlmostEqual(
            _aggregate(pieces, "pause_ms", seconds=24.0, words=0),
            duration_weighted)

    def test_equal_counts_reduce_to_a_plain_mean(self):
        pieces = [_piece(400.0, 2, 9000), _piece(600.0, 2, 1000)]
        self.assertAlmostEqual(
            _aggregate(pieces, "pause_ms", seconds=10.0, words=0), 500.0)


class TestTheFallbackIsAllOrNothing(unittest.TestCase):

    def test_one_missing_count_drops_the_whole_window_to_duration(self):
        """Mixing the two weightings in one mean is neither quantity. The
        window must pick one — and the pre-`pause_count` snippet is the one
        that decides."""
        pieces = [_piece(900.0, 1, 4000), _piece(300.0, None, 20000)]
        got = _aggregate(pieces, "pause_ms", seconds=24.0, words=0)
        self.assertAlmostEqual(got, (900.0 * 4000 + 300.0 * 20000) / 24000)

    def test_no_counts_at_all_is_the_old_behaviour(self):
        """Every snippet written before 2026-08-06."""
        pieces = [_piece(900.0, None, 4000), _piece(300.0, None, 20000)]
        self.assertAlmostEqual(
            _aggregate(pieces, "pause_ms", seconds=24.0, words=0), 400.0)

    def test_a_zero_count_is_not_a_weight(self):
        """A snippet contributing no pauses contributes no pause_ms either, so
        a 0 must never become a divisor or silently zero a term."""
        pieces = [_piece(900.0, 0, 4000), _piece(300.0, 3, 20000)]
        got = _aggregate(pieces, "pause_ms", seconds=24.0, words=0)
        self.assertAlmostEqual(got, (900.0 * 4000 + 300.0 * 20000) / 24000)

    def test_a_boolean_count_is_not_a_weight(self):
        """bool subclasses int; True must not pass for a count of 1."""
        pieces = [_piece(900.0, True, 4000), _piece(300.0, 3, 20000)]
        got = _aggregate(pieces, "pause_ms", seconds=24.0, words=0)
        self.assertAlmostEqual(got, (900.0 * 4000 + 300.0 * 20000) / 24000)


class TestWpmStaysDurationWeighted(unittest.TestCase):
    """Duration-weighting IS the exact roll-up for a rate. If a future change
    hands wpm a weight, this fails — and it should."""

    def test_wpm_is_total_words_over_total_minutes(self):
        pieces = [
            Piece(snippet_id="a", recording_id="r", start_ms=0.0,
                  duration_ms=6000.0, words=15, values={"wpm": 150.0}),
            Piece(snippet_id="b", recording_id="r", start_ms=6000.0,
                  duration_ms=54000.0, words=90, values={"wpm": 100.0}),
        ]
        got = _aggregate(pieces, "wpm", seconds=60.0, words=105)
        self.assertAlmostEqual(got, 105 / 1.0)   # 105 words in 60 s


class TestThePipelineEmitsTheCount(unittest.TestCase):

    def test_pause_count_is_wired_into_the_metrics_blob(self):
        """Read the source: audio_metrics needs numpy, which the pure-unit
        env does not have."""
        import pathlib
        source = (pathlib.Path(__file__).parent
                  / "services" / "audio_metrics.py").read_text()
        self.assertIn('"pause_count": _compute_pause_count(dbs)', source)

    def test_the_count_and_the_mean_share_one_run_detector(self):
        """Two independent implementations would drift, and the count would
        stop describing the mean it is supposed to weight."""
        import pathlib
        source = (pathlib.Path(__file__).parent
                  / "services" / "audio_metrics.py").read_text()
        self.assertEqual(source.count("def _pause_runs("), 1)
        for fn in ("_compute_pause_ms", "_compute_pause_count"):
            body = source[source.index(f"def {fn}("):]
            body = body[:body.index("\n\n\n")]
            self.assertIn("_pause_runs(dbs)", body,
                          f"{fn} does not use the shared run detector")


if __name__ == "__main__":
    unittest.main()
