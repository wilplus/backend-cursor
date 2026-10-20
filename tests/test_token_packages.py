"""
STORY    As a speaker, I want to buy a package once at the published price and
         get my tokens exactly once, so that I am never charged a
         subscription or credited twice. (Critical path: payments.)
OUTCOME
  O1  The buy button opens a one-time USD checkout at the listed price, never
      a subscription.
  O2  Only a session Stripe says is paid, one-time, in USD, for exactly the
      package's price grants it; anything else grants nothing.
  O3  A grant that could not be written asks Stripe to deliver again; a
      repeated delivery grants nothing more.
  O4  The webhook applies a package and nothing else: a subscription event or
      an old arc checkout is acknowledged and grants nothing.
  O5  Nothing renews: months later the balance is what it was, with no new
      grant and no renewal date.
  O6  A package carries tokens only: no package on sale grants coach reviews
      (a review is paid in tokens since 2026-10-14).
PROVES   O1 -> test_checkout_is_one_time_at_the_published_price
         O2 -> test_a_paid_session_grants_the_package
            -> test_anything_but_a_paid_exact_package_grants_nothing
         O3 -> test_a_failed_grant_asks_stripe_to_deliver_again
            -> test_a_second_delivery_grants_nothing
         O4 -> test_the_webhook_grants_packages_and_nothing_else
         O5 -> test_nothing_renews
         O6 -> test_a_package_grants_no_coach_reviews
WHY      Contract section 8; founder 2026-10-05 "Packages" (N44, N48.3 Q13 A).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import pytest
from flask import Flask

from routes import internal_webhooks
from services import token_account as ta
from services import token_packages as tp
from services.token_prices import SOLD_TIERS, TIERS

CONFIG = SimpleNamespace(STRIPE_SECRET_KEY="sk_test", FRONTEND_URL="https://app.test")


# ── checkout ────────────────────────────────────────────────────────────

def _create(package="practice", **extra):
    with mock.patch("stripe.checkout.Session.create",
                    return_value={"id": "cs_1", "url": "https://pay"}) as create:
        result = tp.create_package_checkout_session(
            user_id="u1", package=package, app_config=CONFIG, **extra)
    return result, create


def test_checkout_is_one_time_at_the_published_price():
    result, create = _create("coaching")
    assert result.ok and result.payload["checkout_url"] == "https://pay"
    kwargs = create.call_args.kwargs
    assert kwargs["mode"] == "payment"
    assert "subscription_data" not in kwargs
    item = kwargs["line_items"][0]
    assert item["price_data"]["unit_amount"] == TIERS["coaching"]["usd"] * 100
    assert item["price_data"]["currency"] == "usd"
    assert kwargs["metadata"] == {"user_id": "u1", "package": "coaching",
                                  "tier": "coaching", "kind": tp.PACKAGE_KIND,
                                  "cents": str(TIERS["coaching"]["usd"] * 100)}


# ── webhook ─────────────────────────────────────────────────────────────

def _session(**over):
    spec = tp.package_spec("practice")
    base = {"id": "cs_1", "mode": "payment", "payment_status": "paid",
            "currency": "usd", "amount_total": spec["cents"],
            "metadata": {"user_id": "u1", "package": "practice",
                         "kind": tp.PACKAGE_KIND}}
    base.update(over)
    return base


def _apply(session, grant=None):
    grant = grant or mock.Mock(return_value={"ok": True, "reason": ""})
    with mock.patch("stripe.checkout.Session.retrieve", return_value=session), \
            mock.patch.object(ta, "package_grant", grant):
        result = tp.apply_completed_package_checkout("cs_1", CONFIG)
    return result, grant


def test_a_paid_session_grants_the_package():
    result, grant = _apply(_session())
    assert (result.http_status, result.payload["granted"]) == (200, True)
    spec = TIERS["practice"]
    grant.assert_called_once_with(
        "u1", tokens=spec["tokens"], coach_reviews=spec["coach_reviews"],
        ref_id="cs_1", package="practice", database=None)


@pytest.mark.parametrize("over, reason", [
    ({"payment_status": "unpaid"}, "not_paid"),
    ({"mode": "subscription"}, "not_one_time"),
    ({"amount_total": 1}, "amount_mismatch"),
    ({"currency": "eur"}, "amount_mismatch"),
    ({"metadata": {"user_id": "u1", "package": "max", "kind": tp.PACKAGE_KIND}},
     "unknown_buyer_or_package"),
    ({"metadata": {"package": "practice", "kind": tp.PACKAGE_KIND}},
     "unknown_buyer_or_package"),
])
def test_anything_but_a_paid_exact_package_grants_nothing(over, reason):
    result, grant = _apply(_session(**over))
    assert (result.http_status, result.payload) == (200, {"granted": False, "reason": reason})
    grant.assert_not_called()


def test_a_failed_grant_asks_stripe_to_deliver_again():
    result, _ = _apply(_session(), mock.Mock(return_value={"ok": False, "reason": "no_row"}))
    assert result.http_status == 500


def _webhook(event, session=None):
    """POST one Stripe event to the webhook route; returns (status, body, grant)."""
    grant = mock.Mock(return_value={"ok": True, "reason": ""})
    with mock.patch.object(internal_webhooks, "config", SimpleNamespace(
            STRIPE_WEBHOOK_SECRET="whsec_test", STRIPE_SECRET_KEY="sk_test")), \
            mock.patch("stripe.Webhook.construct_event", return_value=event), \
            mock.patch("stripe.checkout.Session.retrieve", return_value=session), \
            mock.patch.object(ta, "package_grant", grant), \
            Flask(__name__).test_request_context(method="POST", data=b"{}"):
        resp, status = internal_webhooks.stripe_checkout_webhook()
    return status, resp.get_json(), grant


def _completed(metadata):
    return {"type": "checkout.session.completed",
            "data": {"object": {"id": "cs_1", "metadata": metadata}}}


def test_the_webhook_grants_packages_and_nothing_else():
    """N48.3 Q13 A: the subscription, arc-checkout and credit-pack paths are
    gone; a package is the only thing the webhook applies."""
    status, body, grant = _webhook(_completed(_session()["metadata"]), _session())
    assert (status, body["granted"]) == (200, True)
    grant.assert_called_once()

    status, body, grant = _webhook({"type": "customer.subscription.updated",
                                    "data": {"object": {"id": "sub_1"}}})
    assert (status, body) == (200, {"received": True})
    grant.assert_not_called()

    status, body, grant = _webhook(_completed({"user_id": "u1", "arc_id": "a1"}))
    assert (status, body["granted"], body["reason"]) == (200, False, "not_a_package")
    grant.assert_not_called()


# ── the grant ───────────────────────────────────────────────────────────

class _Query:
    def __init__(self, db, op, payload=None):
        self.db, self.op, self.payload, self.filters = db, op, payload, []

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        self.db.writes.append(payload)
        return self

    def upsert(self, payload):
        self.op, self.payload = "upsert", payload
        self.db.writes.append(payload)
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def is_(self, column, _null):
        self.filters.append((column, None))
        return self

    def limit(self, _n):
        return self

    def execute(self):
        row = self.db.row
        if self.op == "update":
            for column, value in self.filters:
                if column != "user_id" and row.get(column) != value:
                    return SimpleNamespace(data=[])
            row.update(self.payload)
            return SimpleNamespace(data=[dict(row)])
        return SimpleNamespace(data=[dict(row)])


class _Db:
    def __init__(self, **row):
        self.row = {"user_id": "u1", "tier": "free", "token_balance": 12_000,
                    "period_start": "2026-10-01T00:00:00+00:00",
                    "coach_reviews_used": 0, "bonus_balance": None,
                    "coach_review_credits": 0, **row}
        self.ledger: list[dict] = []
        self.writes: list[dict] = []
        self.client = SimpleNamespace(table=self._table)

    def _table(self, _name):
        return _Query(self, "select")


@pytest.fixture
def db(monkeypatch):
    database = _Db()
    monkeypatch.setattr(ta, "_already_charged",
                        lambda user_id, action, ref_id, database=None: any(
                            e["action"] == action and e["ref_id"] == ref_id
                            for e in database.ledger))
    monkeypatch.setattr(ta, "_ledger",
                        lambda user_id, delta, balance_after, action, ref_id=None,
                        tier=None, database=None: database.ledger.append(
                            {"delta": delta, "action": action, "ref_id": ref_id,
                             "tier": tier}))
    return database


def test_a_second_delivery_grants_nothing(db):
    for _ in range(2):
        ta.package_grant("u1", tokens=150_000, coach_reviews=0, ref_id="cs_1",
                         package="practice", database=db)
    assert db.row["bonus_balance"] == 150_000
    assert len(db.ledger) == 1


def test_a_package_grants_no_coach_reviews(db):
    for package in SOLD_TIERS:
        if package != "free":
            assert tp.package_spec(package)["coach_reviews"] == 0, package
    spec = tp.package_spec("coaching")
    ta.package_grant("u1", tokens=spec["tokens"], coach_reviews=spec["coach_reviews"],
                     ref_id="cs_2", package="coaching", database=db)
    assert db.row["bonus_balance"] == spec["tokens"]
    assert db.row["coach_review_credits"] == 0
    assert all("coach_review_credits" not in w for w in db.writes)


# ── nothing renews ──────────────────────────────────────────────────────

def test_nothing_renews(db):
    long_ago = datetime.now(timezone.utc) - timedelta(days=400)
    db.row.update(period_start=long_ago.isoformat(), token_balance=700,
                  bonus_balance=150_000)
    account = ta.get_account("u1", database=db)
    assert (account["balance"], account["bonus_balance"]) == (150_700, 150_000)
    assert account["period_ends_at"] is None
    assert db.writes == [] and db.ledger == []
