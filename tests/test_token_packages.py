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
from datetime import timedelta
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


@pytest.mark.parametrize("package", ["free", "pro", "max", "", "nope"])
def test_only_a_package_on_sale_can_be_bought(package):
    result, create = _create(package)
    assert (result.http_status, result.payload["code"]) == (400, "INVALID_TIER")
    create.assert_not_called()


def test_the_route_opens_a_package_not_a_subscription():
    source = (ROOT / "routes/token_routes.py").read_text()
    route = source[source.index("def tokens_checkout("):source.index("def tokens_portal(")]
    assert "create_package_checkout_session" in route
    assert "create_tier_checkout_session" not in route


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
    body = body[:body.index("@internal_webhooks_bp.route")]
    assert "webhook_reply" in body
    for retired in ("apply_subscription_event", "apply_completed_arc_checkout",
                    "apply_paid_checkout_session_credits"):
        assert retired not in body, retired


def _post_webhook(app_client, event):
    from routes import internal_webhooks as hooks
    with mock.patch.object(hooks.config, "STRIPE_WEBHOOK_SECRET", "whsec", create=True), \
            mock.patch.object(hooks.config, "STRIPE_SECRET_KEY", "sk_test", create=True), \
            mock.patch("stripe.Webhook.construct_event", return_value=event), \
            mock.patch("services.token_packages.webhook_reply",
                       side_effect=AssertionError("not a package")):
        return app_client.post("/v2/internal/stripe/webhook", data=b"{}",
                               headers={"Stripe-Signature": "t=1,v1=x"})


@pytest.mark.parametrize("etype", ["customer.subscription.created",
                                   "customer.subscription.updated",
                                   "customer.subscription.deleted"])
def test_a_subscription_event_is_acked_and_applies_nothing(app_client, etype):
    resp = _post_webhook(app_client, {"type": etype, "data": {"object": {
        "id": "sub_1", "metadata": {"user_id": "u1"}}}})
    assert resp.status_code == 200
    assert resp.get_json() == {"received": True}


@pytest.mark.parametrize("metadata", [{"arc_id": "arc-1", "user_id": "u1"},
                                      {"user_id": "u1"}, {}])
def test_an_arc_or_credit_checkout_is_acked_and_grants_nothing(app_client, metadata):
    resp = _post_webhook(app_client, {"type": "checkout.session.completed",
                                      "data": {"object": {"id": "cs_9",
                                                          "metadata": metadata}}})
    assert resp.status_code == 200
    assert resp.get_json() == {"received": True, "granted": False,
                               "reason": "not_a_package"}


def test_the_billing_portal_is_gone(app_client, stub_verified_user):
    stub_verified_user("u1")
    resp = app_client.post("/v2/tokens/portal", json={},
                           headers={"Authorization": "Bearer t"})
    assert resp.status_code == 410
    assert resp.get_json()["code"] == "GONE"


def test_the_balance_carries_no_plan(db):
    assert "plan" not in ta.get_account("u1", database=db)


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


def test_the_package_lands_in_the_never_resetting_buckets(db):
    out = ta.package_grant("u1", tokens=150_000, coach_reviews=3, ref_id="cs_1",
                           package="coaching", database=db)
    assert out == {"ok": True, "reason": ""}
    assert db.row["bonus_balance"] == 150_000
    assert db.row["coach_review_credits"] == 3
    assert db.row["token_balance"] == 12_000
    assert db.ledger == [{"delta": 150_000, "action": ta.PACKAGE_PURCHASE,
                          "ref_id": "cs_1", "tier": "coaching"}]
    account = ta.get_account("u1", database=db)
    assert account["balance"] == 162_000
    assert account["coach_reviews"]["allowed"] == 3


def test_a_second_delivery_grants_nothing(db):
    for _ in range(2):
        ta.package_grant("u1", tokens=150_000, coach_reviews=0, ref_id="cs_1",
                         package="practice", database=db)
    assert db.row["bonus_balance"] == 150_000
    assert len(db.ledger) == 1


def test_two_packages_add_up(db):
    ta.package_grant("u1", tokens=150_000, coach_reviews=3, ref_id="cs_1",
                     package="coaching", database=db)
    ta.package_grant("u1", tokens=400_000, coach_reviews=8, ref_id="cs_2",
                     package="intensive", database=db)
    assert (db.row["bonus_balance"], db.row["coach_review_credits"]) == (550_000, 11)


# ── nothing renews ──────────────────────────────────────────────────────

def test_the_period_no_longer_rolls(db, monkeypatch):
    assert ta.PERIOD_RESET_ENABLED is False
    later = ta._parse_ts(db.row["period_start"]) + timedelta(days=400)
    monkeypatch.setattr(ta, "_now", lambda: later)
    db.row["token_balance"] = 5
    account = ta.get_account("u1", database=db)
    assert account["monthly_balance"] == 5  # not re-granted
    assert account["period_ends_at"] is None
    assert db.ledger == []
