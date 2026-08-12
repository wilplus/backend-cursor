"""willab — token pricing Phase 1: the balance, the monthly period, charging.

services/token_prices.py · services/token_account.py ·
services/stripe_subscription_tiers.py · routes/token_routes.py

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

Run: python3 -m unittest test_token_pricing
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


class FakeTable:
    """Minimal supabase-py table double with working .eq() CAS semantics."""

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
                if str(row.get(col)) != str(val):
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
    def test_tier_grants_match_the_founder_approved_ladder(self):
        from services.token_prices import grant_for, coach_reviews_for
        self.assertEqual(grant_for("free"), 12_000)
        self.assertEqual(grant_for("starter"), 50_000)
        self.assertEqual(grant_for("pro"), 300_000)
        self.assertEqual(grant_for("max"), 1_500_000)
        # Founder 2026-08-01: Max moves 10 -> 30 reviews. This REVERSES the
        # earlier "30 would be 7.5 hours of the founder's month" note, with the
        # calendar cost known and accepted at that size. The cap still exists
        # and still binds independently of balance; only its Max value moved.
        self.assertEqual([coach_reviews_for(t)
                          for t in ("free", "starter", "pro", "max")],
                         [0, 1, 6, 30])

    def test_unknown_tier_degrades_to_free_never_raises(self):
        from services.token_prices import grant_for, normalize_tier
        self.assertEqual(normalize_tier("enterprise"), "free")
        self.assertEqual(normalize_tier(None), "free")
        self.assertEqual(grant_for("nonsense"), 12_000)

    def test_unknown_action_is_free_rather_than_an_exception(self):
        """Forgetting to price something should cost us revenue, not break the
        user's action on the live loop."""
        from services.token_prices import price_of
        self.assertEqual(price_of("something_new"), 0)
        self.assertEqual(price_of(None), 0)

    def test_duration_bands(self):
        from services.token_prices import band_for_seconds
        self.assertEqual(band_for_seconds(50), "take_short")
        self.assertEqual(band_for_seconds(200), "take_medium")
        self.assertEqual(band_for_seconds(700), "take_long")

    def test_over_length_audio_charges_the_top_band_never_rejected(self):
        from services.token_prices import band_for_seconds
        self.assertEqual(band_for_seconds(60 * 60), "take_long")

    def test_band_for_balance_picks_the_longest_affordable(self):
        from services.token_prices import band_for_balance
        self.assertEqual(band_for_balance(6000)["action"], "take_long")
        self.assertEqual(band_for_balance(3000)["action"], "take_medium")
        self.assertEqual(band_for_balance(1000)["action"], "take_short")
        self.assertIsNone(band_for_balance(999))

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


class PeriodArithmeticTests(unittest.TestCase):
    def test_month_end_signup_does_not_drift_backwards(self):
        from services.token_account import _add_months
        jan31 = datetime(2026, 1, 31, tzinfo=UTC)
        self.assertEqual(_add_months(jan31, 1).date().isoformat(), "2026-02-28")
        # And critically: it does not keep losing days each month.
        self.assertEqual(_add_months(jan31, 3).date().isoformat(), "2026-04-30")

    def test_months_elapsed_is_calendar_not_30_day(self):
        from services.token_account import months_elapsed
        start = datetime(2026, 1, 15, tzinfo=UTC)
        self.assertEqual(months_elapsed(start, datetime(2026, 2, 14, tzinfo=UTC)), 0)
        self.assertEqual(months_elapsed(start, datetime(2026, 2, 15, tzinfo=UTC)), 1)
        self.assertEqual(months_elapsed(start, datetime(2026, 5, 20, tzinfo=UTC)), 4)
        self.assertEqual(months_elapsed(start, datetime(2025, 1, 1, tzinfo=UTC)), 0)


class PeriodResetTests(unittest.TestCase):
    def setUp(self):
        import services.token_account as ta
        self.ta = ta
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_within_period_does_not_regrant(self):
        db = FakeDB(account_row(balance=4000))
        out = self.ta.ensure_period_current("u1", database=db)
        self.assertEqual(out["token_balance"], 4000)
        self.assertEqual(db.grants(), [])

    def test_dormant_four_months_grants_ONCE_and_jumps_the_anchor(self):
        """JUMP, never loop. Looping would hand a returning user four months
        of tokens at once."""
        start = datetime.now(UTC) - timedelta(days=130)
        db = FakeDB(account_row("pro", balance=17, start=start))
        out = self.ta.ensure_period_current("u1", database=db)
        self.assertEqual(out["token_balance"], 300_000)
        self.assertEqual(len(db.grants()), 1, "granted more than once")
        from services.token_account import _parse_ts, months_elapsed
        self.assertEqual(months_elapsed(_parse_ts(out["period_start"]),
                                        datetime.now(UTC)), 0)

    def test_reset_SETS_the_grant_it_does_not_add(self):
        """Adding is rollover, which the founder ruled out — on Max three quiet
        months would bank 4.5M tokens."""
        start = datetime.now(UTC) - timedelta(days=40)
        db = FakeDB(account_row("max", balance=1_400_000, start=start))
        out = self.ta.ensure_period_current("u1", database=db)
        self.assertEqual(out["token_balance"], 1_500_000)

    def test_unused_tokens_do_not_carry(self):
        start = datetime.now(UTC) - timedelta(days=40)
        db = FakeDB(account_row("starter", balance=49_000, start=start))
        out = self.ta.ensure_period_current("u1", database=db)
        self.assertEqual(out["token_balance"], 50_000)

    def test_coach_reviews_do_not_carry(self):
        """Non-rolling is the entire point of the cap — three quiet months
        must not bank 90 reviews into a single week."""
        start = datetime.now(UTC) - timedelta(days=95)
        db = FakeDB(account_row("max", balance=0, start=start, reviews=10))
        out = self.ta.ensure_period_current("u1", database=db)
        self.assertEqual(out["coach_reviews_used"], 0)
        self.assertEqual(len(db.grants()), 1)

    def test_concurrent_reset_grants_once(self):
        start = datetime.now(UTC) - timedelta(days=40)
        db = FakeDB(account_row("starter", balance=10, start=start))
        a = self.ta.ensure_period_current("u1", database=db)
        b = self.ta.ensure_period_current("u1", database=db)
        self.assertEqual(len(db.grants()), 1, "CAS failed — double grant")
        self.assertEqual(a["token_balance"], b["token_balance"])

    def test_missing_row_is_seeded_onto_the_free_period(self):
        db = FakeDB(None)
        out = self.ta.ensure_period_current("u1", database=db)
        self.assertEqual(out["tier"], "free")
        self.assertEqual(out["token_balance"], 12_000)


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

    def test_reopening_a_paid_arc_does_not_double_charge(self):
        db = FakeDB(account_row(balance=12_000))
        a = self.ta.charge("u1", "game", ref_id="arc1", database=db)
        b = self.ta.charge("u1", "game", ref_id="arc1", database=db)
        self.assertEqual(a.charged, 1_500)
        self.assertEqual(b.charged, 0)
        self.assertTrue(b.ok)
        self.assertEqual(b.reason, "already_charged")

    def test_chat_is_repeatable(self):
        db = FakeDB(account_row(balance=12_000))
        for _ in range(3):
            self.assertTrue(self.ta.charge("u1", "chat", database=db).ok)
        self.assertEqual(self.ta.get_account("u1", database=db)["balance"],
                         12_000 - 450)

    def test_insufficient_balance_reports_but_never_raises(self):
        # A tier that HAS reviews, so the balance is what actually bites.
        db = FakeDB(account_row("pro", balance=100))
        r = self.ta.charge("u1", "coach_review", ref_id="arc1", database=db)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "insufficient")
        self.assertEqual(r.balance, 100)

    def test_free_tier_cannot_buy_a_coach_review_at_any_balance(self):
        """The cap is checked BEFORE the balance, and that ordering is the
        useful one: a free user needs to UPGRADE, not top up, so the reason
        the FE receives has to say cap — not 'insufficient'."""
        db = FakeDB(account_row("free", balance=10_000_000))
        r = self.ta.charge("u1", "coach_review", ref_id="arc1", database=db)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "coach_cap_reached")

    def test_coach_cap_binds_independently_of_a_large_balance(self):
        """A Max user holding 1.4M tokens can still be out of reviews. That is
        the design: the cap protects the founder's calendar, not the margin."""
        db = FakeDB(account_row("max", balance=1_400_000, reviews=30))
        r = self.ta.charge("u1", "coach_review", ref_id="arc9", database=db)
        self.assertFalse(r.ok)
        self.assertEqual(r.reason, "coach_cap_reached")
        self.assertEqual(r.balance, 1_400_000, "balance must be untouched")

    def test_coach_review_consumes_the_allowance(self):
        db = FakeDB(account_row("pro", balance=300_000, reviews=0))
        self.assertTrue(self.ta.charge("u1", "coach_review", ref_id="a1",
                                       database=db).ok)
        acct = self.ta.get_account("u1", database=db)
        self.assertEqual(acct["coach_reviews"]["used"], 1)
        self.assertEqual(acct["coach_reviews"]["remaining"], 5)

    def test_flag_off_charges_nothing(self):
        db = FakeDB(account_row(balance=12_000))
        with patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "0"}):
            r = self.ta.charge("u1", "take_long", ref_id="r", database=db)
        self.assertTrue(r.ok)
        self.assertEqual(r.charged, 0)
        self.assertEqual(db.ledger, [])


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


class StripeTierTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def _event(self, etype, price="price_pro", user="u1", status="active"):
        return {"type": etype, "data": {"object": {
            "id": "sub_1", "status": status, "metadata": {"user_id": user},
            "current_period_start": int(datetime(2026, 7, 3, tzinfo=UTC).timestamp()),
            "items": {"data": [{"price": {"id": price}}]}}}}

    MAP = '{"price_starter":"starter","price_pro":"pro","price_max":"max"}'

    def test_subscription_created_sets_tier_and_grants(self):
        from services.stripe_subscription_tiers import apply_subscription_event
        db = FakeDB(account_row())
        out = apply_subscription_event(
            self._event("customer.subscription.created"), self.MAP, database=db)
        self.assertTrue(out["handled"])
        self.assertEqual(out["tier"], "pro")
        self.assertEqual(db.store["row"]["token_balance"], 300_000)

    def test_period_anchors_to_the_stripe_billing_date(self):
        """Otherwise the card is charged on the 3rd and tokens re-grant on the
        17th, and every support question becomes 'when do mine come back?'."""
        from services.stripe_subscription_tiers import apply_subscription_event
        db = FakeDB(account_row())
        apply_subscription_event(self._event("customer.subscription.created"),
                                 self.MAP, database=db)
        self.assertTrue(db.store["row"]["period_start"].startswith("2026-07-03"))

    def test_cancellation_drops_to_free_without_clawback_of_the_paid_period(self):
        """The balance assertion is the whole test. It was missing, and under it
        the code was setting a cancelling Pro user's 250,000 tokens to 12,000 on
        the spot — the exact opposite of the 'no claw-back' comment above it."""
        from services.stripe_subscription_tiers import apply_subscription_event
        db = FakeDB(account_row("pro", balance=250_000))
        out = apply_subscription_event(
            self._event("customer.subscription.deleted"), self.MAP, database=db)
        self.assertEqual(out["tier"], "free")
        self.assertEqual(db.store["row"]["token_balance"], 250_000,
                         "clawed back tokens the user had already paid for")

    def test_cancellation_does_not_move_the_renewal_date(self):
        """Re-anchoring on cancellation would shift their next roll to the day
        they cancelled, so the date the FE shows them stops being the date they
        were told."""
        from services.stripe_subscription_tiers import apply_subscription_event
        anchor = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        db = FakeDB(account_row("pro", balance=250_000))
        db.store["row"]["period_start"] = anchor
        apply_subscription_event(
            self._event("customer.subscription.deleted"), self.MAP, database=db)
        self.assertEqual(db.store["row"]["period_start"], anchor)

    def test_unpaid_subscription_grants_nothing(self):
        from services.stripe_subscription_tiers import apply_subscription_event
        db = FakeDB(account_row())
        out = apply_subscription_event(
            self._event("customer.subscription.created", status="incomplete"),
            self.MAP, database=db)
        self.assertFalse(out["handled"])
        self.assertEqual(db.store["row"]["token_balance"], 12_000)

    def test_missing_user_id_is_refused_not_guessed(self):
        from services.stripe_subscription_tiers import apply_subscription_event
        ev = self._event("customer.subscription.created")
        ev["data"]["object"]["metadata"] = {}
        out = apply_subscription_event(ev, self.MAP, database=FakeDB(account_row()))
        self.assertFalse(out["handled"])
        self.assertEqual(out["reason"], "missing_user_id")

    def test_malformed_price_map_does_not_explode_the_webhook(self):
        from services.stripe_subscription_tiers import parse_price_tier_map
        self.assertEqual(parse_price_tier_map("not json"), {})
        self.assertEqual(parse_price_tier_map(""), {})
        self.assertEqual(parse_price_tier_map('{"p":"platinum"}'), {})

    def test_redelivery_is_idempotent(self):
        """Stripe delivers at least once; re-applying must not stack grants."""
        from services.stripe_subscription_tiers import apply_subscription_event
        db = FakeDB(account_row())
        ev = self._event("customer.subscription.created")
        apply_subscription_event(ev, self.MAP, database=db)
        apply_subscription_event(ev, self.MAP, database=db)
        self.assertEqual(db.store["row"]["token_balance"], 300_000)


class MidPeriodTierChangeTests(unittest.TestCase):
    """What a plan change does to a balance and to the coach counter.

    `customer.subscription.updated` is NOT a renewal signal — Stripe also fires
    it for card changes, cancel-toggles and metadata edits. The old code wrote
    `balance = grant_for(tier)` and `coach_reviews_used = 0` on every one of
    them, which produced two separate faults:

      * a mid-period DOWNGRADE truncated the balance the user had already paid
        for (Max 1.4M → Starter = 50k, instantly);
      * ANY subscription event re-granted a month of tokens and reset the coach
        counter, so the founder's calendar cap could be cleared for free by
        toggling something in the billing portal. That cap is a fence.

    THE RULE PINNED HERE: the billing anchor decides, not the event.
      anchor moved  → SET the grant, zero the counter (a real new period)
      tier changed  → balance = max(current, new grant), counter CARRIES
      neither       → nothing moves at all
    """

    MAP = '{"price_starter":"starter","price_pro":"pro","price_max":"max"}'

    def setUp(self):
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()
        # Anchor a few days back: inside the current period, so nothing rolls
        # underneath the assertions.
        self.anchor = datetime.now(UTC) - timedelta(days=5)

    def tearDown(self):
        self.env.stop()

    def _db(self, tier, balance, reviews=0):
        db = FakeDB(account_row(tier, balance=balance, start=self.anchor,
                                reviews=reviews))
        return db

    def _event(self, price, *, etype="customer.subscription.updated",
               anchor=None):
        """Same billing anchor as the stored row unless told otherwise — i.e. a
        mid-period change, which is the case under test."""
        start = anchor or self.anchor
        return {"type": etype, "data": {"object": {
            "id": "sub_1", "status": "active", "customer": "cus_1",
            "metadata": {"user_id": "u1"},
            "current_period_start": int(start.timestamp()),
            "items": {"data": [{"price": {"id": price}}]}}}}

    def _apply(self, db, price, **kw):
        from services.stripe_subscription_tiers import apply_subscription_event
        return apply_subscription_event(self._event(price, **kw), self.MAP,
                                        database=db)

    # ── downgrade ────────────────────────────────────────────────────
    def test_downgrade_does_not_truncate_the_balance_they_paid_for(self):
        """THE question the FE could not write copy for: Max with 1.4M drops to
        Starter (50k) — what happens to the balance above the new cap?

        Answer: nothing, this period. They bought this month at Max. The smaller
        grant lands by itself at the next roll, which is the rule every tier
        already runs on (nothing rolls over), so it needs no special sentence."""
        db = self._db("max", 1_400_000)
        self._apply(db, "price_starter")
        self.assertEqual(db.store["row"]["tier"], "starter")
        self.assertEqual(db.store["row"]["token_balance"], 1_400_000)

    def test_the_smaller_grant_lands_at_the_next_roll(self):
        """The other half of the above: the downgrade is real, just deferred."""
        import services.token_account as ta
        db = self._db("max", 1_400_000)
        self._apply(db, "price_starter")
        db.store["row"]["period_start"] = (
            datetime.now(UTC) - timedelta(days=40)).isoformat()
        out = ta.ensure_period_current("u1", database=db)
        self.assertEqual(out["token_balance"], 50_000)

    # ── upgrade ──────────────────────────────────────────────────────
    def test_upgrade_lifts_to_the_new_allowance_immediately(self):
        """Plan §10.11: full new-tier grant on upgrade, not pro-rated. Slightly
        generous and trivially explainable, which is worth more here than exact
        — the FE has to state it before checkout."""
        db = self._db("starter", 5_000)
        self._apply(db, "price_pro")
        self.assertEqual(db.store["row"]["token_balance"], 300_000)

    def test_upgrade_never_reduces_a_balance(self):
        """Guards the max(): someone holding more than the new tier's grant
        must not be trimmed by an UPGRADE either."""
        db = self._db("starter", 400_000)   # e.g. left over from a Pro month
        self._apply(db, "price_pro")
        self.assertEqual(db.store["row"]["token_balance"], 400_000)

    # ── the coach cap (fence) ────────────────────────────────────────
    def test_a_portal_toggle_cannot_reset_the_coach_counter(self):
        """THE fence. coach_reviews_used is the founder's calendar, and it must
        not be clearable by anything a user can click. A card change or a
        cancel-toggle arrives here as subscription.updated with the same tier
        and the same anchor."""
        db = self._db("pro", 120_000, reviews=6)
        self._apply(db, "price_pro")
        self.assertEqual(db.store["row"]["coach_reviews_used"], 6)

    def test_a_portal_toggle_does_not_re_grant_tokens(self):
        """Same event, the money half: a spent-down Pro user must not get a
        fresh 300,000 for updating their card."""
        db = self._db("pro", 12_000)
        self._apply(db, "price_pro")
        self.assertEqual(db.store["row"]["token_balance"], 12_000)

    def test_used_reviews_carry_across_a_mid_period_upgrade(self):
        """An upgrade may RAISE the cap; it may not refund reviews already
        taken. 1 used on starter becomes 1-of-6 on pro, not 0-of-6 — otherwise
        upgrade-and-downgrade is an unlimited coach-review loop."""
        import services.token_account as ta
        db = self._db("starter", 50_000, reviews=1)
        self._apply(db, "price_pro")
        self.assertEqual(db.store["row"]["coach_reviews_used"], 1)
        acct = ta.get_account("u1", database=db)
        self.assertEqual(acct["coach_reviews"],
                         {"used": 1, "allowed": 6, "remaining": 5})

    def test_a_genuine_renewal_still_resets_both(self):
        """The rule is anchor-driven, so a real new billing period must behave
        exactly like the monthly roll: SET the grant, zero the counter."""
        db = self._db("pro", 9_000, reviews=6)
        self._apply(db, "price_pro", anchor=datetime.now(UTC))
        self.assertEqual(db.store["row"]["token_balance"], 300_000)
        self.assertEqual(db.store["row"]["coach_reviews_used"], 0)

    def test_a_later_upgrade_is_still_recorded_in_the_ledger(self):
        """Keyed on the bare subscription id, the unique index would reject
        every tier_change after the first and the audit trail would quietly stop
        at signup."""
        db = self._db("starter", 50_000)
        self._apply(db, "price_pro")
        self._apply(db, "price_max")
        changes = [r for r in db.ledger if r["action"] == "tier_change"]
        self.assertEqual([r["tier"] for r in changes], ["pro", "max"])
        self.assertEqual(changes[-1]["delta"], 1_500_000 - 300_000)


class LegacyCreditConversionTests(unittest.TestCase):
    """Honoured legacy credits: the rate, the floor, and the bucket.

    Founder 2026-08-01: credits are retired and the balances people still hold
    are honoured ONCE, at arc-equivalence (1,600 tokens/credit), above the free
    25 everyone was granted.

    The two things that make this correct rather than merely generous:

      * THE FLOOR. Nothing in the schema tells a purchased credit from a
        granted one — stripe_checkout_credit_grants stores a session id and
        nothing else — and every account was seeded 25 free (plus the
        2026-07-13 bump to >=25). A flat conversion would therefore hand every
        account that ever signed up 40,000 non-expiring tokens, 3.3x the whole
        free monthly tier, paid or not.
      * THE BUCKET. The monthly roll SETS token_balance, so tokens honoured
        into it are deleted within 30 days — for a dormant user, before they
        ever log in again. bonus_balance is never touched by the roll.
    """

    def setUp(self):
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    # ── the rate and the floor ───────────────────────────────────────
    def test_the_rate_is_arc_equivalence_not_a_guess(self):
        """25 credits bought an arc unlock; the same four deliverables cost
        40,000 tokens. 40,000/25 = 1,600. If any of those prices move, this
        assertion is the thing that says the conversion rate moved too."""
        from services.token_prices import LEGACY_CREDIT_TOKENS, PRICES
        arc = (PRICES["insights"] + PRICES["game"]
               + PRICES["moment_explanation"] + PRICES["coach_review"])
        self.assertEqual(arc, 40_000)
        self.assertEqual(arc // 25, LEGACY_CREDIT_TOKENS)

    def test_the_free_grant_is_not_converted(self):
        """Everyone holds >=25 for free. Converting those would pay every
        signup 40,000 non-expiring tokens for never having paid anything."""
        from services.token_prices import legacy_credit_tokens
        self.assertEqual(legacy_credit_tokens(25), 0)
        self.assertEqual(legacy_credit_tokens(0), 0)
        self.assertEqual(legacy_credit_tokens(None), 0)
        self.assertEqual(legacy_credit_tokens(10), 0, "below the free floor")

    def test_a_real_balance_is_honoured_above_the_floor(self):
        from services.token_prices import legacy_credit_tokens
        self.assertEqual(legacy_credit_tokens(455), (455 - 25) * 1_600)
        self.assertEqual(legacy_credit_tokens(455), 688_000)
        self.assertEqual(legacy_credit_tokens(26), 1_600)

    def test_junk_never_raises_and_never_pays(self):
        from services.token_prices import legacy_credit_tokens
        self.assertEqual(legacy_credit_tokens("nonsense"), 0)
        self.assertEqual(legacy_credit_tokens(-5), 0)

    def test_the_sql_and_the_python_agree(self):
        """They are two copies of one decision. If the migration pays a
        different amount than the ledger row claims, the drift is invisible
        until someone audits a balance by hand."""
        from services.token_prices import (
            LEGACY_CREDIT_FREE_FLOOR, LEGACY_CREDIT_TOKENS,
        )
        with open("migrations/add_legacy_credit_conversion.sql") as fh:
            sql = fh.read()
        self.assertIn(
            f"GREATEST(COALESCE(d.credits, 0) - {LEGACY_CREDIT_FREE_FLOOR}, 0)"
            f" * {LEGACY_CREDIT_TOKENS})", sql)
        self.assertIn("legacy_credit_conversion", sql)
        # One conversion per user, forever — the ref is what the partial unique
        # index keys on.
        self.assertIn("'legacy-credits-1600-v1'", sql)

    # ── the bucket ───────────────────────────────────────────────────
    def test_honoured_tokens_survive_the_monthly_roll(self):
        """THE reason this is not just added to token_balance. The roll SETS
        the tier grant, so 688,000 honoured into it would be gone inside 30
        days — before a dormant user ever logged back in."""
        import services.token_account as ta
        start = datetime.now(UTC) - timedelta(days=40)
        db = FakeDB(account_row("free", balance=9_000, start=start,
                                bonus=688_000))
        ta.ensure_period_current("u1", database=db)
        self.assertEqual(db.store["row"]["token_balance"], 12_000, "rolled")
        self.assertEqual(db.store["row"]["bonus_balance"], 688_000,
                         "the honoured credits were deleted by the roll")

    def test_four_dormant_months_still_leave_the_bonus_intact(self):
        import services.token_account as ta
        start = datetime.now(UTC) - timedelta(days=130)
        db = FakeDB(account_row("free", balance=0, start=start, bonus=40_000))
        ta.ensure_period_current("u1", database=db)
        self.assertEqual(db.store["row"]["bonus_balance"], 40_000)

    def test_balance_reports_the_total_and_the_split(self):
        """`balance` stays "what you can spend now" so existing readers are
        unaffected; the split exists because period_ends_at applies to the
        monthly half ONLY. One renewal date over a partly non-expiring total
        would tell someone their honoured credits are about to vanish."""
        import services.token_account as ta
        acct = ta.get_account("u1", database=FakeDB(
            account_row("free", balance=12_000, bonus=688_000)))
        self.assertEqual(acct["balance"], 700_000)
        self.assertEqual(acct["monthly_balance"], 12_000)
        self.assertEqual(acct["bonus_balance"], 688_000)

    def test_unmigrated_database_reads_as_no_bonus(self):
        """add_legacy_credit_conversion.sql is run by hand. Until it is, the
        balance must still read — 0 is exactly today's behaviour."""
        import services.token_account as ta
        db = FakeDB(account_row("pro", balance=300_000))
        db.client.table.side_effect = RuntimeError("column does not exist")
        self.assertEqual(ta._read_bonus_balance("u1", database=db), 0)

    # ── spending order ───────────────────────────────────────────────
    def test_the_expiring_allowance_is_spent_first(self):
        """Spending the bonus first would burn the permanent balance while the
        monthly one evaporated unused at the roll."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000, bonus=688_000))
        res = ta.charge("u1", "take_short", database=db)   # 1,000
        self.assertTrue(res.ok)
        self.assertEqual(db.store["row"]["token_balance"], 11_000)
        self.assertEqual(db.store["row"]["bonus_balance"], 688_000,
                         "spent the non-expiring bucket while monthly remained")

    def test_the_bonus_covers_the_overflow_once_monthly_runs_out(self):
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=400, bonus=688_000))
        res = ta.charge("u1", "take_short", database=db)   # 1,000
        self.assertTrue(res.ok)
        self.assertEqual(res.charged, 1_000)
        self.assertEqual(db.store["row"]["token_balance"], 0)
        self.assertEqual(db.store["row"]["bonus_balance"], 687_400)

    def test_an_empty_month_spends_the_bonus_alone(self):
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=0, bonus=40_000))
        res = ta.charge("u1", "take_medium", database=db)  # 3,000
        self.assertTrue(res.ok)
        self.assertEqual(db.store["row"]["bonus_balance"], 37_000)

    def test_the_bonus_counts_toward_affordability(self):
        """A zero monthly balance with honoured credits behind it is NOT
        insufficient — that would be refusing to let someone spend what we just
        told them they had."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=0, bonus=40_000))
        res = ta.charge("u1", "coach_review", database=db)  # 35,000
        self.assertNotEqual(res.reason, "insufficient")

    def test_running_out_of_both_still_reports_rather_than_raises(self):
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=100, bonus=100))
        res = ta.charge("u1", "coach_review", database=db)
        self.assertFalse(res.ok)
        self.assertEqual(res.balance, 200)

    def test_a_charge_without_any_bonus_writes_the_same_row_as_before(self):
        """Pre-migration safety: with no bonus in play the write must not
        mention bonus_balance at all, or it would fail on a database where the
        column does not exist yet.

        Asserted on BOTH paths. The atomic one builds its SET list dynamically
        precisely so a database without add_legacy_credit_conversion.sql never
        sees the column named — the property is the same, only the mechanism
        differs, so neither implementation gets to skip it."""
        import services.token_account as ta

        # Atomic path: the function's staged column list.
        db = FakeDB(account_row("free", balance=12_000))
        ta.charge("u1", "take_short", database=db)
        self.assertTrue(db.account_writes, "no account write happened")
        for w in db.account_writes:
            self.assertNotIn("bonus_balance", w)

        # Legacy path: the same property, seen through .table().update().
        legacy = FakeDB(account_row("free", balance=12_000), rpc_installed=False)
        writes = []
        orig = legacy._table

        def _spy(name):
            t = orig(name)
            if name != "token_ledger":
                inner = t.update

                def _update(payload):
                    writes.append(payload)
                    return inner(payload)
                t.update = _update
            return t
        legacy.client.table.side_effect = _spy
        ta.charge("u1", "take_short", database=legacy)
        self.assertTrue(writes, "no account write happened")
        for w in writes:
            self.assertNotIn("bonus_balance", w)


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

    def test_a_grant_lands_in_the_bucket_that_does_not_expire(self):
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=9_000, bonus=0))
        acct = ta.admin_grant("u1", 1_000_000, ref_id="r1", database=db)
        self.assertEqual(db.store["row"]["bonus_balance"], 1_000_000)
        # The monthly half is UNTOUCHED — a top-up must not look like a
        # period grant, or the next roll would appear to delete it.
        self.assertEqual(db.store["row"]["token_balance"], 9_000)
        self.assertEqual(acct["balance"], 1_009_000)

    def test_the_grant_survives_the_monthly_roll(self):
        import services.token_account as ta
        start = datetime.now(UTC) - timedelta(days=40)
        db = FakeDB(account_row("free", balance=9_000, start=start, bonus=0))
        ta.admin_grant("u1", 1_000_000, ref_id="r1", database=db)
        ta.ensure_period_current("u1", database=db)
        self.assertEqual(db.store["row"]["token_balance"], 12_000, "rolled")
        self.assertEqual(db.store["row"]["bonus_balance"], 1_000_000)

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

    def test_a_different_ref_id_grants_again(self):
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=0, bonus=0))
        ta.admin_grant("u1", 100, ref_id="a", database=db)
        ta.admin_grant("u1", 100, ref_id="b", database=db)
        self.assertEqual(db.store["row"]["bonus_balance"], 200)

    def test_a_negative_grant_corrects_and_floors_at_zero(self):
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=0, bonus=1_000))
        ta.admin_grant("u1", -400, ref_id="fix", database=db)
        self.assertEqual(db.store["row"]["bonus_balance"], 600)
        ta.admin_grant("u1", -9_999, ref_id="fix2", database=db)
        self.assertEqual(db.store["row"]["bonus_balance"], 0)

    def test_junk_is_refused_rather_than_guessed(self):
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=0, bonus=0))
        for bad in (None, "x", 0):
            self.assertIsNone(
                ta.admin_grant("u1", bad, ref_id="r", database=db))
        self.assertIsNone(ta.admin_grant("", 100, ref_id="r", database=db))
        self.assertEqual(db.store["row"]["bonus_balance"], 0)

    def test_the_movement_is_written_to_the_ledger(self):
        """The balance is a cache; the ledger is the truth. A grant nobody
        can prove happened is the state this table exists to prevent."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=1_000, bonus=0))
        ta.admin_grant("u1", 250_000, ref_id="r1", database=db)
        rows = [r for r in db.ledger
                if r.get("action") == ta.ADMIN_ADJUST]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["delta"], 250_000)
        self.assertEqual(rows[0]["balance_after"], 251_000)
        self.assertEqual(rows[0]["ref_id"], "r1")


class PlanStateTests(unittest.TestCase):
    """`plan` on the balance: is this tier a live subscription, or the default?

    Without it the FE cannot tell "you are on free, upgrade" from "you are on
    Pro, manage it" — which is what left four published, priced tiers with no
    way to buy or leave them.
    """

    def setUp(self):
        self.env = patch.dict("os.environ", {"TOKEN_PRICING_ENABLED": "1"})
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_free_user_is_not_managed(self):
        import services.token_account as ta
        plan = ta.plan_state("u1", tier="free", database=FakeDB(account_row()))
        self.assertFalse(plan["managed"])
        self.assertFalse(plan["manage_available"])

    def test_active_subscription_is_managed(self):
        import services.token_account as ta
        db = FakeDB(account_row("pro", balance=300_000))
        db.store["row"].update({
            "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1",
            "stripe_subscription_status": "active",
            "subscription_cancel_at_period_end": False,
        })
        plan = ta.plan_state("u1", tier="pro", database=db)
        self.assertTrue(plan["managed"])
        self.assertTrue(plan["manage_available"])
        self.assertEqual(plan["tier"], "pro")

    def test_past_due_is_still_managed(self):
        """The card failed; the subscription exists and the portal is where it
        gets fixed. Showing 'upgrade' would sell a second subscription to solve
        a billing problem."""
        import services.token_account as ta
        db = FakeDB(account_row("pro", balance=300_000))
        db.store["row"].update({
            "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1",
            "stripe_subscription_status": "past_due"})
        self.assertTrue(ta.plan_state("u1", tier="pro", database=db)["managed"])

    def test_cancelled_subscription_is_not_managed_but_stays_reachable(self):
        import services.token_account as ta
        db = FakeDB(account_row("free"))
        db.store["row"].update({
            "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1",
            "stripe_subscription_status": "canceled",
            "subscription_cancel_at_period_end": True})
        plan = ta.plan_state("u1", tier="free", database=db)
        self.assertFalse(plan["managed"])
        # Not "cancelling" — already gone. Showing a lapse date for a plan they
        # no longer hold reads as though they still have it.
        self.assertFalse(plan["cancel_at_period_end"])
        self.assertTrue(plan["manage_available"], "cannot reach their invoices")

    def test_cancel_at_period_end_carries_the_date_they_lose_it(self):
        import services.token_account as ta
        ends = (datetime.now(UTC) + timedelta(days=12)).isoformat()
        db = FakeDB(account_row("pro", balance=300_000))
        db.store["row"].update({
            "stripe_customer_id": "cus_1", "stripe_subscription_id": "sub_1",
            "stripe_subscription_status": "active",
            "subscription_cancel_at_period_end": True,
            "subscription_current_period_end": ends})
        plan = ta.plan_state("u1", tier="pro", database=db)
        self.assertTrue(plan["managed"])
        self.assertTrue(plan["cancel_at_period_end"])
        self.assertTrue(plan["current_period_end"].startswith(ends[:10]))

    def test_unmigrated_database_degrades_to_upgrade_only(self):
        """add_subscription_state.sql has to be run by hand. Until it is, the
        balance must still read — 'on main' is not 'run in prod'."""
        import services.token_account as ta
        db = FakeDB(account_row("pro", balance=300_000))
        db.client.table.side_effect = RuntimeError("column does not exist")
        plan = ta.plan_state("u1", tier="pro", database=db)
        self.assertFalse(plan["managed"])
        self.assertFalse(plan["manage_available"])

    def test_balance_carries_plan_and_no_usage_framing(self):
        """AC-9 does not stop applying because the surface is billing. `plan`
        may say what was bought and when it renews; it may never carry a
        percentage used, a streak, or a comparison."""
        import services.token_account as ta
        acct = ta.get_account("u1", database=FakeDB(account_row("pro", 250_000)))
        self.assertIn("plan", acct)
        banned = ("percent", "pct", "used_ratio", "usage", "streak", "rank",
                  "score", "efficiency", "compared", "average")
        for key in acct["plan"]:
            self.assertNotIn(key.lower().replace("_", ""),
                             [b.replace("_", "") for b in banned],
                             f"plan.{key} is performance framing")


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

    # ── it actually goes through the function ─────────────────────────
    def test_charging_calls_the_postgres_function_with_the_priced_amount(self):
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000))
        res = ta.charge("u1", "take_short", ref_id="rec1", database=db)
        self.assertTrue(res.ok)
        self.assertEqual(len(db.rpc_calls), 1)
        call = db.rpc_calls[0]
        self.assertEqual(call["p_user_id"], "u1")
        self.assertEqual(call["p_action"], "take_short")
        self.assertEqual(call["p_price"], res.charged)
        self.assertEqual(call["p_ref_id"], "rec1")
        # The price version rides with the charge so a repricing stays
        # auditable and historical rows never re-interpret.
        self.assertEqual(call["p_price_version"], ta.PRICE_VERSION)

    # ── half-state A: a debit whose ledger row never landed ───────────
    def test_legacy_debits_without_a_ledger_row_then_double_charges(self):
        """The bug, demonstrated. The ledger is the idempotency record, so a
        debit that fails to record it re-arms the probe — and the recording
        pipeline retries by design."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000), rpc_installed=False)

        with patch.object(ta, "_ledger", lambda *a, **k: None):
            ta.charge("u1", "take_short", ref_id="rec1", database=db)
        first = db.store["row"]["token_balance"]
        self.assertLess(first, 12_000, "the debit landed")
        self.assertEqual(db.ledger, [], "…and nothing recorded it")

        # The pipeline retries the same recording_id. Nothing remembers.
        ta.charge("u1", "take_short", ref_id="rec1", database=db)
        self.assertLess(db.store["row"]["token_balance"], first,
                        "legacy path charged the same recording twice")

    def test_atomic_charge_leaves_the_balance_untouched_if_the_ledger_fails(self):
        """Same failure, one transaction: the INSERT takes the UPDATE down with
        it, so there is no debit to be un-recorded and the retry is still
        priced normally."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000))
        db.ledger_insert_fails = True

        res = ta.charge("u1", "take_short", ref_id="rec1", database=db)
        self.assertEqual(db.store["row"]["token_balance"], 12_000,
                         "balance moved despite the ledger insert failing")
        self.assertEqual(db.ledger, [])
        # Fence §6.1 still holds — a billing failure never fails the take.
        self.assertTrue(res.ok)
        self.assertEqual(res.charged, 0)
        self.assertEqual(res.reason, "write_failed")

        # And the retry is a NORMAL first charge, not a second one.
        db.ledger_insert_fails = False
        again = ta.charge("u1", "take_short", ref_id="rec1", database=db)
        self.assertTrue(again.ok)
        self.assertEqual(len(db.ledger), 1)
        self.assertEqual(db.store["row"]["token_balance"],
                         12_000 - again.charged)

    # ── half-state B: TOCTOU between the probe and the debit ──────────
    def test_legacy_probe_and_debit_race_into_a_double_debit(self):
        """Two workers, one ref. Both probe an empty ledger, both debit; the
        unique index drops the second ROW and the second DEBIT stands. The
        balance and the ledger then disagree, permanently — and the ledger is
        the documented source of truth, so nothing can reconcile them.

        The interleaving is produced for real: the second charge runs at the
        exact moment the first is about to write its ledger row."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000), rpc_installed=False)
        start = 12_000
        orig_table = db._table
        reentered = []

        def _racing_table(name):
            t = orig_table(name)
            if name == "token_ledger":
                inner = t.execute

                def _execute():
                    if t._op == "insert" and not reentered:
                        reentered.append(True)
                        # Worker 2 arrives here: the ledger is still empty, so
                        # its probe says "not charged" and it debits too.
                        ta.charge("u1", "take_short", ref_id="rec1",
                                  database=db)
                    return inner()
                t.execute = _execute
            return t
        db.client.table.side_effect = _racing_table

        ta.charge("u1", "take_short", ref_id="rec1", database=db)

        price = ta.price_of("take_short")
        self.assertTrue(reentered, "the race never happened — test is broken")
        self.assertEqual(len(db.ledger), 1, "one row, as the index enforces")
        self.assertEqual(db.store["row"]["token_balance"], start - 2 * price,
                         "legacy path debited twice for one ledger row")

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

    def test_chat_stays_repeatable_because_it_has_no_ref(self):
        """The once-per-ref guard must not leak onto actions that legitimately
        repeat — a second chat turn is a second charge."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000))
        ta.charge("u1", "chat", database=db)
        ta.charge("u1", "chat", database=db)
        self.assertEqual(len(db.ledger), 2)

    # ── half-state C: a spent balance with an unmoved coach counter ───
    def test_the_coach_counter_moves_in_the_same_write_as_the_debit(self):
        import services.token_account as ta
        db = FakeDB(account_row("pro", balance=300_000, reviews=0))
        res = ta.charge("u1", "coach_review", ref_id="arc1", database=db)
        self.assertTrue(res.ok)
        self.assertEqual(db.store["row"]["coach_reviews_used"], 1)
        # One write carrying both, not a debit plus a second CAS that can fail
        # on its own and hand out a free review past the cap.
        self.assertEqual(len(db.account_writes), 1)
        self.assertIn("coach_reviews_used", db.account_writes[0])
        self.assertIn("token_balance", db.account_writes[0])

    def test_a_capped_coach_review_writes_nothing_at_all(self):
        import services.token_account as ta
        db = FakeDB(account_row("starter", balance=50_000, reviews=1))
        res = ta.charge("u1", "coach_review", ref_id="arc1", database=db)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "coach_cap_reached")
        self.assertEqual(db.account_writes, [])
        self.assertEqual(db.ledger, [])
        self.assertEqual(db.store["row"]["token_balance"], 50_000)

    # ── the migration may not have been run yet ───────────────────────
    def test_a_database_without_the_function_still_charges(self):
        """"Merged on main" is not "run in prod" in this repo. A database
        without the migration must keep charging, not start failing open."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000), rpc_installed=False)
        res = ta.charge("u1", "take_short", ref_id="rec1", database=db)
        self.assertTrue(res.ok)
        self.assertGreater(res.charged, 0)
        self.assertEqual(len(db.ledger), 1)
        self.assertEqual(db.store["row"]["token_balance"],
                         12_000 - res.charged)

    def test_both_paths_return_the_same_result_for_the_same_scenario(self):
        """The contract callers depend on is identical either side of the
        migration — that is what makes the rollout safe in either order."""
        import services.token_account as ta
        for ref in ("rec1", None):
            atomic = ta.charge(
                "u1", "take_short", ref_id=ref,
                database=FakeDB(account_row("free", balance=12_000)))
            legacy = ta.charge(
                "u1", "take_short", ref_id=ref,
                database=FakeDB(account_row("free", balance=12_000),
                                rpc_installed=False))
            self.assertEqual(atomic.as_dict(), legacy.as_dict(), f"ref={ref}")

        # …including the refusals.
        broke = ta.charge("u1", "take_short",
                          database=FakeDB(account_row("free", balance=0)))
        broke_legacy = ta.charge(
            "u1", "take_short",
            database=FakeDB(account_row("free", balance=0),
                            rpc_installed=False))
        self.assertEqual(broke.as_dict(), broke_legacy.as_dict())
        self.assertFalse(broke.ok)
        self.assertEqual(broke.reason, "insufficient")

    def test_the_missing_function_probe_is_cached_then_retried(self):
        """One failed round trip per window, not one per charge — but it MUST
        expire, or running the migration would need a redeploy to take effect."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000), rpc_installed=False)
        ta.charge("u1", "chat", database=db)
        self.assertEqual(len(db.rpc_calls), 0)   # raised before recording
        probes = db.client.rpc.call_count
        self.assertEqual(probes, 1)

        ta.charge("u1", "chat", database=db)
        self.assertEqual(db.client.rpc.call_count, probes,
                         "re-probed inside the cache window")

        ta._rpc_missing_until = 0.0               # window elapsed
        ta.charge("u1", "chat", database=db)
        self.assertEqual(db.client.rpc.call_count, probes + 1,
                         "never re-probed — the migration would need a deploy")

    # ── a real failure must NOT be retried through the legacy path ────
    def test_a_genuine_rpc_error_fails_open_without_falling_back(self):
        """This is the dangerous direction. "The call failed" and "the call
        committed but the response was lost" are indistinguishable from here,
        so falling back would replay a charge that may already have landed —
        the double debit this whole change removes."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000))
        db.client.rpc.side_effect = RuntimeError("connection reset by peer")

        res = ta.charge("u1", "take_short", ref_id="rec1", database=db)
        self.assertTrue(res.ok, "fence §6.1: billing never fails the take")
        self.assertEqual(res.charged, 0)
        self.assertEqual(res.reason, "write_failed")
        # No fallback ran: nothing was written by hand behind the function.
        self.assertEqual(db.ledger, [])
        self.assertEqual(db.store["row"]["token_balance"], 12_000)

    def test_only_a_missing_function_counts_as_missing(self):
        import services.token_account as ta
        self.assertTrue(ta._rpc_not_found(RpcNotInstalled()))
        self.assertTrue(ta._rpc_not_found(
            RuntimeError("PGRST202 Could not find the function")))
        self.assertFalse(ta._rpc_not_found(RuntimeError("connection reset")))
        self.assertFalse(ta._rpc_not_found(
            RuntimeError("insufficient_privilege for token_charge")))
        # A row-level failure inside a function that DOES exist must never be
        # read as "not installed".
        self.assertFalse(ta._rpc_not_found(
            RuntimeError("duplicate key value violates unique constraint "
                         "uq_token_ledger_once_per_ref")))

    def test_an_account_row_that_vanished_mid_flight_fails_open(self):
        """The function's own NOT FOUND branch.

        Reaching it takes a row that disappears BETWEEN the seed and the
        charge — ensure_period_current re-seeds an absent account first, so an
        ordinary missing row just charges normally. Rare, and it still must
        not fail a recording: fence §6.1 says a billing lookup we cannot
        complete costs us the fee, never the take."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000))

        with patch.object(ta, "ensure_period_current",
                          return_value=account_row("free", 12_000)):
            db.store["row"] = None                # deleted after the seed
            res = ta.charge("u1", "take_short", database=db)

        self.assertTrue(res.ok)
        self.assertEqual(res.charged, 0)
        self.assertEqual(res.reason, "account_unavailable")
        self.assertEqual(db.ledger, [])


if __name__ == "__main__":
    unittest.main()
