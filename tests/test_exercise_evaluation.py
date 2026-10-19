"""
STORY    As the founder, I want the exercise evaluation to stay sealed until
         enough data exists and never to promote anything on its own, so that
         no decision rests on too few practices.
OUTCOME
  O1  Below the bar the result is sealed with the counter's own reason, and
      no pile is computed.
  O2  Above the bar machine picks and coach picks are kept in separate piles
      (machine-only never holds a coach pick); an unreadable source reseals.
  O3  Nothing promotes on its own: promotes is false and the founder's
      approval is required, sealed or not.
PROVES   O1 -> test_below_the_bar_it_is_sealed_with_the_reason_and_nothing_computed
         O2 -> test_above_the_bar_the_piles_never_mix_and_an_unreadable_source_reseals
         O3 -> both tests (promotes / requires_founder_approval asserted in each)
NOTE     The fake database and world builders live in
         tests/test_exercise_learning_readiness.py, which tests the counter
         this evaluation is gated on.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import exercise_evaluation as ev
from services import exercise_fair_test as ft
from tests.test_exercise_learning_readiness import _coach_trace, _Db, _World


class EvaluationTests(unittest.TestCase):

    def _never_promotes(self, out):
        self.assertIs(out["promotes"], False)
        self.assertIs(out["requires_founder_approval"], True)

    def test_below_the_bar_it_is_sealed_with_the_reason_and_nothing_computed(self):
        out = ev.evaluate_jar(_Db())  # the counter's own gate: 1 of 300
        self.assertTrue(out["sealed"])
        self.assertEqual(out["why_not"],
                         "1 of 300 first-exposure attempts with a valid endpoint")
        for pile in ev.PILES:
            self.assertNotIn(pile, out)
        self._never_promotes(out)

    def test_above_the_bar_the_piles_never_mix_and_an_unreadable_source_reseals(self):
        db = _Db()
        db.world = (_World().add(owner="u1")
                    .add(owner="u2", exercise="coach-pick", mode="coach_chosen",
                         trace=_coach_trace()))
        with patch.object(ft, "BOOTSTRAP_ROUNDS", 20):
            out = ev.evaluate_jar(db, gate={"ready": True})
        self.assertFalse(out["sealed"])
        machine = out["machine_only"]["scoreboard"]
        both = out["with_coach_picks"]["scoreboard"]
        self.assertEqual(machine["counted"], 1)
        self.assertNotIn("coach_chosen", machine["by_selection_mode"])
        self.assertEqual(both["counted"], 2)
        self.assertEqual(both["by_selection_mode"]["coach_chosen"]["counted"], 1)
        self.assertEqual(out["coach_pick_labels"], 1)
        self._never_promotes(out)

        out = ev.evaluate_jar(_Db(fail=("attempts",)), gate={"ready": True})
        self.assertTrue(out["sealed"])
        self.assertEqual(out["why_not"], "unreadable: attempts")
        self._never_promotes(out)
