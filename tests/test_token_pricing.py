"""willab — token pricing Phase 1: the balance, the monthly period, charging.

services/token_prices.py · services/token_account.py · routes/token_routes.py

WHAT THIS PINS DOWN:
  * THE TWO FENCES. (a) the meter fails OPEN — a zero balance, an unreadable
    account, and a database that throws all leave the user's action working,
    because this sits in front of the F1 record loop; (b) prices are FLAT, and
    no pricing module may import the cost ledger (a cost-derived price varies
    with how the user performed, which is AC-9 in billing clothes);
  * the three monthly-reset rules, each of which is a real bug if broken —
    JUMP not loop (four dormant months = ONE grant, not four), SET not add
    (adding is rollover, which the founder ruled out), CAS on period_start
    (concurrent resets must not double-grant);
  * calendar-month arithmetic, so a user who signs up on the 31st does not
    drift backwards through the year;
  * that the coach cap is a SECOND limit binding independently of the balance —
    a Max user with 1.4M tokens can still be out of reviews, and cannot buy
    past the cap;
  * idempotency: re-opening a paid arc never double-charges, while chat stays
    repeatable.

Run: python3 -m unittest tests.test_token_pricing
"""
from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


UTC = timezone.utc


class _Is:
    """Marker for an IS filter, so the double can tell `= NULL` (never true)
    from `IS NULL` (the only thing that matches an ungranted column)."""

    def __init__(self, val):
        self.val = val


class FakeTable:
    """Minimal supabase-py table double with working .eq()/.is_() CAS."""

    def __init__(self, store: dict, ledger: list):
        self.store = store
        self.ledger = ledger
        self._filters: list = []
        self._op = None
        self._payload = None

    # -- builder -------------------------------------------------------
    def select(self, *_a, **_k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def upsert(self, payload):
        self._op, self._payload = "upsert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def is_(self, col, val):
        """PostgREST's IS predicate. Present because `WHERE col = 0` does NOT
        match a NULL column and the production code has to use this to CAS on
        a never-granted bonus_balance — a double that only understands eq()
        would pass the exact bug that shipped (founder 2026-08-12)."""
        self._filters.append((col, _Is(val)))
        return self

    def lt(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    # -- terminal ------------------------------------------------------
    def execute(self):
        raise NotImplementedError


class AccountTable(FakeTable):
    def execute(self):
        row = self.store.get("row")
        if self._op == "select":
            return MagicMock(data=[dict(row)] if row else [])
        if self._op == "upsert":
            self.store["row"] = dict(self._payload)
            return MagicMock(data=[dict(self._payload)])
        if self._op == "update":
            if row is None:
                return MagicMock(data=[])
            # CAS: every eq() filter must match current state.
            for col, val in self._filters:
                if col == "user_id":
                    continue
                if isinstance(val, _Is):
                    want_null = str(val.val).lower() == "null"
                    if (row.get(col) is None) != want_null:
                        return MagicMock(data=[])   # lost the race
                    continue
                # `= NULL` is never true in SQL, and the double must say so
                # or it will green-light a CAS that matches nothing in prod.
                if row.get(col) is None or str(row.get(col)) != str(val):
                    return MagicMock(data=[])   # lost the race
            row.update(self._payload)
            self.store["row"] = row
            return MagicMock(data=[dict(row)])
        return MagicMock(data=[])


class LedgerTable(FakeTable):
    def execute(self):
        if self._op == "insert":
            p = self._payload
            key = (p.get("user_id"), p.get("action"), p.get("ref_id"))
            if p.get("ref_id") is not None and key in {
                (r.get("user_id"), r.get("action"), r.get("ref_id"))
                for r in self.ledger if r.get("ref_id") is not None
            }:
                raise RuntimeError("duplicate key value violates unique index")
            self.ledger.append(dict(p))
            return MagicMock(data=[dict(p)])
        if self._op == "select":
            f = dict(self._filters)
            rows = [r for r in self.ledger
                    if all(str(r.get(k)) == str(v) for k, v in f.items())]
            return MagicMock(data=rows)
        return MagicMock(data=[])


class RpcNotInstalled(RuntimeError):
    """What PostgREST returns for a function that is not in the schema cache.

    Shaped like the real thing (code + message) so _rpc_not_found is exercised
    on its actual matching logic rather than on a convenient stand-in."""

    code = "PGRST202"

    def __init__(self, name="token_charge"):
        super().__init__(
            f"Could not find the function public.{name} in the schema cache")


class _RpcCall:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return MagicMock(data=self._fn())


class FakeDB:
    """Supabase double.

    ``rpc_installed`` chooses which half of services/token_account.charge runs:

      * True  — token_charge() exists, so charging goes through the ATOMIC
        path. This is the default because it is what production runs once
        migrations/add_token_charge_rpc.sql is applied, and every behavioural
        test in this file should be pinning THAT.
      * False — the function is missing and PostgREST says PGRST202, so the
        legacy four-round-trip path runs. Still covered, because a database
        where the migration has not been run yet must keep charging.

    The contract is that the two are indistinguishable to a caller, which is
    why the same test bodies are run against both (ChargeAtomicityTests).
    """

    def __init__(self, row=None, rpc_installed=True):
        self.store = {"row": dict(row) if row else None}
        self.ledger: list = []
        self.rpc_installed = rpc_installed
        # Set by a test to make the ledger INSERT inside the function blow up,
        # which is how the atomicity guarantee gets proven rather than asserted.
        self.ledger_insert_fails = False
        self.rpc_calls: list = []
        # Every account write the FUNCTION made, so a test can assert on the
        # column list the same way it can spy on .table().update() for the
        # legacy path.
        self.account_writes: list = []
        self.client = MagicMock()
        self.client.table.side_effect = self._table
        self.client.rpc.side_effect = self._rpc

    def _table(self, name):
        if name == "token_ledger":
            return LedgerTable(self.store, self.ledger)
        return AccountTable(self.store, self.ledger)

    # ── the Postgres function, in Python ──────────────────────────────
    def _rpc(self, name, params):
        if not self.rpc_installed:
            raise RpcNotInstalled(name)
        if name != "token_charge":
            raise RuntimeError(f"unexpected rpc {name}")
        self.rpc_calls.append(dict(params))
        return _RpcCall(lambda: self._token_charge(params))

    def _token_charge(self, p):
        """Mirrors migrations/add_token_charge_rpc.sql.

        The ONE property this double exists to reproduce is atomicity: every
        write is staged and applied only after the ledger insert has succeeded,
        so a failing insert leaves the balance untouched — exactly what the
        function's single transaction gives you and what the legacy path
        cannot.
        """
        row = self.store.get("row")
        price = max(0, int(p.get("p_price") or 0))
        if not (p.get("p_user_id") or "").strip() or p.get("p_action") is None:
            return {"ok": True, "charged": 0, "balance": 0, "reason": "no_user"}
        if row is None:
            return {"ok": True, "charged": 0, "balance": 0,
                    "reason": "account_unavailable"}

        monthly = max(0, int(row.get("token_balance") or 0))
        bonus = max(0, int(row.get("bonus_balance") or 0))
        reviews = max(0, int(row.get("coach_reviews_used") or 0))
        balance = monthly + bonus
        ref_id = p.get("p_ref_id")

        # Probe and debit are inside the same lock — no window between them.
        if ref_id is not None and any(
            r.get("user_id") == p["p_user_id"] and r.get("action") == p["p_action"]
            and r.get("ref_id") == ref_id for r in self.ledger
        ):
            return {"ok": True, "charged": 0, "balance": balance,
                    "reason": "already_charged"}

        if p.get("p_coach_action") and reviews >= int(p.get("p_coach_allowed") or 0):
            return {"ok": False, "charged": 0, "balance": balance,
                    "reason": "coach_cap_reached"}

        if price and balance < price:
            return {"ok": False, "charged": 0, "balance": balance,
                    "reason": "insufficient"}

        from_monthly = min(price, monthly)
        from_bonus = price - from_monthly
        new_balance = balance - price

        staged = {"token_balance": monthly - from_monthly}
        if from_bonus:
            staged["bonus_balance"] = bonus - from_bonus
        if p.get("p_coach_action"):
            staged["coach_reviews_used"] = reviews + 1

        entry = {
            "user_id": p["p_user_id"], "delta": -price,
            "balance_after": new_balance, "action": p["p_action"],
            "ref_id": ref_id, "price_version": p.get("p_price_version"),
            "tier": p.get("p_tier"),
        }
        if self.ledger_insert_fails:
            # The transaction aborts: the staged UPDATE never lands.
            raise RuntimeError("ledger insert exploded")

        self.ledger.append(entry)
        self.account_writes.append(dict(staged))
        row.update(staged)
        self.store["row"] = row
        return {"ok": True, "charged": price, "balance": new_balance,
                "reason": ""}

    def grants(self):
        return [r for r in self.ledger if r["action"] == "period_grant"]


def account_row(tier="free", balance=12000, start=None, reviews=0, bonus=None):
    row = {
        "user_id": "u1", "tier": tier, "token_balance": balance,
        "period_start": (start or datetime.now(UTC)).isoformat(),
        "coach_reviews_used": reviews,
    }
    # Omitted unless asked for, so every pre-existing test exercises the
    # pre-migration shape (no bonus_balance column at all).
    if bonus is not None:
        row["bonus_balance"] = bonus
    return row


class PriceTableTests(unittest.TestCase):


    def test_pricing_never_imports_the_cost_ledger(self):
        """FENCE §6.2. A price derived from measured cost varies with the
        user's own output — an AC-9 score wearing a billing costume.

        Checks IMPORT LINES, not prose: both modules discuss the cost ledger at
        length in their docstrings precisely to explain why they never read it,
        and a naive substring search would fail on the explanation itself."""
        import re
        pattern = re.compile(
            r"^\s*(?:from|import)\s+.*\b(?:llm_usage|llm_pricing)\b", re.M)
        for mod in ("services/token_prices.py", "services/token_account.py",
                    "routes/token_routes.py"):
            hits = pattern.findall(open(mod).read())
            self.assertEqual(hits, [],
                             f"{mod} imports the cost ledger: {hits}")


@patch("services.token_account.PERIOD_RESET_ENABLED", True)  # the roll is off since 2026-10-05 (contract §8, N44); these describe it
class PeriodResetTests(unittest.TestCase):
    def setUp(self):
        import services.token_account as ta
        self.ta = ta
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()


    def test_concurrent_reset_grants_once(self):
        start = datetime.now(UTC) - timedelta(days=40)
        db = FakeDB(account_row("starter", balance=10, start=start))
        a = self.ta.ensure_period_current("u1", database=db)
        b = self.ta.ensure_period_current("u1", database=db)
        self.assertEqual(len(db.grants()), 1, "CAS failed — double grant")
        self.assertEqual(a["token_balance"], b["token_balance"])


class BalanceReadTests(unittest.TestCase):
    """GET /v2/tokens/balance is on every page open (the header's chip), so
    its cost is the loop's cost: one round trip to the account row, and an
    answer even on a database that has not had the newer columns added."""

    def setUp(self):
        import services.token_account as ta
        self.ta = ta
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()
        self.wide = patch.object(ta, "_wide_read_ok", True)
        self.wide.start()

    def tearDown(self):
        self.wide.stop()
        self.env.stop()

    def test_balance_is_one_database_call(self):
        row = account_row(balance=12_000, bonus=500)
        row["coach_review_credits"] = 2
        db = FakeDB(row)
        acct = self.ta.get_account("u1", database=db)
        self.assertEqual(db.client.table.call_count, 1,
                         "the balance read went back to the row more than once")
        self.assertEqual(acct["balance"], 12_500)
        self.assertEqual(acct["bonus_balance"], 500)
        self.assertEqual(acct["coach_reviews"]["allowed"], 2)

    def test_balance_still_answers_without_the_newer_columns(self):
        class OldAccountTable(AccountTable):
            def select(self, cols="", **_k):
                if "bonus_balance" in cols:
                    raise Exception(
                        "column v2_student_details.bonus_balance does not exist")
                return super().select(cols)

        class OldDB(FakeDB):
            def _table(self, name):
                if name == "token_ledger":
                    return LedgerTable(self.store, self.ledger)
                return OldAccountTable(self.store, self.ledger)

        db = OldDB(account_row(balance=12_000))
        acct = self.ta.get_account("u1", database=db)
        self.assertIsNotNone(acct, "an unmigrated database must not hide the balance")
        self.assertEqual(acct["balance"], 12_000)
        self.assertEqual(acct["bonus_balance"], 0)
        # Remembered: the next read does not try the wide columns again.
        self.assertFalse(self.ta._wide_read_ok)


class ChargeTests(unittest.TestCase):
    def setUp(self):
        import services.token_account as ta
        self.ta = ta
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_charge_deducts_the_flat_price(self):
        db = FakeDB(account_row(balance=12_000))
        r = self.ta.charge("u1", "take_short", ref_id="rec1", database=db)
        self.assertTrue(r.ok)
        self.assertEqual(r.charged, 1_000)
        self.assertEqual(r.balance, 11_000)


    def test_a_coach_review_is_paid_in_tokens(self):
        """Founder 2026-10-14: plans differ by tokens only, so a coach review
        costs tokens like any action instead of a plan's review slot."""
        db = FakeDB(account_row("intensive", balance=400_000, reviews=8))
        r = self.ta.charge("u1", "coach_feedback", ref_id="s9", database=db)
        self.assertTrue(r.ok)
        self.assertEqual(r.charged, 35_000)
        self.assertEqual(r.balance, 365_000)


class FailOpenTests(unittest.TestCase):
    """THE fence. This sits in front of the F1 record loop."""

    def setUp(self):
        import services.token_account as ta
        self.ta = ta
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_unreadable_account_lets_the_action_through(self):
        db = FakeDB(account_row())
        db.client.table.side_effect = RuntimeError("database is on fire")
        r = self.ta.charge("u1", "take_short", ref_id="r1", database=db)
        self.assertTrue(r.ok, "a database outage must not block a recording")
        self.assertEqual(r.reason, "account_unavailable")

    def test_zero_balance_still_returns_a_usable_result(self):
        db = FakeDB(account_row(balance=0))
        r = self.ta.charge("u1", "take_short", ref_id="r1", database=db)
        self.assertFalse(r.ok)
        self.assertEqual(r.balance, 0)   # reported, not raised

    def test_charge_never_raises_on_junk_input(self):
        db = FakeDB(account_row())
        self.ta.charge("", "take_short", database=db)
        self.ta.charge("u1", "", database=db)
        self.ta.charge("u1", None, database=db)


class AdminGrantTests(unittest.TestCase):
    """The operator top-up (founder 2026-08-12).

    Same bucket rule as the legacy conversion, and for the same reason: the
    monthly roll SETS token_balance, so a grant put there has a silent 30-day
    expiry. An operator watching it land would have no way to know."""

    def setUp(self):
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()


    def test_the_same_ref_id_never_grants_twice(self):
        """A double-tapped button, a retried fetch, a refreshed tab. The
        ledger's unique index would absorb the duplicate ROW, but the balance
        write is a separate statement and the index cannot protect it — so
        without this check the account would be credited twice and the audit
        trail would show one movement."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=0, bonus=0))
        ta.admin_grant("u1", 500_000, ref_id="same", database=db)
        ta.admin_grant("u1", 500_000, ref_id="same", database=db)
        self.assertEqual(db.store["row"]["bonus_balance"], 500_000)


class ChargeAtomicityTests(unittest.TestCase):
    """The transaction boundary — services/token_account.charge routed through
    migrations/add_token_charge_rpc.sql.

    Founder directive 2026-08-03: eliminate the half-states so a crash cannot
    permanently corrupt user data. These tests do not assert that a transaction
    is "used"; they reproduce each half-state ON THE LEGACY PATH, show it
    corrupting the balance, and then show the atomic path refusing to produce
    it. A guarantee nobody has watched fail is a comment, not a test.
    """

    def setUp(self):
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()
        import services.token_account as ta
        # The negative cache is module state; a test that trips it would
        # otherwise silently push every later test onto the legacy path.
        ta._rpc_missing_until = 0.0

    def tearDown(self):
        self.env.stop()
        import services.token_account as ta
        ta._rpc_missing_until = 0.0


    def test_atomic_charge_is_idempotent_per_ref_under_the_lock(self):
        """The probe and the debit are the same transaction behind a row lock,
        so the second charge for a ref cannot find a window to debit in."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000))
        first = ta.charge("u1", "take_short", ref_id="rec1", database=db)
        after = db.store["row"]["token_balance"]

        second = ta.charge("u1", "take_short", ref_id="rec1", database=db)
        self.assertTrue(second.ok)
        self.assertEqual(second.charged, 0)
        self.assertEqual(second.reason, "already_charged")
        self.assertEqual(db.store["row"]["token_balance"], after)
        self.assertEqual(len(db.ledger), 1)
        self.assertGreater(first.charged, 0)


if __name__ == "__main__":
    unittest.main()
