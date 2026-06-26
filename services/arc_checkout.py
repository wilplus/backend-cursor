"""willab — Paid Audits, Stripe Checkout for an arc (BE chunk A3).

Two pieces, both keep the EXISTING credits checkout/webhook path untouched:
  • create_arc_checkout_session — mode=payment Checkout for ONE audit, tagged
    with metadata.arc_id + metadata.user_id so the webhook can attribute it.
  • apply_completed_arc_checkout — on checkout.session.completed WITH arc
    metadata, mint the arc_purchase (idempotent on stripe_session_id).

When STRIPE_AUDIT_PRICE_ID is set we use that Price; otherwise we build a
one-off price_data line from AUDIT_PRICE_AMOUNT_MINOR + AUDIT_PRICE_CURRENCY.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from services.db import db

logger = logging.getLogger(__name__)


@dataclass
class ArcCheckoutResult:
    ok: bool
    http_status: int
    payload: dict

    @classmethod
    def error(cls, status: int, code: str, message: str, **extra: Any) -> "ArcCheckoutResult":
        body = {"code": code, "error": message}
        body.update(extra)
        return cls(False, status, body)

    @classmethod
    def success(cls, status: int, **body: Any) -> "ArcCheckoutResult":
        return cls(True, status, dict(body))


def _session_field(session: Any, key: str, default: Any = None) -> Any:
    if isinstance(session, dict):
        return session.get(key, default)
    return getattr(session, key, default)


def create_arc_checkout_session(
    arc_id: str, user_id: str, config: Any, *,
    success_url: Optional[str] = None, cancel_url: Optional[str] = None,
) -> ArcCheckoutResult:
    """Create a mode=payment Checkout Session for one audit (this arc)."""
    import stripe

    api_key = (getattr(config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        return ArcCheckoutResult.error(503, "DISABLED", "STRIPE_SECRET_KEY not configured")
    if not arc_id or not user_id:
        return ArcCheckoutResult.error(400, "INVALID_INPUT", "arc_id and user_id are required")

    stripe.api_key = api_key
    price_id = (getattr(config, "STRIPE_AUDIT_PRICE_ID", None) or "").strip()
    if price_id:
        line_item: dict = {"price": price_id, "quantity": 1}
    else:
        currency = (getattr(config, "AUDIT_PRICE_CURRENCY", "pln") or "pln").lower()
        amount_minor = int(getattr(config, "AUDIT_PRICE_AMOUNT_MINOR", 0) or 0)
        if amount_minor <= 0:
            return ArcCheckoutResult.error(
                500, "MISCONFIGURED",
                "Set STRIPE_AUDIT_PRICE_ID or AUDIT_PRICE_AMOUNT_MINOR",
            )
        line_item = {
            "price_data": {
                "currency": currency,
                "unit_amount": amount_minor,
                "product_data": {"name": "willab audit"},
            },
            "quantity": 1,
        }

    success = (success_url
               or getattr(config, "AUDIT_CHECKOUT_SUCCESS_URL", None)
               or "https://www.willpowerlab.com/audit/{ARC}?paid=1")
    cancel = (cancel_url
              or getattr(config, "AUDIT_CHECKOUT_CANCEL_URL", None)
              or "https://www.willpowerlab.com/audit/{ARC}")
    success = success.replace("{ARC}", str(arc_id))
    cancel = cancel.replace("{ARC}", str(arc_id))

    try:
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[line_item],
            client_reference_id=str(user_id),
            metadata={"arc_id": str(arc_id), "user_id": str(user_id), "kind": "arc_audit"},
            success_url=success,
            cancel_url=cancel,
        )
    except Exception as e:
        logger.warning("create_arc_checkout_session failed arc=%s: %s", arc_id, e)
        return ArcCheckoutResult.error(502, "STRIPE_API_ERROR", str(e))

    return ArcCheckoutResult.success(
        200,
        checkout_url=_session_field(session, "url"),
        checkout_session_id=_session_field(session, "id"),
        arc_id=str(arc_id),
    )


def apply_completed_arc_checkout(checkout_session_id: str, config: Any) -> ArcCheckoutResult:
    """Mint the arc_purchase for a completed Checkout Session that carries arc
    metadata. Idempotent (unique stripe_session_id / unique arc_id). Returns
    ``skipped='not_arc'`` when the session has no arc metadata, so the webhook
    caller falls through to the existing credits path."""
    import stripe

    api_key = (getattr(config, "STRIPE_SECRET_KEY", None) or "").strip()
    if not api_key:
        return ArcCheckoutResult.error(503, "DISABLED", "STRIPE_SECRET_KEY not configured")
    sid = (checkout_session_id or "").strip()
    if not sid:
        return ArcCheckoutResult.error(400, "INVALID_INPUT", "checkout_session_id is required")

    stripe.api_key = api_key
    try:
        full = stripe.checkout.Session.retrieve(sid)
    except Exception as e:
        logger.warning("arc checkout Session.retrieve failed sid=%s: %s", sid, e)
        return ArcCheckoutResult.error(502, "STRIPE_API_ERROR", str(e))

    metadata = _session_field(full, "metadata") or {}
    arc_id = (metadata.get("arc_id") if isinstance(metadata, dict) else None)
    if not arc_id:
        return ArcCheckoutResult.success(200, skipped="not_arc")

    if _session_field(full, "payment_status") != "paid":
        return ArcCheckoutResult.success(200, skipped="not_paid", arc_id=arc_id)
    if _session_field(full, "mode") != "payment":
        return ArcCheckoutResult.success(200, skipped="not_payment_mode", arc_id=arc_id)

    user_id = (metadata.get("user_id") if isinstance(metadata, dict) else None) \
        or _session_field(full, "client_reference_id")
    if not user_id:
        return ArcCheckoutResult.error(
            400, "INVALID_SESSION",
            "arc checkout session missing metadata.user_id / client_reference_id",
            arc_id=arc_id,
        )

    amount_minor = _session_field(full, "amount_total")
    currency = _session_field(full, "currency")

    purchase = db.create_arc_purchase(
        str(arc_id), str(user_id),
        kind="paid", source="stripe",
        currency=currency,
        amount_minor=amount_minor,
        stripe_session_id=sid,
    )
    if not purchase:
        return ArcCheckoutResult.error(
            500, "DB_ERROR",
            "Could not record the arc purchase (run migrations/add_arc_purchases.sql)",
            arc_id=arc_id,
        )

    logger.info("arc checkout applied arc=%s user=%s session=%s", arc_id, user_id, sid)
    return ArcCheckoutResult.success(
        200, arc_id=arc_id, user_id=str(user_id), purchase_id=purchase.get("id"),
    )
