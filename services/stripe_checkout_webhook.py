"""Stripe Checkout.session.completed → map Price IDs to homework credits."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def parse_price_credits_map(raw: str) -> dict[str, int]:
    if not (raw or "").strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.warning("STRIPE_CHECKOUT_PRICE_CREDITS_JSON invalid JSON: %s", e)
        return {}
    out: dict[str, int] = {}
    if not isinstance(data, dict):
        return {}
    for k, v in data.items():
        try:
            out[str(k)] = int(v)
        except (TypeError, ValueError):
            continue
    return out


def _line_items_data(session: Any) -> list:
    li = session.get("line_items") if isinstance(session, dict) else getattr(session, "line_items", None)
    if li is None:
        return []
    if isinstance(li, dict):
        return list(li.get("data") or [])
    return list(getattr(li, "data", None) or [])


def total_credits_for_checkout_session(session: Any, price_to_credits: dict[str, int]) -> tuple[int | None, str | None]:
    items = _line_items_data(session)
    if not items:
        return None, "no_line_items"
    total = 0
    for row in items:
        price = row.get("price") if isinstance(row, dict) else getattr(row, "price", None)
        if price is None:
            return None, "line_item_missing_price"
        pid = price.get("id") if isinstance(price, dict) else getattr(price, "id", None)
        if not pid:
            return None, "line_item_missing_price_id"
        qty_raw = row.get("quantity") if isinstance(row, dict) else getattr(row, "quantity", 1)
        try:
            qty = int(qty_raw) if qty_raw is not None else 1
        except (TypeError, ValueError):
            qty = 1
        if qty < 1:
            qty = 1
        credits = price_to_credits.get(str(pid))
        if credits is None:
            return None, f"unmapped_price:{pid}"
        total += credits * qty
    if total <= 0:
        return None, "non_positive_credits"
    return total, None


def checkout_user_id(session: Any) -> str | None:
    if isinstance(session, dict):
        ref = session.get("client_reference_id")
        meta = session.get("metadata") or {}
    else:
        ref = getattr(session, "client_reference_id", None)
        meta = getattr(session, "metadata", None) or {}
    if isinstance(ref, str) and ref.strip():
        return ref.strip()
    if isinstance(meta, dict):
        uid = meta.get("user_id")
        if isinstance(uid, str) and uid.strip():
            return uid.strip()
    return None
