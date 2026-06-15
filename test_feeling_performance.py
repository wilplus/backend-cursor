"""Feeling × performance correlation (willab audit assembly). Pure.

Run: python3 -m unittest test_feeling_performance
"""
from __future__ import annotations

import unittest

from services.feeling_performance import (
    correlate_feeling_performance, session_performance, stress_as_fuel,
)


class SessionPerformanceTests(unittest.TestCase):
    def test_mean_of_overall_scores(self):
        snips = [
            {"metrics": {"overall_score": 0.8}},
            {"metrics": {"overall_score": 0.6}},
        ]
        self.assertAlmostEqual(session_performance(snips), 0.7)

    def test_none_when_no_scores(self):
        self.assertIsNone(session_performance([]))
        self.assertIsNone(session_performance([{"metrics": {}}]))
        self.assertIsNone(session_performance("nope"))

    def test_ignores_non_numeric_and_bools(self):
        snips = [{"metrics": {"overall_score": True}},
                 {"metrics": {"overall_score": 0.5}}]
        self.assertAlmostEqual(session_performance(snips), 0.5)


class CorrelateTests(unittest.TestCase):
    def test_buckets_mean_per_feeling_desc(self):
        pairs = [
            {"feeling": "nervous", "performance": 0.9},
            {"feeling": "nervous", "performance": 0.7},
            {"feeling": "calm", "performance": 0.6},
            {"feeling": "calm", "performance": 0.6},
        ]
        out = correlate_feeling_performance(pairs)
        self.assertEqual(out["buckets"][0], {"feeling": "nervous", "performance": 0.8, "n": 2})
        self.assertEqual(out["top_feeling"], "nervous")
        self.assertIn("nervous", out["headline"])
        self.assertEqual(out["n"], 4)

    def test_headline_gated_on_min_data(self):
        # Only 2 takes total → no headline (below _MIN_PAIRS_FOR_HEADLINE).
        pairs = [{"feeling": "nervous", "performance": 0.9},
                 {"feeling": "calm", "performance": 0.5}]
        out = correlate_feeling_performance(pairs)
        self.assertIsNone(out["headline"])
        self.assertIsNone(out["top_feeling"])
        self.assertEqual(len(out["buckets"]), 2)  # buckets still returned

    def test_single_feeling_no_headline(self):
        # All one feeling → nothing to be "best" against.
        pairs = [{"feeling": "calm", "performance": 0.8} for _ in range(4)]
        out = correlate_feeling_performance(pairs)
        self.assertIsNone(out["top_feeling"])

    def test_drops_invalid(self):
        pairs = [
            {"feeling": "happy", "performance": 0.9},   # not in enum
            {"feeling": "calm", "performance": "x"},    # bad perf
            {"feeling": "calm", "performance": None},
            {"feeling": "calm", "performance": 0.5},
        ]
        out = correlate_feeling_performance(pairs)
        self.assertEqual(out["n"], 1)
        self.assertEqual(out["buckets"][0]["feeling"], "calm")

    def test_bad_input(self):
        out = correlate_feeling_performance(None)
        self.assertEqual(out["buckets"], [])
        self.assertEqual(out["n"], 0)


class StressAsFuelTests(unittest.TestCase):
    def test_nervous_lift_rate(self):
        pairs = [
            {"feeling": "nervous", "performance": 0.9},  # >= avg → lifted
            {"feeling": "nervous", "performance": 0.8},  # >= avg → lifted
            {"feeling": "calm", "performance": 0.3},
            {"feeling": "calm", "performance": 0.4},
        ]
        out = stress_as_fuel(pairs)
        self.assertEqual(out["pct"], 100)  # both nervous takes above the mean
        self.assertEqual(out["n"], 2)
        self.assertIn("%", out["headline"])

    def test_none_when_too_few_nervous(self):
        pairs = [{"feeling": "calm", "performance": 0.5} for _ in range(4)]
        self.assertIsNone(stress_as_fuel(pairs))

    def test_none_when_too_little_data(self):
        self.assertIsNone(stress_as_fuel([{"feeling": "nervous", "performance": 0.9}]))


if __name__ == "__main__":
    unittest.main()
