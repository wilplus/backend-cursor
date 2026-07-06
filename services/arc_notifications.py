"""willab — arc Lounge cards/notes, in ONE place (founder bug-batch 2026-07-06).

Owns every arc-lifecycle bubble so each has ONE idempotent client_id (uuid5 per
arc + kind) and fires from every trigger without duplication:

  • best_presentation_ready — ONLY when the arc has >=3 takes AND the coach has
    reviewed (published) AND the arc is PAID. Fired from: lab upload (take >=3),
    publish (review lands), checkout (payment lands) — whichever completes last.
  • transcript_ready — the unpaid/unreviewed >=3-takes counterpart: the user
    gets the transcript-text affordance + strong sides, NOT the best-pres
    buttons (founder #1: never present the best presentation before the coach
    has checked + assembled it and it's paid).
  • human_check note — after take 1: the automatic overview was shown and the
    exercise is undergoing a human check.
  • pay note — after take 2 is SENT on an UNPAID arc: $50 unlocks take-2/3
    human feedback + the coach-corrected best presentation. metadata carries
    the arc_id + a suggested_action so the FE taps straight into checkout.

All best-effort (never raise into the record/publish path); all copy is
user-facing → FOUNDER SIGN-OFF; AC-9: a "human check" note is fine, no
score/verdict ever.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

TAKES_TARGET = 3


def _insert(db, user_id: str, *, client_key: str, kind: str, body: str,
            metadata: dict) -> bool:
    try:
        db.insert_lounge_messages(str(user_id), [{
            "client_id": str(uuid.uuid5(uuid.NAMESPACE_URL, client_key)),
            "role": "bot",
            "kind": kind,
            "body": body,
            "metadata": metadata,
            "client_created_at": datetime.now(timezone.utc).isoformat(),
        }])
        return True
    except Exception as e:
        logger.warning("arc_notifications: insert failed key=%s: %s",
                       client_key, e)
        return False


def _arc_owner_and_state(db, arc_id: str) -> tuple[Optional[str], int, bool, Any]:
    """(owner_user_id, take_count, coach_reviewed, topic) for an arc.

    ``coach_reviewed`` = EVERY take published (review must-fix): with the free
    take-1 human check + auto-send, "any one take published" is vacuously true
    by take 3 — the bp card would fire from take-3's UPLOAD, before the coach
    checked/assembled the whole thing. All-takes-published is the available
    signal for "the coach has been through this arc"."""
    sessions = [s for s in (db.get_arc_sessions(arc_id) or [])
                if isinstance(s, dict)]
    owner = None
    topic = None
    for s in sessions:
        if owner is None and s.get("user_id"):
            owner = str(s.get("user_id"))
        ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
        if ctx.get("topic"):
            topic = ctx.get("topic")
    reviewed = bool(sessions) and all(
        s.get("results_published_at") for s in sessions
    )
    return owner, len(sessions), reviewed, topic


def maybe_fire_best_presentation_ready(db, arc_id: Any) -> Optional[str]:
    """Fire the right >=3-takes card for the arc's CURRENT state:

      reviewed AND paid  → best_presentation_ready (the real buttons)
      otherwise          → transcript_ready (transcript text + strong sides)

    Idempotent per (arc, kind); safe to call from upload, publish, and checkout
    — the terminal card fires exactly once, whichever trigger completes the
    condition. Returns the kind fired, or None. Never raises."""
    try:
        if not arc_id:
            return None
        owner, take_count, reviewed, topic = _arc_owner_and_state(db, arc_id)
        if not owner or take_count < TAKES_TARGET:
            return None
        from services.arc_entitlement import is_arc_entitled
        paid = is_arc_entitled(db, arc_id, owner)
        if reviewed and paid:
            body = (f"Your best presentation for {topic} is ready."
                    if topic else "Your best presentation is ready.")
            _insert(
                db, owner,
                client_key=f"willab-bestpres:{arc_id}",
                kind="best_presentation_ready",
                body=body,
                metadata={"arc_id": str(arc_id), "topic": topic},
            )
            return "best_presentation_ready"
        body = (f"Your full transcript for {topic} is ready."
                if topic else "Your full transcript is ready.")
        _insert(
            db, owner,
            client_key=f"willab-transcript:{arc_id}",
            kind="transcript_ready",
            body=body,
            metadata={"arc_id": str(arc_id), "topic": topic},
        )
        return "transcript_ready"
    except Exception as e:
        logger.warning("arc_notifications: bp-ready check failed arc=%s: %s",
                       arc_id, e)
        return None


def fire_human_check_note(db, user_id: Any, arc_id: Any) -> bool:
    """After take 1: automatic overview shown; a human check is underway.
    Idempotent per arc. Copy = founder sign-off; AC-9-safe (no verdict)."""
    if not user_id or not arc_id:
        return False
    return _insert(
        db, str(user_id),
        client_key=f"willab-humancheck:{arc_id}",
        kind="text",
        body=(
            "This was your automatic overview — your take is also being "
            "checked by your coach."
        ),
        metadata={"arc_id": str(arc_id), "note": "human_check"},
    )


def fire_pay_note(db, user_id: Any, arc_id: Any) -> bool:
    """After take 2 is sent on an UNPAID arc: the $50 unlock note. Skipped when
    the arc is already entitled. Idempotent per arc. metadata.suggested_action
    lets the FE tap straight into the arc checkout (clean paywall — never an
    error). Copy = founder sign-off."""
    if not user_id or not arc_id:
        return False
    try:
        from services.arc_entitlement import is_arc_entitled
        if is_arc_entitled(db, arc_id, user_id):
            return False  # already paid — no note
    except Exception:
        # Fail SILENT (review): on an entitlement-check hiccup, skip the note —
        # never show a paying user the $50 ask. The note re-fires on a later
        # trigger if the arc really is unpaid.
        return False
    return _insert(
        db, str(user_id),
        client_key=f"willab-paynote:{arc_id}",
        kind="text",
        body=(
            "You keep getting the automatic overview free on every take. To "
            "receive your coach's personal feedback on takes 2 and 3 — plus "
            "your best presentation, corrected by the coach — unlock this "
            "training for $50."
        ),
        metadata={
            "arc_id": str(arc_id),
            "note": "payment",
            "suggested_action": "arc_checkout",
        },
    )
