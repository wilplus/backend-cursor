"""ML-13: the learned exercise order behind its constant (founder E8).

Pins: with the constant False the order is today's, exactly, whatever the
jar says; the reorder touches only ties at one fit, trusted rates first and
highest first, the rest in their order; the gate reads the jar's fair test
and its bar; the safety gate (the eligible pool) never changes.
"""
from __future__ import annotations

import unittest
from unittest import mock

from services import exercise_learned_order as lo


def _ranked():
    return [(0, -2, "a", {"exercise_id": "a"}), (0, -1, "b", {"exercise_id": "b"}),
            (0, 0, "c", {"exercise_id": "c"}), (1, -5, "d", {"exercise_id": "d"}),
            (1, 0, "e", {"exercise_id": "e"})]


class _Closed:
    EXERCISE_LEARNED_ORDER_ENABLED = False


class _Open:
    EXERCISE_LEARNED_ORDER_ENABLED = True


class LearnedOrderTests(unittest.TestCase):
    def setUp(self):
        lo.clear_cache()

    def test_closed_in_code_means_todays_order_whatever_the_jar_says(self):
        with mock.patch.object(lo, "learned_rates", return_value=({"c": 0.9}, "learned")) as read:
            self.assertEqual(lo.apply(_ranked(), object(), config=_Closed()), _ranked())
        read.assert_not_called()

    def test_reorder_touches_only_ties_at_one_fit(self):
        out = lo.reorder(_ranked(), {"c": 0.9, "a": 0.5, "e": 1.0})
        self.assertEqual([t[2] for t in out], ["c", "a", "b", "e", "d"])
        self.assertEqual([t[3] for t in out][0]["exercise_id"], "c")
        self.assertEqual(lo.reorder(_ranked(), None), _ranked())
        self.assertEqual(lo.reorder([], {"a": 1.0}), [])

    def test_the_gate_reads_the_jar_and_the_fair_tests_bar(self):
        sealed = {"sealed": True, "why_not": "12 of 300"}
        with mock.patch("services.exercise_evaluation.evaluate_jar", return_value=sealed):
            rates, why = lo.learned_rates(object())
        self.assertIsNone(rates)
        self.assertIn("jar sealed", why)
        below = {"sealed": False, "machine_only": {"fair_test": {"meets_bar": False, "why_not": ["success gain below 5%"]}}}
        with mock.patch("services.exercise_evaluation.evaluate_jar", return_value=below):
            rates, why = lo.learned_rates(object())
        self.assertIsNone(rates)
        self.assertIn("below its bar", why)
        above = {"sealed": False, "machine_only": {
            "fair_test": {"meets_bar": True, "why_not": []},
            "preferences": [{"exercise_id": "a", "helped_rate": 0.7, "counted": 40, "trusted": True},
                            {"exercise_id": "b", "helped_rate": 0.9, "counted": 3, "trusted": False}]}}
        with mock.patch("services.exercise_evaluation.evaluate_jar", return_value=above):
            rates, why = lo.learned_rates(object())
        self.assertEqual(rates, {"a": 0.7})

    def test_open_with_rates_reorders_and_the_pool_never_changes(self):
        with mock.patch.object(lo, "learned_rates", return_value=({"b": 0.8}, "learned")):
            out = lo.apply(_ranked(), object(), config=_Open())
        self.assertEqual([t[2] for t in out], ["b", "a", "c", "d", "e"])
        self.assertEqual({t[2] for t in out}, {t[2] for t in _ranked()})

    def test_the_matcher_returns_todays_order_with_the_constant_false(self):
        from services import confident_voice_practice as cvp
        key = lambda d, e, i: (None, None, None, None, None, d, e, i)  # noqa: E731
        with mock.patch.object(cvp, "match_for_clip", return_value=(None, [
                (key(0, -1, "a"), {"exercise_id": "a"}), (key(0, 0, "b"), {"exercise_id": "b"})])):
            out = cvp.rank_exercises_for_clip({"pattern": "x"}, object())
        self.assertEqual([t[2] for t in out], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
