"""Apply homework credits from a paid Stripe Checkout Session (webhook + student claim).

LEGACY, AND ON ITS WAY OUT. Founder 2026-07-31: the app is dropping credits and
keeping tokens (services/token_account.py). This path still serves the old
one-off packs while they exist, but it is written so that RETIRING them is a
config change and nothing more — unset STRIPE_CHECKOUT_PRICE_CREDITS_JSON and
every checkout event is quietly acked instead of erroring. Nothing here is
deleted on that day, per the standing "never auto-drop" constraint; it simply
stops matching anything.
"""
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


def _line_price_ids(line_data: list[Any]) -> list[str]:
    out: list[str] = []
    for row in line_data or []:
        price = row.get("price") if isinstance(row, dict) else getattr(row, "price", None)
        pid = price.get("id") if isinstance(price, dict) else getattr(price, "id", None)
        if pid:
            out.append(str(pid))
    return out


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
    For authenticated student-initiated claim (auth_user_id set), fallback to auth_user_id
    when Checkout session omitted metadata.user_id/client_reference_id.
    """
    import stripe

    api_key = (getattr(app_config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        return CheckoutCreditsApplyResult.error(503, "DISABLED", "STRIPE_SECRET_KEY not configured")

    sid = (checkout_session_id or "").strip()
    if not sid:
        return CheckoutCreditsApplyResult.error(400, "INVALID_INPUT", "checkout_session_id is required")

    # ── No credits map configured = CREDITS ARE RETIRED, not broken ───────
    #
    # Founder 2026-07-31: the app is dropping credits and keeping tokens. So an
    # unset STRIPE_CHECKOUT_PRICE_CREDITS_JSON is the intended END STATE, and
    # with no map there is by definition no such thing as a credit sale.
    #
    # This used to return 500, and a 500 tells Stripe to RETRY. The moment that
    # env var is unset, EVERY checkout.session.completed on the account —
    # including every token-tier subscription, which fires one — would retry for
    # three days and then mark the endpoint failing. That is precisely the storm
    # #302 was opened to stop, and its real cost is not the noise: a genuine
    # willab payment failing gets buried in it and nobody notices.
    #
    # So this always ACKS, and the log level carries the difference. Same rule
    # the sibling subscription branch already states in routes/internal_webhooks
    # .py: a mapping we cannot resolve is ours to fix from the logs, and telling
    # Stripe to retry forever fixes nothing.
    raw_map = getattr(app_config, "STRIPE_CHECKOUT_PRICE_CREDITS_JSON", "") or ""
    price_map = parse_price_credits_map(raw_map)
    if not price_map:
        if raw_map.strip():
            # Set, but parsed to nothing: malformed JSON, not an object, or no
            # integer-valued entry. That IS wrong, so stay loud — but still ack,
            # because retrying cannot fix a config error.
            logger.error(
                "stripe checkout credits: STRIPE_CHECKOUT_PRICE_CREDITS_JSON is "
                "set but parsed to an empty map (malformed?) — acking session=%s "
                "to avoid a retry storm", sid,
            )
            return CheckoutCreditsApplyResult.success(200, skipped="credits_map_unusable")
        logger.info("stripe checkout: no credits map configured (credits retired) "
                    "— ignoring session=%s", sid)
        return CheckoutCreditsApplyResult.success(200, skipped="credits_retired")

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

    # ── Line items FIRST, so we can tell whose sale this even is ──────────
    #
    # This endpoint receives EVERY checkout.session.completed on the Stripe
    # account, including sales that have nothing to do with willab (Payment
    # Links for coaching, courses, whatever the founder sells). Those carry no
    # user_id, because there is no willab user behind them.
    #
    # The old order checked user_id BEFORE looking at the prices, so an
    # unrelated sale died on INVALID_SESSION — a 400, which tells Stripe to
    # RETRY. Every foreign sale then retried for days and sat in the dashboard
    # as a failed delivery. The real cost is not the noise: it is that a
    # genuine willab payment failing gets buried among them and nobody notices.
    #
    # So: identify the product first. Not ours → 200, acked, no retry.
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

    checkout_price_ids = _line_price_ids(line_data)

    # INTERSECTION, not "every price must map". A cart with one of our prices
    # plus something unmapped IS ours and is misconfigured — that must stay a
    # loud 400 below, not be silently ignored as somebody else's sale.
    if not (set(checkout_price_ids) & set(price_map)):
        logger.info(
            "stripe checkout: ignoring session=%s — no willab price among %s "
            "(not our sale)", sid, checkout_price_ids,
        )
        return CheckoutCreditsApplyResult.success(200, skipped="not_our_product")

    # ── Only now is a missing user_id a REAL misconfiguration ─────────────
    # The prices say this is a willab sale, so it should have carried a user.
    # 400 here is correct and the retry is useful: it keeps the failure visible
    # until the checkout link is fixed.
    session_user = checkout_user_id(full)
    if not session_user and not auth_user_id:
        return CheckoutCreditsApplyResult.error(
            400,
            "INVALID_SESSION",
            "Set client_reference_id or metadata.user_id to Supabase user id on Checkout Session",
        )

    if auth_user_id and session_user and session_user.strip().lower() != auth_user_id.strip().lower():
        return CheckoutCreditsApplyResult.error(403, "FORBIDDEN", "Checkout session does not belong to this account")

    db_user_id = auth_user_id.strip() if auth_user_id else session_user.strip()
    used_auth_fallback = bool(auth_user_id and not session_user)
    total, map_err = total_credits_for_checkout_session({"line_items": {"data": line_data}}, price_map)
    if map_err or total is None:
        configured_ids = list(price_map.keys())
        logger.error(
            "stripe checkout credits: mapping failed session=%s detail=%s checkout_prices=%s configured_count=%s",
            sid,
            map_err,
            checkout_price_ids,
            len(configured_ids),
        )
        return CheckoutCreditsApplyResult.error(
            400,
            "UNMAPPED_CHECKOUT",
            map_err or "mapping failed",
            checkout_price_ids=checkout_price_ids,
            configured_price_ids=configured_ids,
        )

    try:
        claimed = db.stripe_checkout_grant_claim(sid)
    except Exception as e:
        msg = str(e)
        low = msg.lower()
        logger.warning("stripe_checkout_grant_claim error: %s", e, exc_info=True)
        hint = None
        if "stripe_checkout_credit_grants" in low or "42p01" in low or ("relation" in low and "does not exist" in low):
            hint = "Run migrations/add_stripe_checkout_credit_grants.sql in Supabase (table missing)."
        return CheckoutCreditsApplyResult.error(
            500,
            "DB_ERROR",
            "idempotency claim failed",
            detail=msg[:800],
            hint=hint,
        )

    if not claimed:
        details = db.v2_get_student_details(db_user_id) or {}
        cur = details.get("credits")
        if cur is None:
            from services.db import _free_credit_grant
            cur = _free_credit_grant()
        logger.info("stripe checkout credits duplicate session=%s user=%s credits=%s", sid, db_user_id, cur)
        return CheckoutCreditsApplyResult.success(
            200,
            credits=int(cur),
            duplicate=True,
            delta_applied=0,
            used_auth_fallback=used_auth_fallback,
        )

    new_bal = db.v2_increment_student_credits(db_user_id, total)
    if new_bal is None:
        db.stripe_checkout_grant_release(sid)
        logger.error("stripe checkout credits: increment failed user=%s session=%s", db_user_id, sid)
        return CheckoutCreditsApplyResult.error(
            500,
            "V2_ERROR",
            "Could not update credits (Supabase upsert failed — check Railway logs).",
            hint="Ensure public.v2_student_details has a credits column (migrations/add_v2_student_details_credits.sql) and service_role can write the table.",
        )

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
        used_auth_fallback=used_auth_fallback,
    )
