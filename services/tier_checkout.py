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
