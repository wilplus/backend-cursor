"""willab — Paid Audits, entitlement gate (BE chunk A2). Pure + thin db reads.

An "audit" = an explore ARC (3 takes + the ideal-text report). The
``arc_purchases`` row IS the entitlement (see services/db.get_arc_purchase).

LIVE-LOOP FENCE (hard): take-1 — the first recording and its read — is ALWAYS
free and must NEVER be gated. The paywall starts at take-2's feedback/read,
take-3, and the per-arc ideal-text deliverable. ``take_requires_payment``
encodes the take boundary; the deliverable reads (best-presentation,
ideal-text) gate regardless of take (they only exist after 3 takes).

AC-9: the 402 body carries a PRICE, never a score/verdict.
"""
from __future__ import annotations

from typing import Any

# Takes at/under this index are always free (take 1 = the baseline). The
# first take's record→transcribe→read loop is never gated.
FREE_TAKE_INDEX = 1

# Default delivery SLA if config is missing.
_DEFAULT_SLA_HOURS = 48


def is_arc_entitled(db: Any, arc_id: Any, user_id: Any) -> bool:
    """True iff ``user_id`` owns a purchase (paid or founding_pass) for the arc.

    Defaults to NOT entitled on any hiccup (db.get_arc_purchase never raises and
    returns None on a missing table) — a failure keeps the paywall up, never
    opens it.
    """
    if not arc_id or not user_id:
        return False
    purchase = db.get_arc_purchase(arc_id)
    if not isinstance(purchase, dict):
        return False
    return str(purchase.get("user_id")) == str(user_id)


def take_requires_payment(take_index: Any) -> bool:
    """Does this take sit behind the paywall?

    Take 1 (and unknown/None — a standalone or pre-arc take) is free; take 2+
    requires entitlement. Callers that gate a deliverable (not a specific take)
    pass no take_index and gate unconditionally.
    """
    if take_index is None:
        return False
    try:
        ti = int(take_index)
    except (TypeError, ValueError):
        return False
    return ti > FREE_TAKE_INDEX


def audit_price(config: Any) -> dict:
    """The single audit price, AC-9-safe (a price is not a score). minor units."""
    return {
        "amount_minor": int(getattr(config, "AUDIT_PRICE_AMOUNT_MINOR", 0) or 0),
        "currency": (getattr(config, "AUDIT_PRICE_CURRENCY", "") or "").lower() or None,
    }


def payment_required_payload(arc_id: Any, config: Any) -> dict:
    """The 402 PAYMENT_REQUIRED body the FE renders the paywall from."""
    return {
        "code": "PAYMENT_REQUIRED",
        "arc_id": arc_id,
        "price": audit_price(config),
        "sla_hours": int(getattr(config, "AUDIT_SLA_HOURS", _DEFAULT_SLA_HOURS)
                          or _DEFAULT_SLA_HOURS),
    }
