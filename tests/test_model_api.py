"""
STORY    As a model's founder and its teachers, I want every answer sold to
         be split the same way for every model, running costs first, then
         WillpowerLab's 20% of the margin, then the founder's 10% of the
         rest, then the teachers by their points, with nothing lost to
         rounding, so the price screen and the payouts always agree (N531,
         N577, N583).
OUTCOME
  O1  At any price the parts add up; at the lowest price, what an answer
      costs to run, "Infrastructure" takes it all.
  O2  A teacher's points are their counted answers, weighed by reliability,
      a hard clip worth 1.5; a month's teachers' part is divided by them to
      the unit, and with no founder left the founder's part goes to them.
  O3  The model is "sure" only when it is confident and answers with a
      choice its recipe offers.
PROVES   O1 -> ModelMoneyTest::test_the_split_adds_up_and_the_floor_is_all_infrastructure
         O2 -> ModelMoneyTest::test_points_and_a_month_divided_by_them
         O3 -> ModelMoneyTest::test_sure_needs_confidence_and_an_offered_choice
WHY      services/model_api.py holds the money's rules once, for the price
         screen, every API call and every payout.
"""
from __future__ import annotations

import unittest

from services import model_api as rules


class ModelMoneyTest(unittest.TestCase):
    def test_the_split_adds_up_and_the_floor_is_all_infrastructure(self):
        for price in range(60, 5000, 37):
            s = rules.split(price, 60, uses=7)
            self.assertEqual(s["infra"] + s["founder"] + s["teachers"], s["total"], price)
        floor = rules.split(60, 60, uses=10_000)
        self.assertEqual((floor["infra"], floor["founder"], floor["teachers"]), (600_000, 0, 0))
        self.assertEqual(rules.clamp_price(41, 60), 60)
        self.assertEqual(rules.clamp_price(315, 60), 310)

    def test_points_and_a_month_divided_by_them(self):
        pts = rules.points([
            {"teacher_id": "m", "counted": True, "sureness": 0.5},   # hard
            {"teacher_id": "m", "counted": True, "sureness": 0.9},
            {"teacher_id": "a", "counted": True, "sureness": 0.9},
            {"teacher_id": "a", "counted": False, "sureness": 0.5},
        ], {"m": 1.0, "a": 0.5})
        self.assertEqual(pts, {"m": {"points": 2.5, "answers": 2}, "a": {"points": 0.5, "answers": 1}})
        shares = [{"user_id": "m", "points": 2.5}, {"user_id": "a", "points": 0.5}]
        calls = [{"founder_units": 19, "teachers_units": 173}] * 3
        self.assertEqual(rules.month_payouts(calls, shares, "k"),
                         {("k", "founder"): 57, ("m", "teacher"): 432, ("a", "teacher"): 87})
        gone = rules.month_payouts(calls, shares, None)
        self.assertEqual(sum(gone.values()), 576)
        self.assertNotIn(("k", "founder"), gone)

    def test_sure_needs_confidence_and_an_offered_choice(self):
        rate = {"recipe": {"steps": ["rate"], "scale": ["Yes", "In-between", "No"]}}
        self.assertTrue(rules.read_answer(rate, {"answer": "yes", "confidence": 0.8})["sure"])
        self.assertFalse(rules.read_answer(rate, {"answer": "Maybe", "confidence": 0.99})["sure"])
        self.assertFalse(rules.read_answer(rate, {"answer": "No", "confidence": 0.5})["sure"])
        self.assertFalse(rules.read_answer(rate, "not json")["sure"])


if __name__ == "__main__":
    unittest.main()
