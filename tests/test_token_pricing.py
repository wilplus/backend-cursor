"""
STORY    As a speaker, I want token charges to be flat and never to block my
         recording, so that pricing never gets in the way of my next Take.
         (Critical path: payments, on the record -> process loop.)
OUTCOME
  O1  An action is charged its flat list price, whoever I am and however my
      Take went; my reference goes with it so the charge is taken once.
  O2  The charge never stops the action: an unreadable account, a charge
      function that fails, or nonsense input all let it through, and nothing
      raises.
  O3  The price modules never read the cost ledger (a cost-derived price
      would vary with how I performed).
  O4  An operator top-up with the same reference credits once.
  O5  My balance is read in one database call (the recording band waited
      2.3 s on three).
PROVES   O1 -> test_an_action_is_charged_its_flat_price
         O2 -> test_an_unreadable_account_lets_the_action_through
            -> test_a_failing_charge_lets_the_action_through
            -> test_charge_never_raises_on_junk_input
         O3 -> test_pricing_never_imports_the_cost_ledger
         O4 -> test_the_same_top_up_never_credits_twice
         O5 -> test_the_balance_is_read_in_one_call
WHY      Fence section 6.1 (fail open on the F1 loop) and 6.2 (flat prices).

This file covers the Python caller only. What the database does with a
charge (taken once per reference; too few tokens refused with nothing taken)
is proven on the real token_charge() in tests/test_token_charge_postgres.py.
"""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import services.token_account as ta
from services.token_prices import price_of


class _Table:
    """Minimal supabase-py table double for the account and the ledger,
    with a compare-and-set update and IS NULL matching."""

    def __init__(self, db, name):
        self.db, self.name, self.filters = db, name, []
        self.op = self.payload = None

    def select(self, *_a, **_k):
        self.op = "select"
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, col, val):
        self.filters.append((col, val, "eq"))
        return self

    def is_(self, col, val):
        self.filters.append((col, val, "is"))
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        self.db.calls.append((self.name, self.op))
        if self.name == "token_ledger":
            if self.op == "insert":
                self.db.ledger.append(dict(self.payload))
                return MagicMock(data=[dict(self.payload)])
            want = {c: str(v) for c, v, _ in self.filters}
            return MagicMock(data=[r for r in self.db.ledger
                                   if all(str(r.get(c)) == v for c, v in want.items())])
        row = self.db.row
        if self.op == "select":
            return MagicMock(data=[dict(row)])
        if self.op == "update":
            for col, val, kind in self.filters:
                if col == "user_id":
                    continue
                if kind == "is":
                    if row.get(col) is not None:
                        return MagicMock(data=[])
                elif row.get(col) is None or str(row.get(col)) != str(val):
                    return MagicMock(data=[])
            row.update(self.payload)
            return MagicMock(data=[dict(row)])
        raise AssertionError(self.op)


class FakeDB:
    """The account row, the ledger, and a token_charge() that only records
    what it was asked and answers ``answer`` (or raises it)."""

    def __init__(self, tier="free", balance=12_000, bonus=None, answer=None):
        self.row = {"user_id": "u1", "tier": tier, "token_balance": balance,
                    "period_start": datetime.now(timezone.utc).isoformat(),
                    "coach_reviews_used": 0}
        if bonus is not None:
            self.row["bonus_balance"] = bonus
        self.ledger: list = []
        self.calls: list = []
        self.rpc_calls: list = []
        self.answer = answer if answer is not None else {
            "ok": True, "charged": 0, "balance": 0, "reason": ""}
        self.client = MagicMock()
        self.client.table.side_effect = lambda name: _Table(self, name)
        self.client.rpc.side_effect = self._rpc

    def _rpc(self, name, params):
        self.rpc_calls.append((name, dict(params)))
        if isinstance(self.answer, Exception):
            raise self.answer
        return MagicMock(execute=MagicMock(return_value=MagicMock(data=self.answer)))


class _Base(unittest.TestCase):
    def setUp(self):
        env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        env.start()
        self.addCleanup(env.stop)
        # Module state: a test that trips the "RPC missing" cache would push
        # every later test onto the legacy path.
        ta._rpc_missing_until = 0.0
        self.addCleanup(setattr, ta, "_rpc_missing_until", 0.0)


class FlatPriceTests(_Base):

    def test_an_action_is_charged_its_flat_price(self):
        for tier, action, ref in (("free", "take_short", "rec1"),
                                  ("intensive", "take_short", "rec2"),
                                  ("practice", "coach_feedback", "s9")):
            price = price_of(action)
            db = FakeDB(tier=tier, balance=500_000, answer={
                "ok": True, "charged": price, "balance": 500_000 - price,
                "reason": ""})
            r = ta.charge("u1", action, ref_id=ref, database=db)
            [(name, params)] = db.rpc_calls
            self.assertEqual(name, "token_charge")
            self.assertEqual((params["p_price"], params["p_ref_id"]), (price, ref))
            self.assertEqual((r.ok, r.charged, r.balance),
                             (True, price, 500_000 - price))
        self.assertEqual(price_of("take_short"), 1_000)
        self.assertEqual(price_of("coach_feedback"), 35_000)

    def test_pricing_never_imports_the_cost_ledger(self):
        """Checks import lines, not prose: the modules explain at length why
        they never read the cost ledger."""
        pattern = re.compile(
            r"^\s*(?:from|import)\s+.*\b(?:llm_usage|llm_pricing)\b", re.M)
        for mod in ("services/token_prices.py", "services/token_account.py",
                    "routes/token_routes.py"):
            with open(mod) as fh:
                self.assertEqual(pattern.findall(fh.read()), [], mod)


class FailOpenTests(_Base):
    """This sits in front of the F1 record loop."""

    def test_an_unreadable_account_lets_the_action_through(self):
        db = FakeDB()
        db.client.table.side_effect = RuntimeError("database is on fire")
        r = ta.charge("u1", "take_short", ref_id="r1", database=db)
        self.assertTrue(r.ok, "a database outage must not block a recording")
        self.assertEqual(r.reason, "account_unavailable")
        self.assertEqual(db.rpc_calls, [])

    def test_a_failing_charge_lets_the_action_through(self):
        db = FakeDB(answer=RuntimeError("could not serialize access"))
        r = ta.charge("u1", "take_short", ref_id="r1", database=db)
        self.assertEqual((r.ok, r.charged, r.reason), (True, 0, "write_failed"))
        # No second attempt through the old four-call path: a lost response
        # after a commit looks the same as a rollback from here.
        self.assertEqual(len(db.rpc_calls), 1)
        self.assertNotIn(("v2_student_details", "update"), db.calls)
        self.assertEqual(db.ledger, [])

    def test_charge_never_raises_on_junk_input(self):
        db = FakeDB()
        for user, action in (("", "take_short"), ("u1", ""), ("u1", None)):
            self.assertTrue(hasattr(ta.charge(user, action, database=db), "ok"))


class AccountTests(_Base):

    def test_the_same_top_up_never_credits_twice(self):
        """A double-tapped button or a retried fetch: the balance write is its
        own statement, so the ledger's unique index cannot protect it."""
        db = FakeDB(balance=0, bonus=0)
        ta.admin_grant("u1", 500_000, ref_id="same", database=db)
        ta.admin_grant("u1", 500_000, ref_id="same", database=db)
        self.assertEqual(db.row["bonus_balance"], 500_000)

    def test_the_balance_is_read_in_one_call(self):
        db = FakeDB(balance=1000, bonus=500)
        db.row["coach_review_credits"] = 2
        acct = ta.get_account("u1", database=db)
        self.assertEqual(db.client.table.call_count, 1)
        self.assertEqual(acct["balance"], 1500)
        self.assertEqual(acct["coach_reviews"]["allowed"],
                         ta.coach_reviews_for("free") + 2)


if __name__ == "__main__":
    unittest.main()
