"""Frozen holdout (readiness rig #3). Pure.

Run: python3 -m unittest test_holdout
"""
from __future__ import annotations

import unittest

from services.holdout import is_holdout, HOLDOUT_FRACTION


class HoldoutTests(unittest.TestCase):
    def test_deterministic_stable(self):
        # Same id → same side, every call (a row never drifts across the split).
        for sid in ("abc", "snippet-123", "00000000-0000-0000-0000-000000000001"):
            self.assertEqual(is_holdout(sid), is_holdout(sid))

    def test_missing_id_never_held_out(self):
        self.assertFalse(is_holdout(None))
        self.assertFalse(is_holdout(""))

    def test_fraction_zero_and_one(self):
        ids = [f"s{i}" for i in range(500)]
        self.assertTrue(all(not is_holdout(s, 0.0) for s in ids))
        self.assertTrue(all(is_holdout(s, 1.0) for s in ids))

    def test_distribution_near_fraction(self):
        # Over many ids the held-out share is ~HOLDOUT_FRACTION.
        ids = [f"snippet-{i}" for i in range(8000)]
        held = sum(1 for s in ids if is_holdout(s))
        frac = held / len(ids)
        self.assertAlmostEqual(frac, HOLDOUT_FRACTION, delta=0.03)

    def test_custom_fraction_roughly_holds(self):
        ids = [f"x-{i}" for i in range(8000)]
        held = sum(1 for s in ids if is_holdout(s, 0.5)) / len(ids)
        self.assertAlmostEqual(held, 0.5, delta=0.03)

    def test_train_and_holdout_are_disjoint_and_cover(self):
        ids = [f"u{i}" for i in range(1000)]
        held = {s for s in ids if is_holdout(s)}
        train = {s for s in ids if not is_holdout(s)}
        self.assertEqual(held & train, set())
        self.assertEqual(held | train, set(ids))


if __name__ == "__main__":
    unittest.main()
