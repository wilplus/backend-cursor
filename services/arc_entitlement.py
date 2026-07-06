"""willab — Paid Audits, entitlement gate. Pure + thin db reads.

An "audit" = an explore ARC (3 takes + the coach-corrected best presentation).
The ``arc_purchases`` row IS the entitlement (see services/db.get_arc_purchase).

THE MODEL (founder re-lock 2026-07-06 — supersedes the take-2+ analysis gate):
  • RECORDING / ANALYSIS / SEND-TO-COACH: ALWAYS free, for EVERY take of EVERY
    arc. The paywall NEVER touches the record→transcribe→send→automatic-readout
    loop and never renders as an "analysis failed" error.
  • AUTOMATIC (acoustic) feedback: always shown, every take.
  • COACH HUMAN feedback + best-presentation + breakthrough moments: PAID per
    arc ($50 = arc_purchase), with ONE exception —
  • FREE INTRO (once per user, EVER): on the user's FIRST-EVER arc, take-1's
    coach human feedback is shown free (``human_feedback_visible``). Takes 2–3
    + the best presentation on that arc still require the purchase.
  • The 402 fires ONLY when the user OPENS a paid-but-unpurchased deliverable
    (best-presentation / ideal-text) — a clean paywall, never an error.

AC-9: the 402 body carries a PRICE, never a score/verdict.
"""
from __future__ import annotations

from typing import Any

# The free-intro take: on the user's first-ever arc, take 1's coach human
# feedback is shown free.
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


def human_feedback_visible(
    db: Any, arc_id: Any, user_id: Any, take_index: Any,
) -> bool:
    """Should THIS take's coach HUMAN feedback (insights / notes / videos) be
    shown to the user?

      • arc purchased                     → yes (all takes).
      • take 1 of the user's FIRST-EVER
        arc (the one-time free intro)     → yes.
      • otherwise                         → no (automatic readout only).

    Non-arc / standalone sessions have no paywall concept — callers pass
    arc_id=None and get True (legacy behavior). Best-effort reads only; a db
    hiccup keeps the human layer hidden on an arc, never opens it.
    """
    if not arc_id:
        return True
    if is_arc_entitled(db, arc_id, user_id):
        return True
    try:
        ti = int(take_index)
    except (TypeError, ValueError):
        return False
    if ti != FREE_TAKE_INDEX or not user_id:
        return False
    # SET-ONCE marker (claimed at the user's first take-1 upload), NOT a scan
    # of surviving sessions — deleting the first arc's takes must never
    # re-open the intro on a later arc (review must-fix; fail-closed).
    intro_arc = db.get_free_intro_arc_id(user_id)
    return bool(intro_arc) and str(intro_arc) == str(arc_id)


def take_requires_payment(take_index: Any) -> bool:
    """Does this take's HUMAN-FEEDBACK VIEW sit behind the paywall (absent the
    free-intro exception)? Take 1 free, take 2+ paid.

    NOTE (2026-07-06): this gates the VIEW of the coach's human feedback only —
    recording/analysis/send are NEVER gated. Kept pure; the intro exception
    lives in ``human_feedback_visible``.
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
    """The 402 PAYMENT_REQUIRED body the FE renders the paywall from.

    Fires ONLY on paid-deliverable opens (best-presentation / ideal-text) —
    never on the record/analysis/send path."""
    return {
        "code": "PAYMENT_REQUIRED",
        # Phase-1: the single per-arc paid flag the FE gates locked affordances
        # on. False here by construction — a 402 only fires on an unpaid arc.
        "audit_paid": False,
        "arc_id": arc_id,
        "price": audit_price(config),
        "sla_hours": int(getattr(config, "AUDIT_SLA_HOURS", _DEFAULT_SLA_HOURS)
                          or _DEFAULT_SLA_HOURS),
    }


def next_take_requires_payment(take_count: Any) -> bool:
    """Would the NEXT take's human-feedback VIEW be paid? (take_count+1 > 1.)

    RETIRED FROM GATING (2026-07-06): recording/analysis is never blocked — the
    session-status gate no longer uses this. Kept pure for FE-advisory use
    (e.g. showing the $50 note copy), and for back-compat with existing tests.
    """
    try:
        tc = int(take_count)
    except (TypeError, ValueError):
        return False
    return take_requires_payment(tc + 1)
