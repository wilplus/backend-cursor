"""Apply homework credits from a paid Stripe Checkout Session (webhook + student claim)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from services.db import db
from services.stripe_checkout_webhook import (
    _line_items_data,
    checkout_user_id,
    parse_price_credits_map,
    total_credits_for_checkout_session,
)

logger = logging.getLogger(__name__)


def _session_field(session: Any, key: str, default: Any = None) -> Any:
    if isinstance(session, dict):
        return session.get(key, default)
    return getattr(session, key, default)


@dataclass
class CheckoutCreditsApplyResult:
    ok: bool
    http_status: int
    payload: dict

    @classmethod
    def error(cls, status: int, code: str, message: str, **extra: Any) -> CheckoutCreditsApplyResult:
        body: dict = {"code": code, "error": message}
        body.update(extra)
        return cls(False, status, body)

    @classmethod
    def success(cls, status: int, **body: Any) -> CheckoutCreditsApplyResult:
        return cls(True, status, dict(body))


def apply_paid_checkout_session_credits(
    checkout_session_id: str,
    *,
    auth_user_id: str | None,
    app_config: object,
) -> CheckoutCreditsApplyResult:
    """
    Idempotent credit grant for a Checkout Session (same rules as the Stripe webhook).
    If auth_user_id is set, the session must carry that Supabase user id (metadata / client_reference_id).
    """
    import stripe

    api_key = (getattr(app_config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        return CheckoutCreditsApplyResult.error(503, "DISABLED", "STRIPE_SECRET_KEY not configured")

    sid = (checkout_session_id or "").strip()
    if not sid:
        return CheckoutCreditsApplyResult.error(400, "INVALID_INPUT", "checkout_session_id is required")

    price_map = parse_price_credits_map(getattr(app_config, "STRIPE_CHECKOUT_PRICE_CREDITS_JSON", "") or "")
    if not price_map:
        logger.error("stripe checkout credits: STRIPE_CHECKOUT_PRICE_CREDITS_JSON missing or empty")
        return CheckoutCreditsApplyResult.error(500, "MISCONFIGURED", "STRIPE_CHECKOUT_PRICE_CREDITS_JSON not configured")

    stripe.api_key = api_key
    try:
        full = stripe.checkout.Session.retrieve(sid, expand=["line_items.data.price"])
    except Exception as e:
        logger.warning("stripe Session.retrieve failed: %s", e)
        return CheckoutCreditsApplyResult.error(500, "STRIPE_API_ERROR", str(e))

    if _session_field(full, "payment_status") != "paid":
        return CheckoutCreditsApplyResult.success(200, skipped="not_paid")

    if _session_field(full, "mode") != "payment":
        return CheckoutCreditsApplyResult.success(200, skipped="not_payment_mode")

    session_user = checkout_user_id(full)
    if not session_user:
        return CheckoutCreditsApplyResult.error(
            400,
            "INVALID_SESSION",
            "Set client_reference_id or metadata.user_id to Supabase user id on Checkout Session",
        )

    if auth_user_id and session_user.strip().lower() != auth_user_id.strip().lower():
        return CheckoutCreditsApplyResult.error(403, "FORBIDDEN", "Checkout session does not belong to this account")

    db_user_id = auth_user_id.strip() if auth_user_id else session_user.strip()

    line_data = _line_items_data(full)
    if not line_data:
        try:
            li = stripe.checkout.Session.list_line_items(sid, expand=["data.price"], limit=100)
            line_data = list(li.data) if li and getattr(li, "data", None) else []
        except Exception as e:
            logger.warning("stripe list_line_items failed session=%s err=%s", sid, e)
            line_data = []
    if not line_data:
        logger.error("stripe checkout credits: no line items session=%s", sid)
        return CheckoutCreditsApplyResult.error(400, "NO_LINE_ITEMS", "Checkout session has no line items to map")

    total, map_err = total_credits_for_checkout_session({"line_items": {"data": line_data}}, price_map)
    if map_err or total is None:
        logger.error("stripe checkout credits: mapping failed session=%s detail=%s", sid, map_err)
        return CheckoutCreditsApplyResult.error(400, "UNMAPPED_CHECKOUT", map_err or "mapping failed")

    try:
        claimed = db.stripe_checkout_grant_claim(sid)
    except Exception as e:
        logger.warning("stripe_checkout_grant_claim error: %s", e)
        return CheckoutCreditsApplyResult.error(500, "DB_ERROR", "idempotency claim failed")

    if not claimed:
        details = db.v2_get_student_details(db_user_id) or {}
        cur = details.get("credits")
        if cur is None:
            cur = 15
        logger.info("stripe checkout credits duplicate session=%s user=%s credits=%s", sid, db_user_id, cur)
        return CheckoutCreditsApplyResult.success(200, credits=int(cur), duplicate=True, delta_applied=0)

    new_bal = db.v2_increment_student_credits(db_user_id, total)
    if new_bal is None:
        db.stripe_checkout_grant_release(sid)
        logger.error("stripe checkout credits: increment failed user=%s session=%s", db_user_id, sid)
        return CheckoutCreditsApplyResult.error(500, "V2_ERROR", "Could not update credits")

    logger.info(
        "stripe checkout credits applied user_id=%s session=%s delta=%s new_credits=%s",
        db_user_id,
        sid,
        total,
        new_bal,
    )
    return CheckoutCreditsApplyResult.success(
        200,
        credits=int(new_bal),
        duplicate=False,
        delta_applied=int(total),
        user_id=db_user_id,
    )
