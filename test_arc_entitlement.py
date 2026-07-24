"""Paid Audits — arc entitlement gate. Pure.

Run: python3 -m unittest test_arc_entitlement
"""
from __future__ import annotations

import unittest

from services.arc_entitlement import audit_price, is_arc_entitled


class _FakeDB:
    def __init__(self, purchase=None, raise_on_read=False):
        self._purchase = purchase
        self._raise = raise_on_read

    def get_arc_purchase(self, arc_id):
        # db.get_arc_purchase NEVER raises in prod (returns None on hiccup); the
        # gate relies on that. Model the contract: return None, never throw.
        if self._raise:
            return None
        return self._purchase


class _Cfg:
    AUDIT_PRICE_AMOUNT_MINOR = 2500
    AUDIT_PRICE_CURRENCY = "usd"
    AUDIT_SLA_HOURS = 48
    ARC_UNLOCK_CREDITS = 25


class IsEntitledTests(unittest.TestCase):
    def test_purchase_owned_by_user_is_entitled(self):
        db = _FakeDB({"arc_id": "a1", "user_id": "u1", "kind": "paid"})
        self.assertTrue(is_arc_entitled(db, "a1", "u1"))

    def test_purchase_for_other_user_not_entitled(self):
        db = _FakeDB({"arc_id": "a1", "user_id": "someone_else"})
        self.assertFalse(is_arc_entitled(db, "a1", "u1"))

    def test_no_purchase_not_entitled(self):
        self.assertFalse(is_arc_entitled(_FakeDB(None), "a1", "u1"))

    def test_missing_args_not_entitled(self):
        db = _FakeDB({"arc_id": "a1", "user_id": "u1"})
        self.assertFalse(is_arc_entitled(db, None, "u1"))
        self.assertFalse(is_arc_entitled(db, "a1", None))

    def test_founding_pass_entitles(self):
        db = _FakeDB({"arc_id": "a1", "user_id": "u1", "kind": "founding_pass"})
        self.assertTrue(is_arc_entitled(db, "a1", "u1"))

    def test_legacy_stripe_direct_purchase_still_entitled(self):
        # Grandfathered $50 rows (source='stripe', no credits_charged) —
        # entitlement is row-existence, never the charge shape.
        db = _FakeDB({"arc_id": "a1", "user_id": "u1", "kind": "paid",
                      "source": "stripe", "amount_minor": 5000})
        self.assertTrue(is_arc_entitled(db, "a1", "u1"))

    def test_credits_purchase_entitled(self):
        db = _FakeDB({"arc_id": "a1", "user_id": "u1", "kind": "paid",
                      "source": "credits", "credits_charged": 25})
        self.assertTrue(is_arc_entitled(db, "a1", "u1"))


class PayloadTests(unittest.TestCase):
    def test_price_minor_units_and_lowercase_currency_and_credits(self):
        p = audit_price(_Cfg())
        self.assertEqual(p["amount_minor"], 2500)
        self.assertEqual(p["currency"], "usd")
        self.assertEqual(p["credits"], 25)


if __name__ == "__main__":
    unittest.main()
