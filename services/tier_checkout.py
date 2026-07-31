"""willab — start a subscription for a token tier.

THE REASON THIS EXISTS RATHER THAN A PAYMENT LINK
-------------------------------------------------
A bare Stripe Payment Link cannot sell these tiers, and the failure is delayed
and expensive: you can append ``?client_reference_id=<uid>`` to a Payment Link
and the FIRST payment attributes fine — but ``client_reference_id`` lands on the
**Checkout Session**, and it never reaches the **Subscription** object. Every
later ``customer.subscription.updated`` (i.e. every monthly renewal) arrives with
no user on it, hits the ``missing_user_id`` branch in
services/stripe_subscription_tiers.py, and grants nothing. The customer pays
month two and gets zero tokens.

So the session is created here, server-side, with the user id written into BOTH
places:

  * ``metadata.user_id``                   — on the Checkout Session
  * ``subscription_data.metadata.user_id`` — copied onto the Subscription, and
                                             the ONLY one renewals carry

Getting the second one wrong is the single most likely way this whole billing
path breaks silently, which is why it is asserted by test rather than trusted.

Grants happen in the webhook, never here. This function only opens the door;
``apply_subscription_event`` is what decides anyone got anything, so an
abandoned checkout costs nothing and a replayed one grants once.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)


@dataclass
class TierCheckoutResult:
    ok: bool
    http_status: int
    payload: dict = field(default_factory=dict)

    @classmethod
    def success(cls, url: str, session_id: str, tier: str) -> "TierCheckoutResult":
        return cls(True, 200, {"checkout_url": url, "checkout_session_id": session_id,
                               "tier": tier})

    @classmethod
    def error(cls, status: int, code: str, message: str) -> "TierCheckoutResult":
        return cls(False, status, {"code": code, "error": message})


def _price_for_tier(raw_price_tier_json: str, tier: str) -> Optional[str]:
    """Reverse the {price_id: tier} map. Deliberately reuses the SAME env var
    the webhook reads, so a checkout can never offer a price the webhook would
    then fail to recognise — one source of truth, no drift."""
    from services.stripe_subscription_tiers import parse_price_tier_map
    for price_id, mapped in parse_price_tier_map(raw_price_tier_json).items():
        if mapped == tier:
            return price_id
    return None


def create_tier_checkout_session(
    *,
    user_id: str,
    tier: str,
    app_config: Any,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
    customer_email: Optional[str] = None,
) -> TierCheckoutResult:
    """Open a Stripe Checkout Session for a recurring token tier."""
    import stripe

    from services.token_prices import TIERS

    tier = (tier or "").strip().lower()
    if tier not in TIERS or tier == "free":
        # 'free' is not purchasable — it is the default state, granted by the
        # period roll, and offering it for sale would create a $0 subscription.
        return TierCheckoutResult.error(
            400, "INVALID_TIER",
            f"tier must be one of: {', '.join(t for t in TIERS if t != 'free')}")

    if not (user_id or "").strip():
        return TierCheckoutResult.error(400, "INVALID_INPUT", "user_id is required")

    api_key = (getattr(app_config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        return TierCheckoutResult.error(503, "DISABLED", "STRIPE_SECRET_KEY not configured")

    raw_map = getattr(app_config, "STRIPE_PRICE_TIER_JSON", "") or ""
    price_id = _price_for_tier(raw_map, tier)
    if not price_id:
        logger.error("tier checkout: no price mapped to tier=%s in "
                     "STRIPE_PRICE_TIER_JSON", tier)
        return TierCheckoutResult.error(
            500, "MISCONFIGURED",
            f"No Stripe price mapped to tier '{tier}' in STRIPE_PRICE_TIER_JSON")

    # ── Do they already have one? ────────────────────────────────────
    #
    # Stripe will happily open a SECOND subscription for someone who already
    # has one, and then bill both. A plan change belongs in the billing portal,
    # which switches the existing subscription instead of stacking another.
    #
    # Refused only on POSITIVE knowledge of a live subscription: an unreadable
    # account (or a database where add_subscription_state.sql has not run yet)
    # falls through and sells, which is the pre-existing behaviour. Blocking a
    # purchase over a failed lookup is the worse failure of the two.
    #
    # Read through get_account, not plan_state directly. That is byte-for-byte
    # the object the FE was shown on /v2/tokens/balance, so the guard and the
    # button it rendered agree by construction — and plan_state alone does not
    # know the caller's tier, which would make every managed user look like a
    # mismatch and turn ALREADY_ON_TIER into dead code.
    from services import token_account as ta
    plan = (ta.get_account(user_id) or {}).get("plan") or {}
    if plan.get("managed"):
        if plan.get("tier") == tier:
            return TierCheckoutResult.error(
                409, "ALREADY_ON_TIER",
                f"Already subscribed to {tier}.")
        return TierCheckoutResult.error(
            409, "MANAGE_EXISTING",
            "An active subscription already exists — change it through the "
            "billing portal so it switches instead of stacking a second one.")

    base = (getattr(app_config, "FRONTEND_URL", None) or
            "https://www.willpowerlab.com").rstrip("/")
    success = success_url or f"{base}/account?subscribed=1"
    cancel = cancel_url or f"{base}/account"

    stripe.api_key = api_key
    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            client_reference_id=str(user_id),
            # On the SESSION — used by checkout.session.completed.
            metadata={"user_id": str(user_id), "tier": tier, "kind": "token_tier"},
            # On the SUBSCRIPTION — the only copy that survives onto renewals.
            # Removing this does not break checkout; it breaks month two.
            subscription_data={
                "metadata": {"user_id": str(user_id), "tier": tier,
                             "kind": "token_tier"},
            },
            success_url=success,
            cancel_url=cancel,
            **({"customer_email": customer_email} if customer_email else {}),
        )
    except Exception as e:
        logger.warning("create_tier_checkout_session failed user=%s tier=%s: %s",
                       user_id, tier, e)
        return TierCheckoutResult.error(502, "STRIPE_API_ERROR", str(e))

    url = session.get("url") if isinstance(session, dict) else getattr(session, "url", None)
    sid = session.get("id") if isinstance(session, dict) else getattr(session, "id", None)
    logger.info("tier checkout opened user=%s tier=%s session=%s", user_id, tier, sid)
    return TierCheckoutResult.success(str(url or ""), str(sid or ""), tier)


def create_billing_portal_session(
    *,
    user_id: str,
    app_config: Any,
    return_url: Optional[str] = None,
) -> TierCheckoutResult:
    """Open a Stripe billing-portal session: cancel, switch tier, change card.

    WHY THIS IS ITS OWN ENDPOINT AND NOT A FIELD ON THE BALANCE
    -----------------------------------------------------------
    The FE asked for a `manage_url` inside GET /v2/tokens/balance. It cannot
    live there, for two reasons that both bite in production:

      * portal sessions EXPIRE. A URL minted into a balance payload the FE
        renders once and keeps is a dead link by the time anyone clicks it;
      * it would put a synchronous Stripe API call inside the most-read
        endpoint in the wallet, so a Stripe blip would read to the user as
        "your balance is unavailable". `token_account` goes to some length to
        keep the balance readable when things around it fail; this would hand
        that away for a convenience.

    So the balance carries `plan.manage_available` (a boolean the FE renders a
    button from) and the URL is minted here, on the click — the same shape the
    checkout flow already uses.

    EVERYTHING THE PORTAL DOES ARRIVES BACK AS A WEBHOOK. Cancellations and
    tier switches made in there come home as `customer.subscription.updated`
    /`.deleted` and are applied by `apply_subscription_event`. Nothing about a
    user's entitlement is decided by this function.
    """
    import stripe

    from services import token_account as ta

    if not (user_id or "").strip():
        return TierCheckoutResult.error(400, "INVALID_INPUT", "user_id is required")

    api_key = (getattr(app_config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        return TierCheckoutResult.error(503, "DISABLED", "STRIPE_SECRET_KEY not configured")

    customer_id = ta.stripe_customer_id(str(user_id))
    if not customer_id:
        # Never bought anything (or the migration has not run). Not an error the
        # user caused — the FE renders upgrade instead of manage.
        return TierCheckoutResult.error(
            404, "NO_SUBSCRIPTION",
            "No Stripe customer for this user — nothing to manage yet.")

    base = (getattr(app_config, "FRONTEND_URL", None) or
            "https://www.willpowerlab.com").rstrip("/")
    stripe.api_key = api_key
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url or f"{base}/account",
        )
    except Exception as e:
        logger.warning("create_billing_portal_session failed user=%s: %s",
                       user_id, e)
        return TierCheckoutResult.error(502, "STRIPE_API_ERROR", str(e))

    url = session.get("url") if isinstance(session, dict) else getattr(session, "url", None)
    logger.info("billing portal opened user=%s customer=%s", user_id, customer_id)
    return TierCheckoutResult(True, 200, {"portal_url": str(url or "")})
