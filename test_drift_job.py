"""Unit tests for services/drift_job.py and the registry roll-up — PM-3.

Covers the two rules that the schema cannot enforce and that a query or a
caller will silently get wrong: SESSION-GRAIN aggregation, and reading the
aggregation from the registry rather than restating Appendix F.4.

Run: python3 -m unittest test_drift_job
"""
from __future__ import annotations

import unittest

from services import drift_job
from services import dimension_registry as registry


def _row(session, dim, value, **kw):
    row = {"session_id": session, "dimension_id": dim, "raw_value": value,
           "insufficient_data": False, "fired": None,
           "benchmark_tier": "CORPUS_REL", "benchmark_version": "measure-v1",
           "evaluated_at": "2026-08-05T10:00:00Z"}
    row.update(kw)
    return row


class TestSessionGrain(unittest.TestCase):
    def test_many_snippets_in_one_session_collapse_to_one_value(self):
        """THE rule. Thirty correlated rows must not become thirty
        observations — that narrows the control limits by ~sqrt(30) and makes
        the monitor fire on its own sampling."""
        rows = [_row("s1", "wpm", 100.0 + i) for i in range(30)]
        out = drift_job._session_values(rows)
        self.assertEqual(len(out["wpm"]), 1)

    def test_separate_sessions_stay_separate(self):
        rows = [_row("s1", "wpm", 100.0), _row("s2", "wpm", 200.0)]
        out = drift_job._session_values(rows)
        self.assertEqual(len(out["wpm"]), 2)

    def test_insufficient_data_rows_are_dropped_not_averaged(self):
        """SPEC D30 — those rows carry no value by construction. Averaging a
        None into a session would invent one."""
        rows = [_row("s1", "wpm", 100.0),
                _row("s1", "wpm", None, insufficient_data=True)]
        out = drift_job._session_values(rows)
        self.assertEqual(out["wpm"]["s1"], 100.0)

    def test_garbage_ignored(self):
        rows = [_row("s1", "wpm", "abc"), _row(None, "wpm", 5.0),
                _row("s2", None, 5.0), _row("s3", "wpm", 120.0)]
        out = drift_job._session_values(rows)
        self.assertEqual(list(out["wpm"]), ["s3"])

    def test_levels_average_and_rates_add(self):
        """The registry decides which, so this behaviour follows Appendix F.4
        rather than a hardcoded rule."""
        self.assertEqual(registry.aggregation_of("wpm"), "mean")
        self.assertEqual(registry.aggregation_of("fillers"), "per_minute")
        wpm = drift_job._session_values(
            [_row("s1", "wpm", 100.0), _row("s1", "wpm", 200.0)])
        fillers = drift_job._session_values(
            [_row("s1", "fillers", 2.0), _row("s1", "fillers", 3.0)])
        self.assertEqual(wpm["wpm"]["s1"], 150.0)     # averaged
        self.assertEqual(fillers["fillers"]["s1"], 5.0)   # added


class TestMinting(unittest.TestCase):
    def test_refuses_below_the_floor(self):
        """Ten buckets over a handful of sessions puts one observation in each
        and PSI then reads whatever the sampling did."""
        values = {"wpm": {f"s{i}": float(i) for i in range(5)}}
        self.assertEqual(drift_job._mint_reference(values, version="v"), [])

    def test_mints_ten_deciles_with_an_open_top(self):
        values = {"wpm": {f"s{i}": float(i) for i in range(100)}}
        rows = drift_job._mint_reference(values, version="frozen_v1")
        self.assertEqual(len(rows), 10)
        self.assertEqual([r["decile"] for r in rows], list(range(1, 11)))
        # Decile 10 is +infinity, or new extremes would fall outside the scale.
        self.assertIsNone(rows[-1]["upper_bound"])
        self.assertIsNotNone(rows[0]["upper_bound"])

    def test_cut_points_ascend(self):
        values = {"wpm": {f"s{i}": float(i) for i in range(100)}}
        rows = drift_job._mint_reference(values, version="v")
        bounds = [r["upper_bound"] for r in rows if r["upper_bound"] is not None]
        self.assertEqual(bounds, sorted(bounds))

    def test_n_at_freeze_records_what_it_rests_on(self):
        values = {"wpm": {f"s{i}": float(i) for i in range(60)}}
        rows = drift_job._mint_reference(values, version="v")
        self.assertTrue(all(r["n_at_freeze"] == 60 for r in rows))


class TestBucketing(unittest.TestCase):
    CUTS = [(d, float(d * 10)) for d in range(1, 10)] + [(10, None)]

    def test_assigns_by_cut_point(self):
        self.assertEqual(drift_job._bucket(5.0, self.CUTS), 1)
        self.assertEqual(drift_job._bucket(45.0, self.CUTS), 5)

    def test_above_every_cut_lands_in_the_top_decile(self):
        self.assertEqual(drift_job._bucket(9_999.0, self.CUTS), 10)

    def test_boundary_is_inclusive_below(self):
        self.assertEqual(drift_job._bucket(10.0, self.CUTS), 1)
        self.assertEqual(drift_job._bucket(10.001, self.CUTS), 2)


class TestRegistryRollup(unittest.TestCase):
    def setUp(self):
        # The roll-up lives in the REGISTRY, not in session_metrics — it is a
        # registry operation, and session_metrics imports the DB client, which
        # would make a pure aggregation untestable without a database.
        self.roll = registry.rollup

    def test_fillers_is_a_rate_per_minute_not_a_sum(self):
        """The whole point: Appendix F.4 (E6) says per minute, and the legacy
        global_fillers sums. Two quantities, one name."""
        out = self.roll({"fillers": [2, 3, 5]}, minutes=2.0, words=400)
        self.assertEqual(out["fillers"], 5.0)      # 10 marks over 2 minutes

    def test_levels_average(self):
        out = self.roll({"wpm": [100, 200]}, minutes=1.0, words=100)
        self.assertEqual(out["wpm"], 150.0)

    def test_missing_denominator_yields_none_not_a_wrong_number(self):
        out = self.roll({"fillers": [2, 3]}, minutes=None, words=0)
        self.assertIsNone(out["fillers"])

    def test_unknown_dimension_is_none_not_a_guessed_mean(self):
        """Refusing to aggregate something the spec has not defined is the
        safe direction."""
        out = self.roll({"invented": [1, 2, 3]}, minutes=1.0, words=100)
        self.assertIsNone(out["invented"])

    def test_empty_and_garbage(self):
        out = self.roll({"wpm": [], "pause_ms": [None, "x"]},
                        minutes=1.0, words=10)
        self.assertIsNone(out["wpm"])
        self.assertIsNone(out["pause_ms"])

    def test_every_live_dimension_rolls_up(self):
        """A live dimension that returns None for real inputs is a silent
        hole in the report."""
        inputs = {d.dimension_id: [1.0, 2.0] for d in registry.live_dimensions()}
        out = self.roll(inputs, minutes=1.0, words=100)
        for dim_id, value in out.items():
            self.assertIsNotNone(value, f"{dim_id} did not roll up")


if __name__ == "__main__":
    unittest.main()
