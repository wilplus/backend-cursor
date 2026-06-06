"""Unit tests for services.snippet_salience (willab Lab Level 1).

Guards two things:
  1. The salience RANKING behaves (activated moments outrank flat ones;
     output is capped + chronological).
  2. The methodological FENCE / split-sink: the salience score is
     transient — it NEVER appears on a returned candidate dict, so it
     can't be persisted, serialized to a user (AC-9), or inherited by a
     future validation sampler.

Run: python3 -m unittest test_snippet_salience
"""
from __future__ import annotations

import unittest

from services.snippet_salience import (
    rank_candidates_by_salience,
    _SALIENCE_COMPONENTS,
    _SALIENCE_WEIGHT,
)


def _cand(start_ms, **feats):
    return {"start_ms": start_ms, "metrics": dict(feats)}


# A flat, low-activation window vs a hot, high-activation one vs a mid.
_FLAT = _cand(0, f0_sd=1.0, f0_slope=0.0, f0_mid_end_delta=0.0,
              pause_regularity=1.0, dynamic_db=1.0)
_HOT = _cand(1000, f0_sd=50.0, f0_slope=30.0, f0_mid_end_delta=20.0,
             pause_regularity=0.0, dynamic_db=20.0)
_MID = _cand(2000, f0_sd=25.0, f0_slope=15.0, f0_mid_end_delta=10.0,
             pause_regularity=0.5, dynamic_db=10.0)


class WeightsContractTests(unittest.TestCase):
    def test_provisional_equal_weights_sum_to_one(self):
        self.assertAlmostEqual(
            len(_SALIENCE_COMPONENTS) * _SALIENCE_WEIGHT, 1.0, places=9,
        )

    def test_five_components(self):
        self.assertEqual(len(_SALIENCE_COMPONENTS), 5)
        self.assertEqual(_SALIENCE_WEIGHT, 0.2)


class RankingTests(unittest.TestCase):
    def test_hot_selected_flat_dropped(self):
        sel = rank_candidates_by_salience([_FLAT, _HOT, _MID], top_n=2)
        ids = [s["start_ms"] for s in sel]
        self.assertIn(1000, ids)       # hot kept
        self.assertNotIn(0, ids)       # flat dropped

    def test_output_chronological(self):
        sel = rank_candidates_by_salience([_FLAT, _HOT, _MID], top_n=2)
        ids = [s["start_ms"] for s in sel]
        self.assertEqual(ids, sorted(ids))

    def test_top_n_cap_respected(self):
        sel = rank_candidates_by_salience([_FLAT, _HOT, _MID], top_n=2)
        self.assertEqual(len(sel), 2)

    def test_pool_at_or_below_cap_returns_all(self):
        sel = rank_candidates_by_salience([_FLAT, _HOT, _MID], top_n=10)
        self.assertEqual(len(sel), 3)
        self.assertEqual([s["start_ms"] for s in sel], [0, 1000, 2000])

    def test_empty_pool(self):
        self.assertEqual(rank_candidates_by_salience([], top_n=10), [])

    def test_pause_irregularity_is_salient(self):
        """Lower pause_regularity (more irregular) → more salient. Two
        otherwise-identical windows differing only in pause_regularity:
        the irregular one wins."""
        regular = _cand(0, f0_sd=10, f0_slope=5, f0_mid_end_delta=5,
                        pause_regularity=1.0, dynamic_db=10)
        irregular = _cand(1000, f0_sd=10, f0_slope=5, f0_mid_end_delta=5,
                          pause_regularity=0.0, dynamic_db=10)
        sel = rank_candidates_by_salience([regular, irregular], top_n=1)
        self.assertEqual(sel[0]["start_ms"], 1000)

    def test_missing_features_treated_as_neutral(self):
        """A window with all-None features must not crash and must rank
        below a window with real activation."""
        empty = _cand(0)  # no metrics keys
        sel = rank_candidates_by_salience([empty, _HOT], top_n=1)
        self.assertEqual(sel[0]["start_ms"], 1000)


class FenceGuardTests(unittest.TestCase):
    """The salience score is transient — it must never appear on a
    returned dict (so it can't be persisted / serialized / inherited)."""

    def test_no_salience_field_on_returned_dicts(self):
        sel = rank_candidates_by_salience([_FLAT, _HOT, _MID], top_n=2)
        for s in sel:
            self.assertEqual(set(s.keys()), {"start_ms", "metrics"})
            self.assertNotIn("salience", s)
            self.assertNotIn("salience_score", s)
            self.assertNotIn("salience", s["metrics"])

    def test_returned_dicts_are_the_same_objects(self):
        """The selector returns the SAME candidate dicts (filtered +
        reordered), not augmented copies — proves it adds nothing."""
        sel = rank_candidates_by_salience([_FLAT, _HOT, _MID], top_n=3)
        self.assertTrue(any(s is _HOT for s in sel))


if __name__ == "__main__":
    unittest.main()
