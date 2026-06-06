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


# ── Phase 1 — directional control composite + extreme split ────────
from services.snippet_salience import (  # noqa: E402
    score_control_direction,
    select_extremes_by_control,
    _CONTROL_COMPONENTS,
)


def _ctrl(start_ms, *, f0_sd, pause_regularity, dynamic_db, voiced_ratio):
    return {
        "start_ms": start_ms,
        "metrics": {
            "f0_sd": f0_sd, "pause_regularity": pause_regularity,
            "dynamic_db": dynamic_db, "voiced_ratio": voiced_ratio,
        },
    }


# Controlled (pro-effective): high variability + regular pauses + wide
# dynamics + full voice. Shaky: the opposite on all four.
_CONTROLLED = _ctrl(0, f0_sd=40, pause_regularity=0.9, dynamic_db=18, voiced_ratio=0.9)
_SHAKY = _ctrl(1000, f0_sd=5, pause_regularity=0.1, dynamic_db=4, voiced_ratio=0.4)


def _filler_pool(n, base_ms=5000):
    """n middling candidates so the pool exceeds top_n and a real split
    happens."""
    return [
        _ctrl(base_ms + i * 1000, f0_sd=15 + i, pause_regularity=0.5,
              dynamic_db=9, voiced_ratio=0.6)
        for i in range(n)
    ]


class ControlCompositeTests(unittest.TestCase):
    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(
            sum(w for _, w in _CONTROL_COMPONENTS), 1.0, places=9,
        )

    def test_four_monotonic_components(self):
        keys = [k for k, _ in _CONTROL_COMPONENTS]
        self.assertEqual(
            set(keys), {"f0_sd", "pause_regularity", "dynamic_db", "voiced_ratio"},
        )
        # The non-monotonic features must NOT be in the directional axis.
        for excluded in ("speech_rate", "wpm", "f0_slope",
                         "f0_mid_end_delta", "f0_mean"):
            self.assertNotIn(excluded, keys)

    def test_controlled_outscores_shaky(self):
        pool = [_CONTROLLED, _SHAKY] + _filler_pool(8)
        scores = score_control_direction(pool)
        self.assertGreater(scores[0], scores[1])

    def test_within_recording_zscore_when_no_baseline(self):
        """No baseline → z-scored within the pool; a uniform column
        contributes nothing (no signal), never crashes."""
        flat_pool = [_ctrl(i * 1000, f0_sd=10, pause_regularity=0.5,
                           dynamic_db=10, voiced_ratio=0.6) for i in range(5)]
        scores = score_control_direction(flat_pool)
        self.assertTrue(all(abs(s) < 1e-9 for s in scores))

    def test_baseline_hook_accepted(self):
        """The ISB baseline hook ({feature:(mean,sd)}) is accepted and
        shifts scoring relative to the speaker, not the pool."""
        pool = [_CONTROLLED, _SHAKY] + _filler_pool(8)
        base = {"f0_sd": (10.0, 5.0), "pause_regularity": (0.5, 0.2),
                "dynamic_db": (8.0, 3.0), "voiced_ratio": (0.6, 0.15)}
        scores = score_control_direction(pool, baseline=base)
        self.assertEqual(len(scores), len(pool))
        self.assertGreater(scores[0], scores[1])


class ExtremeSplitTests(unittest.TestCase):
    def test_surfaces_both_extremes(self):
        pool = [_CONTROLLED, _SHAKY] + _filler_pool(10)  # 12 > 10
        sel = select_extremes_by_control(pool, top_n=10)
        ids = [s["start_ms"] for s in sel]
        self.assertEqual(len(sel), 10)
        self.assertIn(0, ids)      # clearest GOOD surfaced
        self.assertIn(1000, ids)   # clearest SHAKY surfaced

    def test_output_chronological(self):
        pool = [_CONTROLLED, _SHAKY] + _filler_pool(10)
        sel = select_extremes_by_control(pool, top_n=10)
        ids = [s["start_ms"] for s in sel]
        self.assertEqual(ids, sorted(ids))

    def test_pool_at_or_below_cap_returns_all(self):
        pool = [_CONTROLLED, _SHAKY] + _filler_pool(4)  # 6 <= 10
        sel = select_extremes_by_control(pool, top_n=10)
        self.assertEqual(len(sel), 6)

    def test_never_exceeds_cap(self):
        pool = [_CONTROLLED, _SHAKY] + _filler_pool(30)  # 32 > 10
        sel = select_extremes_by_control(pool, top_n=10)
        self.assertEqual(len(sel), 10)


class ControlFenceGuardTests(unittest.TestCase):
    """Control composite + direction are transient — never on outputs."""

    def test_no_control_or_direction_on_returned_dicts(self):
        pool = [_CONTROLLED, _SHAKY] + _filler_pool(10)
        sel = select_extremes_by_control(pool, top_n=10)
        for s in sel:
            self.assertEqual(set(s.keys()), {"start_ms", "metrics"})
            for banned in ("control", "control_score", "direction",
                           "likely_strong", "likely_shaky", "salience"):
                self.assertNotIn(banned, s)
                self.assertNotIn(banned, s["metrics"])


if __name__ == "__main__":
    unittest.main()
