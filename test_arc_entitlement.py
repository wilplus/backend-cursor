"""Paid Audits — arc entitlement gate (BE chunk A2). Pure.

Run: python3 -m unittest test_arc_entitlement
"""
from __future__ import annotations

import unittest

from services.arc_entitlement import (
    audit_price, is_arc_entitled, next_take_requires_payment,
    payment_required_payload, take_requires_payment,
)


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
    AUDIT_PRICE_AMOUNT_MINOR = 15000
    AUDIT_PRICE_CURRENCY = "PLN"
    AUDIT_SLA_HOURS = 48


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


class TakeBoundaryTests(unittest.TestCase):
    def test_take_one_is_free(self):
        # LIVE-LOOP FENCE: take 1 never requires payment.
        self.assertFalse(take_requires_payment(1))

    def test_take_two_and_three_require_payment(self):
        self.assertTrue(take_requires_payment(2))
        self.assertTrue(take_requires_payment(3))

    def test_unknown_take_is_free(self):
        # None / non-numeric (standalone / pre-arc) is never gated by take.
        self.assertFalse(take_requires_payment(None))
        self.assertFalse(take_requires_payment("nope"))


class NextTakeGateTests(unittest.TestCase):
    """Phase-1 — the session-status gate: once the free first take is in the
    bank on an unpaid arc, the NEXT take is paid → can_start_analysis flips."""

    def test_zero_takes_next_is_free(self):
        # Fresh arc (or no arc yet): next take is take 1 → free.
        self.assertFalse(next_take_requires_payment(0))

    def test_one_take_next_requires_payment(self):
        # Free take 1 done → next take is take 2 → paid.
        self.assertTrue(next_take_requires_payment(1))
        self.assertTrue(next_take_requires_payment(2))

    def test_bad_count_is_free(self):
        self.assertFalse(next_take_requires_payment(None))
        self.assertFalse(next_take_requires_payment("nope"))


class PayloadTests(unittest.TestCase):
    def test_price_minor_units_and_lowercase_currency(self):
        p = audit_price(_Cfg())
        self.assertEqual(p["amount_minor"], 15000)
        self.assertEqual(p["currency"], "pln")

    def test_402_payload_shape(self):
        body = payment_required_payload("a1", _Cfg())
        self.assertEqual(body["code"], "PAYMENT_REQUIRED")
        self.assertEqual(body["arc_id"], "a1")
        self.assertEqual(body["price"]["amount_minor"], 15000)
        self.assertEqual(body["sla_hours"], 48)
        # Phase-1: a 402 only fires on an unpaid arc, so the body says so.
        self.assertFalse(body["audit_paid"])


if __name__ == "__main__":
    unittest.main()
