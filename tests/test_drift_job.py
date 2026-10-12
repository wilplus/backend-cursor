"""Unit tests for services/drift_job.py and the registry roll-up — PM-3.

Covers the two rules that the schema cannot enforce and that a query or a
caller will silently get wrong: SESSION-GRAIN aggregation, and reading the
aggregation from the registry rather than restating Appendix F.4.

Run: python3 -m unittest tests.test_drift_job
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
