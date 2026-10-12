"""Packages, bought once (contract §8; founder 2026-10-05, "Packages"; N44).

Pins:
  * the buy button opens a one-time Checkout (``mode="payment"``) at the
    published price, never a subscription;
  * the webhook grants only a session Stripe says is paid, in USD, for
    exactly the package's price, and grants once however often Stripe
    delivers it;
  * the tokens land in the bucket that never resets and the package's coach
    reviews in their own never-resetting bucket;
  * nothing renews: the period no longer rolls, so the free grant lands once.
"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace
from unittest import mock

import pytest

from services import token_account as ta
from services import token_packages as tp
from services.token_prices import TIERS

ROOT = pathlib.Path(__file__).resolve().parents[1]
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
                                  "tier": "coaching", "kind": tp.PACKAGE_KIND}


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


def test_the_webhook_grants_packages_and_nothing_else():
    """N48.3 Q13 A: the subscription, arc-checkout and credit-pack paths are
    gone; a package is the only thing the webhook applies."""
    source = (ROOT / "routes/internal_webhooks.py").read_text()
    body = source[source.index("def stripe_checkout_webhook("):]
    end = body.find("@internal_webhooks_bp.route")
    body = body if end < 0 else body[:end]
    assert "webhook_reply" in body
    for retired in ("apply_subscription_event", "apply_completed_arc_checkout",
                    "apply_paid_checkout_session_credits"):
        assert retired not in body, retired


# ── the grant ───────────────────────────────────────────────────────────

class _Query:
    def __init__(self, db, op, payload=None):
        self.db, self.op, self.payload, self.filters = db, op, payload, []

    def select(self, *_a, **_k):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
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


# ── nothing renews ──────────────────────────────────────────────────────
