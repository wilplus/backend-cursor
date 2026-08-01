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
        f = dict(self._filters)
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


class FakeDB:
    def __init__(self, row=None):
        self.store = {"row": dict(row) if row else None}
        self.ledger: list = []
        self.client = MagicMock()
        self.client.table.side_effect = self._table

    def _table(self, name):
        if name == "token_ledger":
            return LedgerTable(self.store, self.ledger)
        return AccountTable(self.store, self.ledger)

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
        column does not exist yet."""
        import services.token_account as ta
        db = FakeDB(account_row("free", balance=12_000))
        writes = []
        orig = db._table

        def _spy(name):
            t = orig(name)
            if name != "token_ledger":
                inner = t.update

                def _update(payload):
                    writes.append(payload)
                    return inner(payload)
                t.update = _update
            return t
        db.client.table.side_effect = _spy
        ta.charge("u1", "take_short", database=db)
        self.assertTrue(writes, "no account write happened")
        for w in writes:
            self.assertNotIn("bonus_balance", w)


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


if __name__ == "__main__":
    unittest.main()
