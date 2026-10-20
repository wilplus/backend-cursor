"""
STORY    As a paying speaker, I want my purchased audit unlocked for me and
         nobody else, and kept locked on any database hiccup, so that payment
         is honoured and never leaks (payments on the critical path).
OUTCOME
  O1  The owner's purchase means entitled.
  O2  Another user's purchase of the same arc means not entitled.
  O3  No purchase, or a failed read (get_arc_purchase answers None on a
      hiccup), keeps the paywall up.
  O4  A missing arc id or user id is never entitled.
PROVES   O1 -> test_purchase_owned_by_user_is_entitled
         O2 -> test_another_users_purchase_is_not_entitled
         O3 -> test_no_purchase_or_a_failed_read_keeps_the_paywall_up
         O4 -> test_missing_ids_are_never_entitled
WHY      services/arc_entitlement.py: "a failure keeps the paywall up,
         never opens it".
"""
from __future__ import annotations

import unittest

from services.arc_entitlement import is_arc_entitled

_PURCHASE = {"arc_id": "a1", "user_id": "u1", "kind": "paid"}


class _FakeDB:
    """get_arc_purchase as production promises it: a row, or None when there
    is none or the read failed. It never raises."""

    def __init__(self, purchase=None):
        self._purchase = purchase

    def get_arc_purchase(self, arc_id):
        return self._purchase


class IsEntitledTests(unittest.TestCase):
    def test_purchase_owned_by_user_is_entitled(self):
        self.assertTrue(is_arc_entitled(_FakeDB(_PURCHASE), "a1", "u1"))

    def test_another_users_purchase_is_not_entitled(self):
        self.assertFalse(is_arc_entitled(_FakeDB(_PURCHASE), "a1", "u2"))

    def test_no_purchase_or_a_failed_read_keeps_the_paywall_up(self):
        self.assertFalse(is_arc_entitled(_FakeDB(None), "a1", "u1"))
        self.assertFalse(is_arc_entitled(_FakeDB([_PURCHASE]), "a1", "u1"))

    def test_missing_ids_are_never_entitled(self):
        db = _FakeDB(_PURCHASE)
        self.assertFalse(is_arc_entitled(db, "", "u1"))
        self.assertFalse(is_arc_entitled(db, "a1", None))
        self.assertFalse(is_arc_entitled(_FakeDB({"arc_id": "a1", "user_id": None}),
                                         "a1", None))


if __name__ == "__main__":
    unittest.main()
