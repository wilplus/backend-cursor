"""willab — Stripe subscription events → token tiers.

Token pricing Phase 1. Founder 2026-07-28: every tier renews monthly, which
means starter ($5) and pro ($25) are SUBSCRIPTIONS, not packs. An allowance
whose remainder is deleted after 30 days is not a pack; selling it as one is how
you get chargebacks. So all three paid tiers are recurring Stripe Prices and
arrive here as subscription events, not checkout completions.

Mapping comes from ``STRIPE_PRICE_TIER_JSON`` — {price_id: tier} — deliberately
separate from the legacy ``STRIPE_CHECKOUT_PRICE_CREDITS_JSON`` (price → credit
amount), which still serves the old one-off credit packs and is untouched.

WHY THE BILLING ANCHOR MATTERS. ``current_period_start`` from Stripe becomes the
account's ``period_start``. Without that the card is charged on the 3rd while
tokens re-grant on the 17th, and every support conversation becomes "when do my
tokens come back?". Same day, one answer.

Never claws back on cancellation — they paid for the period they are in. A
deleted subscription drops the tier to free, which takes effect at the next roll.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_HANDLED = (
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
)


def parse_price_tier_map(raw: str) -> dict[str, str]:
    """{price_id: tier} from STRIPE_PRICE_TIER_JSON. Invalid JSON = empty map
    (logged), never an exception — a malformed env var must not 500 the whole
    webhook and lose unrelated events."""
    if not (raw or "").strip():
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("STRIPE_PRICE_TIER_JSON invalid JSON: %s", e)
        return {}
    if not isinstance(parsed, dict):
        logger.warning("STRIPE_PRICE_TIER_JSON must be an object")
        return {}
    out: dict[str, str] = {}
    for k, v in parsed.items():
        tier = str(v).strip().lower()
        if tier in ("free", "starter", "pro", "max"):
            out[str(k).strip()] = tier
        else:
            logger.warning("STRIPE_PRICE_TIER_JSON: unknown tier %r for %s",
                           v, k)
    return out


def is_subscription_event(event_type: Optional[str]) -> bool:
    return (event_type or "") in _HANDLED


def _user_id_from(sub: dict) -> Optional[str]:
    """Supabase user id off the subscription metadata.

    Checkout must set ``metadata.user_id`` AND ``subscription_data.metadata
    .user_id`` — the second is what lands on the subscription object itself and
    is the only one later renewal events carry."""
    md = sub.get("metadata") or {}
    for key in ("user_id", "supabase_user_id", "auth_user_id"):
        val = md.get(key)
        if val:
            return str(val).strip()
    return None


def _tier_from_items(sub: dict, price_map: dict[str, str]) -> Optional[str]:
    items = ((sub.get("items") or {}).get("data")) or []
    for item in items:
        price = (item.get("price") or {}).get("id")
        if price and price in price_map:
            return price_map[price]
    return None


def _period_start(sub: dict) -> Optional[datetime]:
    ts = sub.get("current_period_start")
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else None
    except (TypeError, ValueError, OSError):
        return None


def apply_subscription_event(event: dict, raw_price_tier_json: str, *,
                             database=None) -> dict:
    """Handle one subscription event. Returns a small payload for the webhook.

    Idempotent by construction: setting a tier is a write of an absolute state
    (tier + grant + anchor), so Stripe's at-least-once redelivery re-applies the
    same values rather than stacking grants.
    """
    from services import token_account as ta

    etype = event.get("type") or ""
    if not is_subscription_event(etype):
        return {"handled": False, "reason": "not_a_subscription_event"}

    sub = (event.get("data") or {}).get("object") or {}
    user_id = _user_id_from(sub)
    if not user_id:
        # Loud: a paid subscription we cannot attribute is money in with no
        # tokens out, and the user will notice before we do.
        logger.error("stripe subscription %s has no metadata.user_id — "
                     "cannot grant tokens (sub=%s)", etype, sub.get("id"))
        return {"handled": False, "reason": "missing_user_id"}

    if etype == "customer.subscription.deleted":
        # Downgrade only. No claw-back: they paid for this period.
        ta.set_tier(user_id, "free", ref_id=str(sub.get("id") or ""),
                    database=database)
        logger.info("stripe: subscription cancelled user=%s → free", user_id)
        return {"handled": True, "user_id": user_id, "tier": "free"}

    price_map = parse_price_tier_map(raw_price_tier_json)
    if not price_map:
        logger.error("STRIPE_PRICE_TIER_JSON not configured — subscription "
                     "event cannot be mapped to a tier")
        return {"handled": False, "reason": "price_map_unconfigured"}

    tier = _tier_from_items(sub, price_map)
    if not tier:
        logger.error("stripe subscription %s: no known price in items "
                     "(sub=%s)", etype, sub.get("id"))
        return {"handled": False, "reason": "unknown_price"}

    status = (sub.get("status") or "").strip().lower()
    if status in ("incomplete", "incomplete_expired", "unpaid"):
        # Not paid yet — granting here would hand out a month for an
        # authorisation that may never clear.
        logger.info("stripe: subscription %s status=%s — no grant yet",
                    sub.get("id"), status)
        return {"handled": False, "reason": f"status_{status}"}

    result = ta.set_tier(user_id, tier, period_start=_period_start(sub),
                         ref_id=str(sub.get("id") or ""), database=database)
    return {"handled": True, "user_id": user_id, "tier": tier,
            "granted": (result or {}).get("balance")}
