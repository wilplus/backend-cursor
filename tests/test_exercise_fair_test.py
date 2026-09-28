"""The fair-test calculator (step 8 prep; §3.5 items 6, 7, 9).

Pins:
  * the speaker split is stable, disjoint and near the declared share;
  * the stored 80/20 odds are read as served (4/5 top, the rest share 1/5);
  * on a simulated world where the truth is known, inverse-propensity
    weighting recovers each policy's success rate, and a truly better ranker
    clears the bar while today's ranking against itself does not;
  * a missing attempt lowers the attempt rate and never counts as
    "didn't help";
  * the attempt-rate guardrail blocks a ranker people give up on;
  * only held-out speakers are graded; the result always needs the founder;
  * evaluate() is sealed until the evidence bar is met; no route serves it.
"""
from __future__ import annotations

import pathlib
import random
import unittest
from unittest.mock import patch

from services import exercise_fair_test as ft
from tests.test_exercise_learning_readiness import _Db


def _assignment(pool):
    n = len(pool)
    return {"candidates": [
        {"exercise_id": e, "rank": i,
         "probability_numerator": 1 if n == 1 else (4 if i == 1 else 1),
         "probability_denominator": 1 if n == 1 else (5 if i == 1 else 5 * (n - 1))}
        for i, e in enumerate(pool, start=1)]}


def _world(truth, *, attempt=None, speakers=3000, seed=7, pool=("A", "B")):
    """Units logged under 80/20 on `pool`; `truth[e]` is e's chance to help,
    `attempt[e]` its chance of a valid attempt (default 1)."""
    rng = random.Random(seed)
    units = []
    for s in range(speakers):
        served = pool[0] if rng.random() < 0.8 else pool[1]
        tried = rng.random() < (attempt or {}).get(served, 1.0)
        units.append({
            "speaker": f"s{s}", "served": served, "pool": list(pool),
            "odds": ft.logged_odds(_assignment(pool)), "trace": {},
            "attempted": tried,
            "helped": (rng.random() < truth[served]) if tried else None})
    return units


def always(exercise):
    return lambda unit: exercise


class SplitTests(unittest.TestCase):
    def test_stable_and_near_the_declared_share(self):
        self.assertEqual(ft.split_of("speaker-1"), ft.split_of("speaker-1"))
        held = sum(ft.split_of(f"s{i}") == "holdout" for i in range(10000))
        self.assertAlmostEqual(held / 10000, ft.HOLDOUT_SHARE, delta=0.02)


class OddsTests(unittest.TestCase):
    def test_the_stored_odds(self):
        self.assertEqual(ft.logged_odds(_assignment(["A", "B", "C"])),
                         {"A": 0.8, "B": 0.1, "C": 0.1})
        self.assertEqual(ft.logged_odds(_assignment(["A"])), {"A": 1.0})
        self.assertEqual(ft.fixed_ranking({"pool": ["A", "B"]}), "A")


class EstimateTests(unittest.TestCase):
    def setUp(self):
        # Fewer resampling rounds keep the unit tier fast; production uses 2000.
        patcher = patch.object(ft, "BOOTSTRAP_ROUNDS", 400)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_weighting_recovers_each_policy_s_true_rate(self):
        units = _world({"A": 0.30, "B": 0.60}, speakers=20000)
        self.assertAlmostEqual(ft.policy_rates(units, always("A"))["success_rate"],
                               0.30, delta=0.02)
        self.assertAlmostEqual(ft.policy_rates(units, always("B"))["success_rate"],
                               0.60, delta=0.04)

    def test_a_truly_better_ranker_clears_the_bar(self):
        out = ft.compare(_world({"A": 0.30, "B": 0.60}), always("B"))
        self.assertTrue(out["meets_bar"], out["why_not"])
        low, high = out["success_gain_interval_95"]
        self.assertGreater(low, 0)
        self.assertTrue(out["requires_founder_approval"])

    def test_today_s_ranking_against_itself_does_not(self):
        out = ft.compare(_world({"A": 0.30, "B": 0.60}), ft.fixed_ranking)
        self.assertEqual(out["success_gain"], 0)
        self.assertFalse(out["meets_bar"])

    def test_no_real_difference_does_not_clear_it(self):
        out = ft.compare(_world({"A": 0.40, "B": 0.40}), always("B"))
        self.assertFalse(out["meets_bar"])

    def test_a_missing_attempt_is_never_a_failure(self):
        units = _world({"A": 0.5, "B": 0.5}, attempt={"A": 0.5}, speakers=20000)
        rates = ft.policy_rates(units, always("A"))
        self.assertAlmostEqual(rates["success_rate"], 0.5, delta=0.02)
        self.assertAlmostEqual(rates["attempt_rate"], 0.5, delta=0.02)

    def test_the_guardrail_blocks_a_ranker_people_give_up_on(self):
        units = _world({"A": 0.30, "B": 0.60}, attempt={"B": 0.5})
        out = ft.compare(units, always("B"))
        self.assertFalse(out["meets_bar"])
        self.assertIn("attempt rate falls more than 5%", out["why_not"])

    def test_only_held_out_speakers_are_graded(self):
        units = _world({"A": 0.3, "B": 0.6}, speakers=1000)
        out = ft.compare(units, always("B"))
        held = [u for u in units if ft.split_of(u["speaker"]) == "holdout"]
        self.assertEqual(out["holdout"]["exposures"], len(held))
        self.assertLess(len(held), len(units))

    def test_the_interval_is_reproducible(self):
        units = _world({"A": 0.3, "B": 0.6}, speakers=800)
        self.assertEqual(ft.compare(units, always("B"))["success_gain_interval_95"],
                         ft.compare(units, always("B"))["success_gain_interval_95"])


class UnitTests(unittest.TestCase):
    def test_units_come_from_the_counter_s_cohort(self):
        record = {"in_cohort": True, "excluded": "no_attempt", "endpoint": None,
                  "exposure": {"owner_user_id": "u", "exercise_id": "A"},
                  "assignment": _assignment(["A", "B"]), "trace": {}}
        left_out = {**record, "in_cohort": False, "excluded": "repeat"}
        [unit] = ft.units_from([record, left_out])
        self.assertEqual((unit["attempted"], unit["helped"], unit["pool"]),
                         (False, None, ["A", "B"]))


class SealTests(unittest.TestCase):
    def test_sealed_until_the_bar_is_met(self):
        out = ft.evaluate(_Db(), always("room"))
        self.assertEqual(set(out), {"sealed", "why_not"})
        self.assertTrue(out["sealed"])

    def test_no_route_serves_it(self):
        root = pathlib.Path(__file__).resolve().parent.parent
        for path in (root / "routes").rglob("*.py"):
            self.assertNotIn("exercise_fair_test", path.read_text(), str(path))
