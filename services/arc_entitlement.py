"""willab — Paid Audits, entitlement gate. Pure + thin db reads.

An "audit" = an explore ARC (3 takes + the coach-corrected ideal text). The
``arc_purchases`` row IS the entitlement (see services/db.get_arc_purchase).

THE MODEL (founder re-price 2026-07-06 — $25/25 credits, selective delivery):
  • RECORDING / ANALYSIS / SEND-TO-COACH / AUTOMATIC readout: ALWAYS free, for
    EVERY take of EVERY arc, unconditionally. Never gated, never a 402.
  • Per-take coach-authored content (the coach's note/commentary, the coach's
    CORRECTED TRANSCRIPT, the breakthrough badge+video) renders to the user
    UNCONDITIONALLY the moment the coach saves + surfaces it — no payment
    check at all (see services/lab_recording.build_readout_from_session; the
    old per-take/free-intro teaser scoping is RETIRED — this file no longer
    has any take-level or first-arc-ever logic).
  • PAID per arc ($25 = ARC_UNLOCK_CREDITS, spent from the credits balance via
    POST /v2/arc/<arc_id>/unlock — see services/db.deduct_credits_strict):
    the coach-CORRECTED ideal text (a real coach-authored artifact; the raw
    auto-assembled draft is NEVER shown to the student, at any payment state —
    see services/best_presentation.py coach_finalized), the cross-take
    breakthroughs LIST, the game, and the snippet library.
  • The 402 fires ONLY when the user OPENS one of those four paid surfaces —
    a clean paywall, never an error on the record/analysis path.

AC-9: the 402 body carries a PRICE (and the credits equivalent), never a
score/verdict.
"""
from __future__ import annotations

from typing import Any


def is_arc_entitled(db: Any, arc_id: Any, user_id: Any) -> bool:
    """True iff ``user_id`` owns a purchase (paid or founding_pass) for the arc.
    Covers BOTH the legacy $50 Stripe-direct rows and the current $25/credits
    rows — entitlement is row-existence, never the charge shape.

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


def audit_price(config: Any) -> dict:
    """The audit's price, AC-9-safe (a price is not a score). Both the display
    price (minor units) AND its credits equivalent (the live charge)."""
    return {
        "amount_minor": int(getattr(config, "AUDIT_PRICE_AMOUNT_MINOR", 0) or 0),
        "currency": (getattr(config, "AUDIT_PRICE_CURRENCY", "") or "").lower() or None,
        "credits": int(getattr(config, "ARC_UNLOCK_CREDITS", 0) or 0),
    }
