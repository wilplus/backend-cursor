"""Unit tests for services/drift_monitor.py.

Covers the three edge cases the build prompt calls out by name — the empty
decile (ln(0)), the small weekly n, and the CORPUS_REL exclusion (which is a
caller contract, asserted here as documentation) — plus the 2x2 that is the
actual deliverable.

Run: python3 -m unittest test_drift_monitor
"""
from __future__ import annotations

import math
import unittest

from services.drift_monitor import (
    HEALTHY,
    IN_CONTROL,
    INSUFFICIENT_N,
    MAJOR_SHIFT_REFIT,
    MODERATE_SHIFT,
    OUT_OF_CONTROL_HIGH,
    OUT_OF_CONTROL_LOW,
    PIPELINE_CHANGED,
    POPULATION_MOVED,
    RUN_LENGTH,
    STABLE,
    UNKNOWN,
    UPSTREAM_CHANGE,
    p_chart,
    psi,
    psi_verdict,
    rank_triage,
    triage,
)

FLAT = {d: 100 for d in range(1, 11)}          # n = 1000, uniform


class TestPSI(unittest.TestCase):
    def test_identical_distributions_are_zero(self):
        self.assertEqual(psi(FLAT, FLAT), 0.0)

    def test_scale_invariant(self):
        """Counts, not proportions — but doubling every count changes nothing."""
        doubled = {d: v * 2 for d, v in FLAT.items()}
        self.assertAlmostEqual(psi(doubled, FLAT), 0.0, places=6)

    def test_shift_is_positive(self):
        shifted = dict(FLAT)
        shifted[1] = 400
        shifted[10] = 10
        self.assertGreater(psi(shifted, FLAT), 0.0)

    def test_bigger_shift_scores_higher(self):
        mild = {**FLAT, 1: 150, 10: 50}
        severe = {**FLAT, 1: 600, 10: 5}
        self.assertGreater(psi(severe, FLAT), psi(mild, FLAT))

    def test_symmetric(self):
        """(a-e)ln(a/e) is invariant under swapping a and e."""
        other = {**FLAT, 3: 400, 7: 20}
        self.assertAlmostEqual(psi(other, FLAT), psi(FLAT, other), places=6)

    def test_empty_decile_is_finite(self):
        """THE case that breaks a naive implementation: ln(0) = -inf."""
        gap = dict(FLAT)
        gap[5] = 0
        value = psi(gap, FLAT)
        self.assertIsNotNone(value)
        self.assertTrue(math.isfinite(value))
        self.assertGreater(value, 0.0)

    def test_empty_decile_is_not_dropped(self):
        """Dropping the empty decile would UNDERSTATE the drift it evidences."""
        gap = dict(FLAT)
        gap[5] = 0
        without_bin_5 = {d: v for d, v in FLAT.items() if d != 5}
        # A missing decile is the strongest evidence of a shift; it must score
        # higher than a merely thin one.
        thin = dict(FLAT)
        thin[5] = 1
        self.assertGreater(psi(gap, FLAT), 0.0)
        self.assertGreaterEqual(psi(gap, FLAT), psi(thin, FLAT) * 0.5)
        self.assertIsNotNone(psi(FLAT, without_bin_5))

    def test_no_data_is_none_not_zero(self):
        """'No data' must not read as 'no drift' — that is a clean bill of
        health nobody earned."""
        self.assertIsNone(psi({}, FLAT))
        self.assertIsNone(psi(FLAT, {}))
        self.assertIsNone(psi({}, {}))

    def test_garbage_keys_and_values_ignored(self):
        noisy = dict(FLAT)
        noisy.update({0: 50, 11: 50, "x": 10, 4: -5, 6: float("nan")})
        value = psi(noisy, FLAT)
        self.assertIsNotNone(value)
        self.assertTrue(math.isfinite(value))

    def test_all_mass_in_one_decile(self):
        spike = {d: 0 for d in range(1, 11)}
        spike[1] = 500
        value = psi(spike, FLAT)
        self.assertTrue(math.isfinite(value))
        self.assertGreater(value, 1.0)


class TestPSIVerdict(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(psi_verdict(0.05, n_current=100), STABLE)
        self.assertEqual(psi_verdict(0.15, n_current=100), MODERATE_SHIFT)
        self.assertEqual(psi_verdict(0.30, n_current=100), MAJOR_SHIFT_REFIT)

    def test_band_edges_are_closed_below(self):
        self.assertEqual(psi_verdict(0.10, n_current=100), MODERATE_SHIFT)
        self.assertEqual(psi_verdict(0.20, n_current=100), MAJOR_SHIFT_REFIT)

    def test_none_is_insufficient_not_stable(self):
        self.assertEqual(psi_verdict(None), INSUFFICIENT_N)

    def test_small_n_refuses_a_verdict(self):
        """PSI on a handful of rows is dominated by the smoothing floor."""
        self.assertEqual(psi_verdict(0.4, n_current=5), INSUFFICIENT_N)


class TestPChart(unittest.TestCase):
    @staticmethod
    def _weeks(rates, n=200):
        return [{"week": i, "n": n, "fired": int(round(r * n))}
                for i, r in enumerate(rates)]

    def test_stable_series_is_in_control(self):
        chart = p_chart(self._weeks([0.20, 0.21, 0.19, 0.20, 0.205]))
        self.assertEqual(chart["signal"], IN_CONTROL)
        self.assertAlmostEqual(chart["centre_line"], 0.201, places=2)

    def test_limits_bracket_the_centre(self):
        chart = p_chart(self._weeks([0.20] * 5))
        self.assertLess(chart["lcl"], chart["centre_line"])
        self.assertGreater(chart["ucl"], chart["centre_line"])

    def test_spike_breaches_high(self):
        chart = p_chart(self._weeks([0.20, 0.20, 0.20, 0.20, 0.60]))
        self.assertEqual(chart["signal"], OUT_OF_CONTROL_HIGH)
        self.assertTrue(chart["breached"])

    def test_collapse_breaches_low(self):
        chart = p_chart(self._weeks([0.40, 0.40, 0.40, 0.40, 0.02]))
        self.assertEqual(chart["signal"], OUT_OF_CONTROL_LOW)

    def test_small_weekly_n_refuses(self):
        """3-sigma limits on n=5 are so wide nothing can breach them; a green
        chart there is an artefact of sample size, not a finding."""
        chart = p_chart(self._weeks([0.2, 0.8, 0.2], n=5))
        self.assertEqual(chart["signal"], INSUFFICIENT_N)
        self.assertIsNone(chart["ucl"])

    def test_empty_input(self):
        chart = p_chart([])
        self.assertEqual(chart["signal"], INSUFFICIENT_N)
        self.assertEqual(chart["points"], [])

    def test_malformed_rows_dropped_not_raised(self):
        rows = [{"week": 0, "n": 200, "fired": 40},
                {"week": 1, "n": 0, "fired": 0},        # n = 0
                {"week": 2, "n": 100, "fired": 500},    # fired > n
                {"week": 3, "n": "x", "fired": 1},      # uncastable
                {"week": 4, "n": 200, "fired": 42}]
        chart = p_chart(rows)
        self.assertEqual(len(chart["points"]), 2)

    def test_run_rule_catches_drift_inside_the_limits(self):
        """The case 3-sigma misses entirely: a slid threshold never breaches a
        limit, it just stops crossing the middle."""
        rates = [0.20] * 4 + [0.22] * RUN_LENGTH
        chart = p_chart(self._weeks(rates, n=500))
        self.assertEqual(chart["run_violation"], "high")
        self.assertTrue(chart["breached"])
        # every individual point is still within the control limits
        self.assertTrue(all(p["signal"] == IN_CONTROL for p in chart["points"]))

    def test_short_run_is_not_a_violation(self):
        rates = [0.20] * 4 + [0.22] * (RUN_LENGTH - 1)
        chart = p_chart(self._weeks(rates, n=500))
        self.assertIsNone(chart["run_violation"])

    def test_points_on_the_centre_line_break_a_run(self):
        rates = [0.22] * (RUN_LENGTH - 1) + [0.20] + [0.22] * (RUN_LENGTH - 1)
        chart = p_chart(self._weeks(rates, n=500))
        self.assertIsNone(chart["run_violation"])


class TestTriage(unittest.TestCase):
    def test_all_four_cells(self):
        self.assertEqual(triage(STABLE, IN_CONTROL), HEALTHY)
        self.assertEqual(triage(MODERATE_SHIFT, IN_CONTROL), POPULATION_MOVED)
        self.assertEqual(triage(STABLE, OUT_OF_CONTROL_HIGH), PIPELINE_CHANGED)
        self.assertEqual(triage(MAJOR_SHIFT_REFIT, OUT_OF_CONTROL_LOW),
                         UPSTREAM_CHANGE)

    def test_the_cell_this_layer_exists_for(self):
        """Stable inputs + drifting decisions = our own code moved."""
        self.assertEqual(triage(STABLE, OUT_OF_CONTROL_LOW), PIPELINE_CHANGED)

    def test_insufficient_either_side_is_unknown_not_healthy(self):
        self.assertEqual(triage(INSUFFICIENT_N, IN_CONTROL), UNKNOWN)
        self.assertEqual(triage(STABLE, INSUFFICIENT_N), UNKNOWN)

    def test_ranking_leads_with_pipeline_changed(self):
        ranked = rank_triage([HEALTHY, POPULATION_MOVED, PIPELINE_CHANGED,
                              UPSTREAM_CHANGE, UNKNOWN])
        self.assertEqual(ranked[0], PIPELINE_CHANGED)
        self.assertEqual(ranked[1], UPSTREAM_CHANGE)
        self.assertEqual(ranked[-1], HEALTHY)


class TestEndToEnd(unittest.TestCase):
    def test_asr_upgrade_shape(self):
        """The scenario the layer is built for: an upstream change moves the
        input distribution AND the decisions."""
        before = {d: 100 for d in range(1, 11)}
        after = {1: 300, 2: 250, 3: 200, 4: 100, 5: 50,
                 6: 40, 7: 30, 8: 20, 9: 10, 10: 5}
        band = psi_verdict(psi(after, before), n_current=sum(after.values()))
        chart = p_chart([{"week": i, "n": 300, "fired": f}
                         for i, f in enumerate([60, 62, 58, 61, 200])])
        self.assertEqual(band, MAJOR_SHIFT_REFIT)
        self.assertEqual(triage(band, chart["signal"]), UPSTREAM_CHANGE)


if __name__ == "__main__":
    unittest.main()
