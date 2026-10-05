"""willab — buy a token package, once (contract §8; founder 2026-10-05,
"Packages"; decisions log N44).

THE MODEL. Every purchase is a one-time package of tokens and any coach
reviews it includes. Balances stay until spent and never renew; there are no
subscriptions, billing periods or monthly plans (contract §8, items 48-50).
Until 5 October the buy button opened a monthly Stripe subscription while the
screen said "one-time purchase"; this module replaces that door.

HOW A PURCHASE LANDS. ``create_package_checkout_session`` opens a Stripe
Checkout Session in ``payment`` mode. The price is written inline from
``services.token_prices.TIERS`` (``price_data``), so the amount charged is the
published price by construction and no Stripe dashboard price has to match it.
The webhook then calls ``apply_completed_package_checkout``: it re-reads the
session from Stripe, checks it is paid, in USD, for exactly this package's
price, and only then grants. Nothing is granted here, so an abandoned
checkout costs nothing.

WHERE THE TOKENS GO. Into ``bonus_balance``, the bucket that never resets,
and the package's coach reviews into ``coach_review_credits``; both through
``services.token_account.package_grant``, idempotent on the Checkout Session
id, so a webhook Stripe delivers twice grants once.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.tier_checkout import TierCheckoutResult

logger = logging.getLogger(__name__)

#: The metadata ``kind`` that routes a completed checkout here.
PACKAGE_KIND = "token_package"


def _sellable() -> tuple[str, ...]:
    from services.token_prices import SOLD_TIERS
    return tuple(t for t in SOLD_TIERS if t != "free")


def package_spec(package: Optional[str]) -> Optional[dict]:
    """``{"package", "tokens", "coach_reviews", "usd", "cents"}`` for a
    package on sale, else None. A retired tier is not a package."""
    from services.token_prices import TIERS
    key = (package or "").strip().lower()
    if key not in _sellable():
        return None
    row = TIERS[key]
    return {
        "package": key,
        "tokens": int(row["tokens"]),
        "coach_reviews": int(row["coach_reviews"]),
        "usd": int(row["usd"]),
        "cents": int(row["usd"]) * 100,
    }


def _line_item_name(spec: dict) -> str:
    """What Stripe's page shows: the package and its tokens, in the words the
    purchase screen's chip already uses ("Practice · 150,000 tokens")."""
    return f"{spec['package'].capitalize()} · {spec['tokens']:,} tokens"


def create_package_checkout_session(
    *,
    user_id: str,
    package: str,
    app_config: Any,
    success_url: Optional[str] = None,
    cancel_url: Optional[str] = None,
    customer_email: Optional[str] = None,
) -> TierCheckoutResult:
    """Open a one-time Stripe Checkout Session for a token package."""
    import stripe

    spec = package_spec(package)
    if spec is None:
        return TierCheckoutResult.error(
            400, "INVALID_TIER",
            f"tier must be one of: {', '.join(_sellable())}")
    if not (user_id or "").strip():
        return TierCheckoutResult.error(400, "INVALID_INPUT", "user_id is required")
    api_key = (getattr(app_config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        return TierCheckoutResult.error(503, "DISABLED", "STRIPE_SECRET_KEY not configured")

    base = (getattr(app_config, "FRONTEND_URL", None) or
            "https://www.willpowerlab.com").rstrip("/")
    metadata = {"user_id": str(user_id), "package": spec["package"],
                "tier": spec["package"], "kind": PACKAGE_KIND}
    stripe.api_key = api_key
    try:
        params: dict[str, Any] = {
            "mode": "payment",
            "line_items": [{
                "price_data": {
                    "currency": "usd",
                    "unit_amount": spec["cents"],
                    "product_data": {"name": _line_item_name(spec)},
                },
                "quantity": 1,
            }],
            "client_reference_id": str(user_id),
            "metadata": metadata,
            "payment_intent_data": {"metadata": metadata},
            # A receipt the buyer keeps, and the record the five-year rule
            # (retention schedule v1.3) is about.
            "invoice_creation": {"enabled": True},
            "success_url": success_url or f"{base}/account?subscribed=1",
            "cancel_url": cancel_url or f"{base}/account",
        }
        if customer_email:
            params["customer_email"] = customer_email
        session = stripe.checkout.Session.create(**params)
    except Exception as e:
        logger.warning("create_package_checkout_session failed user=%s "
                       "package=%s: %s", user_id, spec["package"], e,
                       exc_info=True)
        return TierCheckoutResult.error(502, "STRIPE_API_ERROR", str(e))

    url = session.get("url") if isinstance(session, dict) else getattr(session, "url", None)
    sid = session.get("id") if isinstance(session, dict) else getattr(session, "id", None)
    logger.info("package checkout opened user=%s package=%s session=%s",
                user_id, spec["package"], sid)
    return TierCheckoutResult.success(str(url or ""), str(sid or ""), spec["package"])


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def apply_completed_package_checkout(session_id: str, app_config: Any, *,
                                     database=None) -> TierCheckoutResult:
    """Grant a paid package from its Checkout Session. Idempotent.

    Answers 200 for anything Stripe should not retry (not ours, not paid,
    the wrong amount: logged for us to fix), and 500 only when the grant
    itself could not be written, so Stripe delivers again."""
    import stripe

    api_key = (getattr(app_config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        return TierCheckoutResult.error(503, "DISABLED", "STRIPE_SECRET_KEY not configured")
    stripe.api_key = api_key
    try:
        session = stripe.checkout.Session.retrieve(str(session_id))
    except Exception as e:
        logger.warning("package checkout: retrieve failed session=%s: %s",
                       session_id, e, exc_info=True)
        return TierCheckoutResult.error(502, "STRIPE_API_ERROR", str(e))

    metadata = _get(session, "metadata") or {}
    user_id = str(_get(metadata, "user_id") or "").strip()
    spec = package_spec(_get(metadata, "package"))
    problem = None
    if _get(metadata, "kind") != PACKAGE_KIND:
        problem = "not_a_package"
    elif not user_id or spec is None:
        problem = "unknown_buyer_or_package"
    elif _get(session, "mode") != "payment":
        problem = "not_one_time"
    elif _get(session, "payment_status") != "paid":
        problem = "not_paid"
    elif (str(_get(session, "currency") or "").lower() != "usd"
          or int(_get(session, "amount_total") or -1) != spec["cents"]):
        problem = "amount_mismatch"
    if problem or spec is None:
        logger.error("package checkout not granted session=%s reason=%s",
                     session_id, problem)
        return TierCheckoutResult(True, 200, {"granted": False, "reason": problem})

    from services import token_account as ta
    outcome = ta.package_grant(
        user_id, tokens=spec["tokens"], coach_reviews=spec["coach_reviews"],
        ref_id=str(session_id), package=spec["package"], database=database)
    if not outcome.get("ok"):
        logger.error("package grant failed session=%s user=%s reason=%s",
                     session_id, user_id, outcome.get("reason"))
        return TierCheckoutResult.error(500, "GRANT_FAILED",
                                        str(outcome.get("reason") or "unknown"))
    return TierCheckoutResult(True, 200, {
        "granted": outcome.get("reason") != "already_applied",
        "package": spec["package"],
    })


def webhook_reply(session_id: str, app_config: Any) -> tuple[dict, int]:
    """The webhook's answer for a completed package checkout: the grant's
    payload (with ``received`` when it landed) and its HTTP status."""
    result = apply_completed_package_checkout(session_id, app_config)
    payload = dict(result.payload)
    if result.ok:
        payload["received"] = True
    return payload, result.http_status
