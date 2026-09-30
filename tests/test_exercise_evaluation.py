"""The full jar unseals the evaluation (founder 2026-09-29, evening).

Pins:
  * below the bar the answer is sealed, with the counter's own reason, and
    nothing is computed;
  * once the bar is met the scoreboard adds the scorekeeper's labels up per
    exercise and per selection mode, in two piles that never mix: machine
    picks alone, and with the coach's picks;
  * the candidate prefers the exercise with the highest study-group helped
    rate within the unit's own pool, trusts a rate only above the
    per-exercise bar, and otherwise keeps today's fixed ranking;
  * the fair test grades machine draws only (a coach pick has no logged
    odds) and always requires the founder; nothing promotes;
  * the route is registered, password-gated, one service call.
"""
from __future__ import annotations

import pathlib
import unittest
from unittest.mock import patch

from services import exercise_evaluation as ev
from services import exercise_fair_test as ft
from services.exercise_learning_readiness import cohort_records
from tests.test_exercise_adequacy_labels import CALM, RUSHING, _with_endpoint
from tests.test_exercise_learning_readiness import RULES, _Db, _World

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _records(world):
    return cohort_records(
        signal_rules_version=RULES, exposures=world.exposures,
        assignments=world.assignments, traces=world.traces,
        practices=world.practices, attempts=world.attempts)


def _train(n):
    """A speaker id in the study group, the n-th one found."""
    found = 0
    for i in range(100000):
        if ft.split_of(f"s{i}") == "train":
            found += 1
            if found == n:
                return f"s{i}"
    raise AssertionError("no train speaker")


class ScoreboardTests(unittest.TestCase):
    def test_adds_labels_up_per_exercise_and_per_mode(self):
        labels = [
            {"exercise_id": "room", "selection_mode": "top", "helped": True},
            {"exercise_id": "room", "selection_mode": "top", "helped": False},
            {"exercise_id": "slow", "selection_mode": "coach_chosen", "helped": True},
        ]
        board = ev.scoreboard(labels)
        self.assertEqual((board["counted"], board["helped"], board["helped_rate"]),
                         (3, 2, 0.6667))
        self.assertEqual(board["exercises"], [
            {"exercise_id": "room", "counted": 2, "helped": 1, "helped_rate": 0.5},
            {"exercise_id": "slow", "counted": 1, "helped": 1, "helped_rate": 1.0}])
        self.assertEqual(board["by_selection_mode"]["coach_chosen"],
                         {"counted": 1, "helped": 1, "helped_rate": 1.0})
        self.assertEqual(ev.scoreboard([])["helped_rate"], None)


class CandidateTests(unittest.TestCase):
    def test_prefers_the_higher_study_group_rate_within_the_pool(self):
        choose = ev.success_ranked({"room": (3, 30), "slow": (20, 30)})
        self.assertEqual(choose({"pool": ["room", "slow"]}), "slow")
        # Only the unit's own pool is ever ranked.
        self.assertEqual(choose({"pool": ["room"]}), "room")

    def test_trusts_a_rate_only_above_the_bar_else_today_s_ranking(self):
        choose = ev.success_ranked({"room": (3, 30), "slow": (5, 5)})
        self.assertEqual(choose({"pool": ["room", "slow"]}), "room")
        self.assertEqual(ev.success_ranked({})({"pool": ["slow", "room"]}), "slow")
        self.assertIsNone(ev.success_ranked({})({"pool": []}))

    def test_learns_from_study_group_speakers_only(self):
        holdout = next(f"s{i}" for i in range(100000)
                       if ft.split_of(f"s{i}") == "holdout")
        labels = [{"exercise_id": "room", "owner_user_id": holdout, "helped": True},
                  {"exercise_id": "room", "owner_user_id": _train(1), "helped": False}]
        self.assertEqual(ev.train_rates(labels), {"room": (0, 1)})


class PilesTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(ft, "BOOTSTRAP_ROUNDS", 50)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _world(self):
        world = _World()
        _with_endpoint(world.add(owner=_train(1), exercise="room"), CALM)
        _with_endpoint(world.add(owner=_train(2), exercise="room"), RUSHING)
        _with_endpoint(world.add(owner=_train(3), exercise="slow",
                                 mode="coach_chosen"), CALM)
        return world

    def test_two_piles_that_never_mix(self):
        out = ev.build_evaluation(_records(self._world()))
        machine = out["machine_only"]["scoreboard"]
        both = out["with_coach_picks"]["scoreboard"]
        self.assertEqual((machine["counted"], machine["helped"]), (2, 1))
        self.assertEqual((both["counted"], both["helped"]), (3, 2))
        self.assertNotIn("coach_chosen", machine["by_selection_mode"])
        self.assertEqual(both["by_selection_mode"]["coach_chosen"]["counted"], 1)
        self.assertEqual(out["coach_pick_labels"], 1)

    def test_the_fair_test_grades_machine_draws_only_and_needs_the_founder(self):
        out = ev.build_evaluation(_records(self._world()))
        for pile in ev.PILES:
            test = out[pile]["fair_test"]
            self.assertTrue(test["requires_founder_approval"])
            self.assertEqual(test["fair_test_version"], ft.FAIR_TEST_VERSION)
            self.assertEqual(out[pile]["candidate"]["version"], ev.CANDIDATE_VERSION)
        # The coach pick is a label in one pile, never a graded unit.
        self.assertEqual(len(ft.units_from(_records(self._world()))), 2)
        prefs = {p["exercise_id"]: p for p in out["with_coach_picks"]["candidate"]["preferences"]}
        self.assertIn("slow", prefs)
        self.assertFalse(prefs["slow"]["trusted"])
        self.assertNotIn("slow", {p["exercise_id"] for p in
                                  out["machine_only"]["candidate"]["preferences"]})


class SealTests(unittest.TestCase):
    def test_below_the_bar_it_is_sealed_with_the_counter_s_reason(self):
        out = ev.evaluate_jar(_Db())
        self.assertTrue(out["sealed"])
        self.assertIn("of 300", out["why_not"])
        self.assertFalse(out["promotes"])
        self.assertTrue(out["requires_founder_approval"])
        self.assertNotIn("machine_only", out)

    def test_a_ready_gate_unseals_and_an_unreadable_source_reseals(self):
        db = _Db()
        with patch.object(ft, "BOOTSTRAP_ROUNDS", 20):
            out = ev.evaluate_jar(db, gate={"ready": True})
        self.assertFalse(out["sealed"])
        self.assertIn("machine_only", out)
        self.assertIn("with_coach_picks", out)
        self.assertFalse(out["promotes"])
        broken = _Db(fail=("attempts",))
        out = ev.evaluate_jar(broken, gate={"ready": True})
        self.assertTrue(out["sealed"])
        self.assertIn("unreadable: attempts", out["why_not"])


class RouteTests(unittest.TestCase):
    def test_the_route_is_registered_password_gated_and_thin(self):
        source = (ROOT / "routes" / "journal.py").read_text()
        block = source[source.index("def journal_admin_exercise_learning_evaluation"):]
        block = block[:block.index("\n@journal_bp.route")]
        self.assertIn("_journal_admin_ok()", block)
        self.assertIn("evaluate_jar(db)", block)
        self.assertEqual(block.count("db."), 0)
        self.assertIn('"/v2/internal/journal/exercise-learning-evaluation"', source)

    def test_nothing_serves_a_learned_ranking(self):
        # The candidate lives in the evaluation only: no serving path imports it.
        for path in ("services/confident_voice_practice.py",
                     "services/exercise_exposure.py", "routes/v2/coach.py"):
            self.assertNotIn("exercise_evaluation", (ROOT / path).read_text())
