"""F1 — word→slide boundary exposure/impact metrics (2026-07-26).

Pinned here:
  F1-1  the three numbers the founder asked for: words at risk near a boundary,
        words that CHANGE slide under pause-snap, and boundaries with no pause
        to snap into;
  F1-2  the metrics describe the SNAP ITSELF, not the live flag — so they are
        comparable across takes and across a flag flip;
  F1-3  unmeasurable takes return None (never a silent zero that would read as
        "no problem here");
  F1-4  AC-9 + LIVE LOOP: pure, never raises, nothing user-facing.

Run: ./venv/bin/python -m unittest test_slide_boundary_metrics
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.slide_boundary_metrics import boundary_metrics

SLIDES = [{"title": "one"}, {"title": "two"}]


def _w(*pairs):
    """[(seconds, token)] → Whisper-shaped word dicts."""
    return [{"word": t, "start": s, "end": s + 0.2} for s, t in pairs]


def _adv(*t_ms):
    return [{"index": i, "t_ms": t} for i, t in enumerate(t_ms)]


class UnmeasurableTests(unittest.TestCase):
    """F1-3 — None, never a zero. A zero would read as 'measured, no problem'."""

    def test_no_deck(self):
        self.assertIsNone(boundary_metrics(_w((1.0, "hi")), _adv(0, 5000), []))

    def test_no_words(self):
        self.assertIsNone(boundary_metrics([], _adv(0, 5000), SLIDES))

    def test_no_taps(self):
        self.assertIsNone(boundary_metrics(_w((1.0, "hi")), [], SLIDES))

    def test_only_the_recording_start_entry_is_not_a_boundary(self):
        # t_ms=0 is "recording began", not a slide change anyone can be on the
        # wrong side of.
        self.assertIsNone(boundary_metrics(_w((1.0, "hi")), _adv(0), SLIDES))


class RiskExposureTests(unittest.TestCase):
    """F1-1a — how many words sit close enough to a tap for drift to move."""

    def test_counts_words_within_the_window_either_side(self):
        #  4.6s = 400ms BEFORE the 5.0s tap → at risk
        #  5.4s = 400ms AFTER            → at risk
        #  4.4s = 600ms before           → outside ±500ms, NOT at risk
        words = _w((4.4, "outside"), (4.6, "before"), (5.4, "after"),
                   (9.0, "far"))
        out = boundary_metrics(words, _adv(0, 5000), SLIDES, risk_ms=500)
        self.assertEqual(out["words_at_risk"], 2)
        self.assertEqual(out["words_total"], 4)

    def test_boundary_is_inclusive_at_exactly_risk_ms(self):
        out = boundary_metrics(_w((4.5, "edge")), _adv(0, 5000), SLIDES,
                               risk_ms=500)
        self.assertEqual(out["words_at_risk"], 1)

    def test_a_word_near_two_boundaries_counts_once(self):
        # Guards a double-count: the word must not inflate the exposure figure.
        out = boundary_metrics(_w((5.0, "between")), _adv(0, 4800, 5200),
                               SLIDES, risk_ms=500)
        self.assertEqual(out["words_at_risk"], 1)

    def test_risk_is_not_impact(self):
        # Words can be at risk while nothing actually moves — the two numbers
        # measure different things and must not be conflated.
        words = _w((4.9, "a"), (5.1, "b"))
        out = boundary_metrics(words, _adv(0, 5000), SLIDES,
                               risk_ms=500, window_ms=0)
        self.assertEqual(out["words_at_risk"], 2)
        self.assertEqual(out["words_reassigned"], 0)


class ImpactTests(unittest.TestCase):
    """F1-1b — words whose slide actually CHANGES under the snap."""

    def test_words_after_a_tap_move_back_when_the_boundary_snaps_later(self):
        # Speech, then a real pause, then the tap lands mid-speech: snapping the
        # boundary into the pause moves the post-tap words to the OTHER slide.
        words = _w((0.5, "opening"), (1.0, "line"),
                   (4.0, "second"), (4.3, "slide"))
        # Tap at 3000ms sits inside the 1.2s→4.0s silence already; move it to
        # 3900 so it falls mid-speech and the snap has work to do.
        out = boundary_metrics(words, _adv(0, 3900), SLIDES,
                               window_ms=1500, min_gap_ms=200)
        self.assertGreaterEqual(out["boundaries_moved"], 1)
        self.assertGreater(out["shift_ms_max"], 0)

    def test_no_movement_when_snapping_is_disabled_by_a_zero_window(self):
        words = _w((0.5, "a"), (4.0, "b"))
        out = boundary_metrics(words, _adv(0, 3900), SLIDES, window_ms=0)
        self.assertEqual(out["words_reassigned"], 0)
        self.assertEqual(out["boundaries_moved"], 0)
        self.assertEqual(out["shift_ms_max"], 0)

    def test_boundaries_unmoved_accounts_for_every_boundary(self):
        out = boundary_metrics(_w((0.5, "a"), (4.0, "b")), _adv(0, 3900),
                               SLIDES, window_ms=1500)
        self.assertEqual(out["boundaries_moved"] + out["boundaries_unmoved"],
                         out["boundaries_total"])


class FlagIndependenceTests(unittest.TestCase):
    """F1-2 — the numbers describe the SNAP, not any live setting, so they
    stay comparable across time.

    They always did, and that is why they survived the flag's deletion
    (founder 2026-08-11): pause-snap is no longer applied to any take, so
    these are now purely diagnostic — "how much of this take sits near a
    boundary, and was a pause even available there" — which is how we learn
    whether the FE's MEASURED clock offset is doing its job."""

    def _run(self, env_says):
        # The env var is inert now; measuring under both values proves it.
        with patch.dict("os.environ",
                        {"SLIDE_PAUSE_SNAP_ENABLED": "1" if env_says else "0"}):
            return boundary_metrics(_w((0.5, "a"), (4.0, "b")), _adv(0, 3900),
                                    SLIDES, window_ms=1500)

    def test_identical_measurements_either_way(self):
        on, off = self._run(True), self._run(False)
        for key in ("words_at_risk", "words_reassigned", "boundaries_moved",
                    "shift_ms_max"):
            self.assertEqual(on[key], off[key], key)

    def test_snap_enabled_now_reports_the_TRUTH_the_pipeline_never_snaps(self):
        # The field used to echo a live flag. The flag is gone, so it states
        # a fact instead — and it stays in the payload rather than being
        # dropped, because a historical row that said true means something
        # different from one that says false, and a reader needs to be able
        # to tell which era a measurement came from.
        self.assertFalse(self._run(True)["snap_enabled"])
        self.assertFalse(self._run(False)["snap_enabled"])


class RobustnessTests(unittest.TestCase):
    """F1-4 — LIVE LOOP: a measurement never breaks the analysis pipeline."""

    def test_malformed_input_never_raises(self):
        for words in (None, "nonsense", [None], [{"word": "x"}],
                      [{"word": "x", "start": "late"}],
                      [{"word": "", "start": 1.0}]):
            boundary_metrics(words, _adv(0, 5000), SLIDES)   # must not raise

    def test_bool_timestamps_are_rejected_not_coerced(self):
        # Python's bool-is-int would otherwise make True a 1ms word/tap.
        out = boundary_metrics([{"word": "x", "start": True}],
                               _adv(0, 5000), SLIDES)
        self.assertIsNone(out)
        self.assertIsNone(boundary_metrics(
            _w((1.0, "x")), [{"index": 1, "t_ms": True}], SLIDES))

    def test_unsorted_words_are_handled(self):
        out = boundary_metrics(_w((9.0, "last"), (0.5, "first")),
                               _adv(0, 5000), SLIDES)
        self.assertEqual(out["words_total"], 2)


class NoUserSurfaceTests(unittest.TestCase):
    """AC-9 — this is internal. Pin that the module cannot leak into a user
    payload by importing anything that serves one."""

    def test_module_is_pure_and_serves_nothing(self):
        import inspect
        import services.slide_boundary_metrics as mod
        src = inspect.getsource(mod)
        self.assertNotIn("jsonify", src)
        self.assertNotIn("from routes", src)
        self.assertNotIn("services.db", src)


if __name__ == "__main__":
    unittest.main()


class CoverageSplitTests(unittest.TestCase):
    """THE decisive split: "didn't move" has two opposite meanings, and the
    FE-clock-offset decision hinges on telling them apart."""

    def test_no_pause_near_the_tap_is_counted_as_unreachable(self):
        # Continuous speech through the tap: no gap >= min_gap_ms anywhere, so
        # pause-snap can never fix this boundary. This is the number that
        # argues FOR measuring the offset exactly.
        words = _w(*[(i * 0.3, f"w{i}") for i in range(30)])   # 300ms cadence
        out = boundary_metrics(words, _adv(0, 4500), SLIDES,
                               window_ms=1500, min_gap_ms=600)
        self.assertEqual(out["boundaries_no_pause"], 1)
        self.assertEqual(out["boundaries_already_aligned"], 0)

    def test_a_boundary_already_sitting_in_a_pause_is_not_unreachable(self):
        # Big silence 2.0s -> 5.0s, tap at 3500 sits inside it. Nothing to fix.
        words = _w((1.0, "before"), (1.5, "words"), (5.0, "after"), (5.4, "it"))
        out = boundary_metrics(words, _adv(0, 3500), SLIDES,
                               window_ms=1500, min_gap_ms=200)
        self.assertEqual(out["boundaries_no_pause"], 0)
        self.assertEqual(out["boundaries_no_pause"]
                         + out["boundaries_already_aligned"]
                         + out["boundaries_moved"],
                         out["boundaries_total"])

    def test_the_three_buckets_always_account_for_every_boundary(self):
        for advs in (_adv(0, 3900), _adv(0, 2000, 6000), _adv(0, 500)):
            out = boundary_metrics(
                _w((0.5, "a"), (1.0, "b"), (4.0, "c"), (7.0, "d")),
                advs, SLIDES, window_ms=1500, min_gap_ms=200)
            if not out:
                continue
            self.assertEqual(
                out["boundaries_moved"] + out["boundaries_no_pause"]
                + out["boundaries_already_aligned"],
                out["boundaries_total"], str(advs))

    def test_unmoved_is_still_reported_and_stays_consistent(self):
        out = boundary_metrics(_w((0.5, "a"), (4.0, "b")), _adv(0, 3900),
                               SLIDES, window_ms=1500, min_gap_ms=200)
        self.assertEqual(out["boundaries_unmoved"],
                         out["boundaries_total"] - out["boundaries_moved"])
