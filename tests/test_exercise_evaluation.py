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

import unittest
from unittest.mock import patch

from services import exercise_evaluation as ev
from services import exercise_fair_test as ft
from tests.test_exercise_learning_readiness import _Db


class SealTests(unittest.TestCase):

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
