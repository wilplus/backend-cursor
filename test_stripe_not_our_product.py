"""willab — "is this sale even ours?", and selling a tier so renewals survive.

WHY THESE TESTS EXIST

The Stripe endpoint receives EVERY checkout and subscription event on the
account, including sales of products that have nothing to do with willab. Both
handlers used to check the user id BEFORE looking at the price, so a foreign
sale returned 400 / logged ERROR — and a 400 tells Stripe to RETRY. Live
evidence 2026-07-31: two unrelated Payment Link sales retrying for days as
failed deliveries. The noise is not the real cost; the real cost is that a
GENUINE willab payment failing gets buried among them and nobody notices.

WHAT IS PINNED:
  * a foreign sale is acked 200 and never retried;
  * a willab sale with no user id is STILL a loud 400 — that failure must stay
    visible, because it is money in with no tokens out;
  * intersection, not "all prices map" — a mixed cart containing one of our
    prices is OURS and misconfigured, and must not be silently ignored;
  * ⭐ the tier checkout writes user_id into subscription_data.metadata, not
    only session metadata. This is THE load-bearing assertion in the file: get
    it wrong and checkout still works, the first payment still lands, and every
    RENEWAL from month two silently grants nothing.

Run: python3 -m unittest test_stripe_not_our_product
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

_ORIG_DB = None


def setUpModule():
    global _ORIG_DB
    _ORIG_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_DB is not None:
        sys.modules["services.db"] = _ORIG_DB
    else:
        sys.modules.pop("services.db", None)


OURS = "price_ours"
FOREIGN = "price_someone_elses"
CREDITS_MAP = '{"price_ours": 25}'
TIER_MAP = '{"price_starter":"starter","price_pro":"pro"}'


class _Cfg:
    STRIPE_SECRET_KEY = "sk_test_x"
    STRIPE_CHECKOUT_PRICE_CREDITS_JSON = CREDITS_MAP
    STRIPE_PRICE_TIER_JSON = TIER_MAP
    FRONTEND_URL = "https://www.willpowerlab.com"


def _session(prices, user_id=None, paid=True):
    return {
        "id": "cs_test_1",
        "payment_status": "paid" if paid else "unpaid",
        "mode": "payment",
        "client_reference_id": user_id,
        "metadata": {},
        "line_items": {"data": [{"price": {"id": p}, "quantity": 1} for p in prices]},
    }


class ForeignCheckoutTests(unittest.TestCase):
    """A sale that isn't ours must be acked, not retried."""

    def _apply(self, session):
        from services.stripe_checkout_credits import apply_paid_checkout_session_credits
        stripe_mod = types.ModuleType("stripe")
        stripe_mod.api_key = None
        stripe_mod.checkout = types.SimpleNamespace(
            Session=types.SimpleNamespace(
                retrieve=lambda *a, **k: session,
                list_line_items=lambda *a, **k: types.SimpleNamespace(data=[]),
            ))
        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            return apply_paid_checkout_session_credits(
                "cs_test_1", auth_user_id=None, app_config=_Cfg)

    def test_foreign_sale_with_no_user_is_acked_not_retried(self):
        """THE regression. A Payment Link sale of an unrelated product has no
        willab user and never will — 400 would retry it forever."""
        res = self._apply(_session([FOREIGN]))
        self.assertTrue(res.ok)
        self.assertEqual(res.http_status, 200)
        self.assertEqual(res.payload.get("skipped"), "not_our_product")

    def test_our_sale_without_a_user_is_still_a_loud_400(self):
        """Money in, no tokens out. This must stay visible and retryable."""
        res = self._apply(_session([OURS]))
        self.assertFalse(res.ok)
        self.assertEqual(res.http_status, 400)
        self.assertEqual(res.payload.get("code"), "INVALID_SESSION")

    def test_mixed_cart_containing_one_of_ours_is_ours(self):
        """Intersection, not 'all prices map'. A cart with our price plus an
        unmapped extra is a real misconfiguration — silently ignoring it would
        drop a paying customer's credits."""
        res = self._apply(_session([OURS, FOREIGN], user_id="u1"))
        self.assertFalse(res.ok, "mixed cart must not be treated as foreign")
        self.assertEqual(res.payload.get("code"), "UNMAPPED_CHECKOUT")

    def test_unpaid_session_short_circuits_before_any_of_this(self):
        res = self._apply(_session([OURS], paid=False))
        self.assertTrue(res.ok)
        self.assertEqual(res.payload.get("skipped"), "not_paid")


class CreditsRetiredTests(unittest.TestCase):
    """Turning credits off must be a config change, not an outage.

    Founder 2026-07-31: the app drops credits and keeps tokens. The day
    STRIPE_CHECKOUT_PRICE_CREDITS_JSON is unset, this path used to return 500 —
    and a 500 tells Stripe to RETRY. Every checkout.session.completed on the
    account would then retry for three days and mark the endpoint failing,
    INCLUDING the one that every token-tier subscription fires. That is the
    storm #302 exists to prevent, and its cost is not noise: a genuine payment
    failure gets buried in it.

    So: always ack, and let the log level carry the difference.
    """

    def _apply(self, cfg, session=None):
        from services.stripe_checkout_credits import apply_paid_checkout_session_credits
        stripe_mod = types.ModuleType("stripe")
        stripe_mod.api_key = None
        retrieved = {"n": 0}

        def _retrieve(*_a, **_k):
            retrieved["n"] += 1
            return session or _session([OURS], user_id="u1")

        stripe_mod.checkout = types.SimpleNamespace(
            Session=types.SimpleNamespace(
                retrieve=_retrieve,
                list_line_items=lambda *a, **k: types.SimpleNamespace(data=[]),
            ))
        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            res = apply_paid_checkout_session_credits(
                "cs_test_1", auth_user_id=None, app_config=cfg)
        return res, retrieved["n"]

    def test_unset_map_acks_instead_of_asking_stripe_to_retry(self):
        class _NoCredits(_Cfg):
            STRIPE_CHECKOUT_PRICE_CREDITS_JSON = ""
        res, _ = self._apply(_NoCredits)
        self.assertTrue(res.ok)
        self.assertEqual(res.http_status, 200, "a 500 here retries for three days")
        self.assertEqual(res.payload.get("skipped"), "credits_retired")

    def test_a_token_tier_subscription_survives_credits_being_retired(self):
        """THE case that made this urgent. A subscription checkout fires
        checkout.session.completed too, and it lands right here."""
        class _NoCredits(_Cfg):
            STRIPE_CHECKOUT_PRICE_CREDITS_JSON = ""
        sub_session = _session(["price_pro"], user_id="u1")
        sub_session["mode"] = "subscription"
        res, _ = self._apply(_NoCredits, sub_session)
        self.assertTrue(res.ok)
        self.assertEqual(res.http_status, 200)

    def test_retiring_credits_costs_no_stripe_api_call(self):
        """With no map, nothing arriving can be a credit sale, so there is
        nothing to look up. Retrieving anyway would spend a Stripe call on every
        checkout event on the account, forever, to learn nothing."""
        class _NoCredits(_Cfg):
            STRIPE_CHECKOUT_PRICE_CREDITS_JSON = ""
        _, retrieves = self._apply(_NoCredits)
        self.assertEqual(retrieves, 0)

    def test_a_malformed_map_is_told_apart_from_a_retired_one(self):
        """Both parse to {}, and they are not the same thing. Set-but-broken is
        a real misconfiguration and stays loud in the logs — but still acks,
        because retrying cannot fix a config error."""
        class _Broken(_Cfg):
            STRIPE_CHECKOUT_PRICE_CREDITS_JSON = "{not json"
        res, _ = self._apply(_Broken)
        self.assertTrue(res.ok)
        self.assertEqual(res.http_status, 200)
        self.assertEqual(res.payload.get("skipped"), "credits_map_unusable")

    def test_a_configured_pack_still_works_exactly_as_before(self):
        """The retirement path must not disturb the packs while they exist."""
        res, _ = self._apply(_Cfg, _session([FOREIGN]))
        self.assertTrue(res.ok)
        self.assertEqual(res.payload.get("skipped"), "not_our_product")


class ForeignSubscriptionTests(unittest.TestCase):
    def _event(self, price, user_id=None, etype="customer.subscription.created"):
        md = {"user_id": user_id} if user_id else {}
        return {"type": etype, "data": {"object": {
            "id": "sub_1", "status": "active", "metadata": md,
            "current_period_start": 1785483683,
            "items": {"data": [{"price": {"id": price}}]}}}}

    def test_foreign_subscription_is_ignored_quietly(self):
        from services.stripe_subscription_tiers import apply_subscription_event
        out = apply_subscription_event(self._event("price_gym_membership"), TIER_MAP)
        self.assertFalse(out["handled"])
        self.assertEqual(out["reason"], "not_a_willab_tier")

    def test_our_tier_without_a_user_still_reports_missing_user_id(self):
        """This is the bare-Payment-Link renewal failure. It must stay loud."""
        from services.stripe_subscription_tiers import apply_subscription_event
        out = apply_subscription_event(self._event("price_pro"), TIER_MAP)
        self.assertFalse(out["handled"])
        self.assertEqual(out["reason"], "missing_user_id")

    def test_cancellation_of_a_foreign_subscription_does_not_downgrade_anyone(self):
        """Ordering guard: the deleted branch now sits AFTER the tier check, so
        cancelling an unrelated product can never flip a willab user to free."""
        from services.stripe_subscription_tiers import apply_subscription_event
        out = apply_subscription_event(
            self._event("price_gym_membership", user_id="u1",
                        etype="customer.subscription.deleted"), TIER_MAP)
        self.assertFalse(out["handled"])
        self.assertEqual(out["reason"], "not_a_willab_tier")


class TierCheckoutTests(unittest.TestCase):
    def _create(self, tier, capture):
        from services.tier_checkout import create_tier_checkout_session
        stripe_mod = types.ModuleType("stripe")
        stripe_mod.api_key = None

        def _create_session(**kwargs):
            capture.update(kwargs)
            return {"id": "cs_live_1", "url": "https://checkout.stripe.com/x"}

        stripe_mod.checkout = types.SimpleNamespace(
            Session=types.SimpleNamespace(create=_create_session))
        with patch.dict(sys.modules, {"stripe": stripe_mod}):
            return create_tier_checkout_session(
                user_id="user-123", tier=tier, app_config=_Cfg)

    def test_user_id_is_written_onto_the_SUBSCRIPTION_not_just_the_session(self):
        """⭐ THE assertion. client_reference_id and session metadata do NOT
        reach the Subscription object, so without subscription_data.metadata
        every renewal from month two arrives unattributable and grants zero —
        while checkout and the first payment look perfectly fine."""
        cap: dict = {}
        res = self._create("pro", cap)
        self.assertTrue(res.ok)
        sub_meta = (cap.get("subscription_data") or {}).get("metadata") or {}
        self.assertEqual(sub_meta.get("user_id"), "user-123",
                         "renewals will grant nothing without this")
        self.assertEqual(cap.get("mode"), "subscription")
        self.assertEqual(cap["line_items"][0]["price"], "price_pro")
        # and the session-level copies, for checkout.session.completed
        self.assertEqual(cap.get("client_reference_id"), "user-123")
        self.assertEqual((cap.get("metadata") or {}).get("user_id"), "user-123")

    def test_free_is_not_purchasable(self):
        """A $0 subscription is not a product; free is the default state."""
        res = self._create("free", {})
        self.assertFalse(res.ok)
        self.assertEqual(res.payload["code"], "INVALID_TIER")

    def test_unknown_tier_refused(self):
        res = self._create("platinum", {})
        self.assertFalse(res.ok)
        self.assertEqual(res.payload["code"], "INVALID_TIER")

    def test_tier_with_no_mapped_price_is_a_config_error_not_a_crash(self):
        from services.tier_checkout import create_tier_checkout_session

        class _NoMax(_Cfg):
            STRIPE_PRICE_TIER_JSON = '{"price_starter":"starter"}'
        res = create_tier_checkout_session(user_id="u1", tier="max",
                                           app_config=_NoMax)
        self.assertFalse(res.ok)
        self.assertEqual(res.payload["code"], "MISCONFIGURED")

    def test_checkout_reads_the_same_env_var_the_webhook_reads(self):
        """One source of truth: a checkout must never offer a price the webhook
        would then fail to recognise."""
        with open("services/tier_checkout.py") as fh:
            src = fh.read()
        self.assertIn("STRIPE_PRICE_TIER_JSON", src)
        self.assertIn("parse_price_tier_map", src)


class SecondSubscriptionTests(unittest.TestCase):
    """You cannot buy a plan you are already paying for.

    Stripe will open a SECOND subscription for a customer who already has one
    and then bill both, monthly, until somebody notices. A user who taps "Pro"
    on a page that has not refreshed, or who wants to move Starter → Pro, must
    be routed to the billing portal — which SWITCHES the existing subscription
    rather than stacking another beside it.
    """

    def _create(self, tier, account):
        """`account` is what GET /v2/tokens/balance would return — stubbed at
        get_account, not at plan_state, because the guard is specified as
        "refuse what the user was actually shown"."""
        from services.tier_checkout import create_tier_checkout_session
        stripe_mod = types.ModuleType("stripe")
        stripe_mod.api_key = None
        stripe_mod.checkout = types.SimpleNamespace(
            Session=types.SimpleNamespace(
                create=lambda **kw: {"id": "cs_1", "url": "https://x"}))
        with patch.dict(sys.modules, {"stripe": stripe_mod}), \
                patch("services.token_account.get_account", return_value=account):
            return create_tier_checkout_session(
                user_id="user-123", tier=tier, app_config=_Cfg)

    @staticmethod
    def _acct(**plan):
        return {"balance": 1, "tier": plan.get("tier", "free"), "plan": plan}

    def test_same_tier_is_a_calm_no_op_not_a_second_charge(self):
        res = self._create("pro", self._acct(managed=True, tier="pro"))
        self.assertFalse(res.ok)
        self.assertEqual(res.http_status, 409)
        self.assertEqual(res.payload["code"], "ALREADY_ON_TIER")

    def test_a_different_tier_is_sent_to_the_portal_to_SWITCH(self):
        """Not a refusal to change plan — a refusal to change it by buying a
        second one. The portal is where a switch happens."""
        res = self._create("pro", self._acct(managed=True, tier="starter"))
        self.assertFalse(res.ok)
        self.assertEqual(res.http_status, 409)
        self.assertEqual(res.payload["code"], "MANAGE_EXISTING")

    def test_the_guard_reads_the_tier_the_user_actually_holds(self):
        """Regression. Asking plan_state for the plan WITHOUT the caller's tier
        returns the 'free' default, so every managed user looks like a tier
        mismatch: ALREADY_ON_TIER could never fire and re-tapping your own plan
        reported MANAGE_EXISTING instead."""
        res = self._create("starter", self._acct(managed=True, tier="starter"))
        self.assertEqual(res.payload["code"], "ALREADY_ON_TIER")

    def test_an_unmanaged_tier_still_sells(self):
        """Everyone on free — the whole point of the endpoint."""
        res = self._create("pro", self._acct(managed=False, tier="free"))
        self.assertTrue(res.ok)
        self.assertEqual(res.payload["tier"], "pro")

    def test_an_unreadable_account_sells_rather_than_blocking_the_sale(self):
        """Refuse only on POSITIVE knowledge of a live subscription. An
        unreadable account, and every database where add_subscription_state.sql
        has not run yet, must not become 'nobody can subscribe'."""
        self.assertTrue(self._create("pro", None).ok)
        self.assertTrue(self._create("pro", {}).ok)


class BillingPortalTests(unittest.TestCase):
    """Cancel, switch, change card — handed to Stripe rather than rebuilt.

    Nothing here decides an entitlement. Whatever the user does in the portal
    comes back as customer.subscription.updated/deleted and is applied by
    apply_subscription_event, which is the only writer of tiers.
    """

    def _open(self, customer_id, capture=None):
        from services.tier_checkout import create_billing_portal_session
        stripe_mod = types.ModuleType("stripe")
        stripe_mod.api_key = None

        def _create(**kwargs):
            if capture is not None:
                capture.update(kwargs)
            return {"url": "https://billing.stripe.com/p/session/x"}

        stripe_mod.billing_portal = types.SimpleNamespace(
            Session=types.SimpleNamespace(create=_create))
        with patch.dict(sys.modules, {"stripe": stripe_mod}), \
                patch("services.token_account.stripe_customer_id",
                      return_value=customer_id):
            return create_billing_portal_session(user_id="user-123",
                                                 app_config=_Cfg)

    def test_opens_against_the_stored_customer(self):
        cap: dict = {}
        res = self._open("cus_1", cap)
        self.assertTrue(res.ok)
        self.assertEqual(cap.get("customer"), "cus_1")
        self.assertTrue(res.payload["portal_url"].startswith("https://"))

    def test_no_customer_is_nothing_to_manage_not_an_error_state(self):
        """404 NO_SUBSCRIPTION means 'render upgrade instead' — it is not a
        failure to show anybody."""
        res = self._open(None)
        self.assertFalse(res.ok)
        self.assertEqual(res.http_status, 404)
        self.assertEqual(res.payload["code"], "NO_SUBSCRIPTION")

    def test_the_portal_url_is_never_baked_into_the_balance_read(self):
        """Portal sessions expire, and GET /v2/tokens/balance is the most-read
        endpoint in the wallet. Minting a URL there would ship dead links and
        make a Stripe outage read to the user as a missing balance — which
        token_account works hard to avoid. The balance carries a BOOLEAN
        (plan.manage_available); the URL is minted on the click."""
        with open("services/token_account.py") as fh:
            account_src = fh.read()
        self.assertNotIn("billing_portal", account_src)
        self.assertIn("manage_available", account_src)


if __name__ == "__main__":
    unittest.main()
