"""Paid Audits — arc entitlement gate. Pure.

Run: python3 -m unittest tests.test_arc_entitlement
"""
from __future__ import annotations

import unittest

from services.arc_entitlement import is_arc_entitled


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


class IsEntitledTests(unittest.TestCase):
    def test_purchase_owned_by_user_is_entitled(self):
        db = _FakeDB({"arc_id": "a1", "user_id": "u1", "kind": "paid"})
        self.assertTrue(is_arc_entitled(db, "a1", "u1"))


if __name__ == "__main__":
    unittest.main()
