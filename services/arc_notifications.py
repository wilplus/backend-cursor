"""willab — arc Lounge cards/notes, in ONE place (founder bug-batch 2026-07-06,
re-priced to $25/25 credits 2026-07-06 same day).

Owns every arc-lifecycle bubble so each has ONE idempotent client_id (uuid5 per
arc + kind) and fires from every trigger without duplication:

  • best_presentation_ready — ONLY when the arc has >=3 takes AND
    coach_finalized (the coach has corrected EVERY slide — the REAL signal
    from services.best_presentation, NOT a proxy like "all takes published";
    a coach can publish every take's automatic review + commentary without
    having done the separate ideal-text correction pass) AND the arc is PAID.
    Fired from: lab upload (take >=3), publish (a take lands, may complete
    coach_finalized), checkout (payment lands), and the coach's own edit save
    — whichever completes the condition last.
  • transcript_ready — the unpaid/unfinalized >=3-takes counterpart: the user
    gets the transcript-text affordance + strong sides, NOT the best-pres
    buttons (founder #1: never present the best presentation before the coach
    has actually corrected it AND it's paid).
  • human_check note — after take 1: the automatic overview was shown and the
    exercise is undergoing a human check.
  • pay note — after take 2 is SENT on an UNPAID arc: 25 credits ($25) unlocks
    the coach-corrected ideal text + breakthroughs list + game + library.
    (Per-take coach commentary/transcript-correction is FREE unconditionally
    now — the pay-note must NOT claim otherwise.) metadata carries the arc_id
    + a suggested_action so the FE taps straight into the unlock flow.

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


def _arc_owner_and_topic(db, arc_id: str) -> tuple[Optional[str], int, Any]:
    """(owner_user_id, take_count, topic) for an arc — the cheap facts. The
    review-readiness signal itself (coach_finalized) comes from
    services.best_presentation, not from here (see maybe_fire_best_
    presentation_ready) — "all takes published" is NOT the same thing as "the
    coach corrected the ideal text" and must not be conflated."""
    from services.best_presentation import spoken_arc_sessions
    # SPOKEN takes only (2026-07-15) — a read never counts toward the ≥3
    # lifecycle trigger.
    sessions = spoken_arc_sessions(db.get_arc_sessions(arc_id))
    owner = None
    topic = None
    for s in sessions:
        if owner is None and s.get("user_id"):
            owner = str(s.get("user_id"))
        ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
        if ctx.get("topic"):
            topic = ctx.get("topic")
    return owner, len(sessions), topic


def maybe_fire_best_presentation_ready(db, arc_id: Any) -> Optional[str]:
    """Fire the right >=3-takes card for the arc's CURRENT state:

      coach_finalized AND paid  → best_presentation_ready (the real buttons)
      otherwise                 → transcript_ready (transcript + strong sides)

    coach_finalized is the REAL signal (services.best_presentation — has the
    coach corrected EVERY slide?), not a proxy. Idempotent per (arc, kind);
    safe to call from upload, publish, checkout, and the coach's edit save —
    the terminal card fires exactly once, whichever trigger completes the
    condition. Returns the kind fired, or None. Never raises."""
    try:
        if not arc_id:
            return None
        owner, take_count, topic = _arc_owner_and_topic(db, arc_id)
        if not owner or take_count < TAKES_TARGET:
            return None
        from services.arc_entitlement import is_arc_entitled
        from services.best_presentation import build_best_presentation
        paid = is_arc_entitled(db, arc_id, owner)
        # Cache-aware (Part B) — a repeated call with an unchanged arc/edits
        # skips the LLM compose, so this is cheap on the common no-op path.
        finalized = bool(
            build_best_presentation(arc_id, database=db).get("coach_finalized")
        )
        if finalized and paid:
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
            "This was your automatic overview. Your take is also being "
            "checked by your coach."
        ),
        metadata={"arc_id": str(arc_id), "note": "human_check"},
    )


def fire_instant_ideal_ready(db, user_id: Any, arc_id: Any) -> bool:
    """The INSTANT ideal-text bubble (founder re-lock 2026-07-17): fired the
    moment the arc's machine draft persists at spoken take 3 — the free,
    labeled instant lane. Distinct from the publish-time purple bubble
    (client_id uuid5 "willab-idealtext:<arc>"; this key differs, no
    collision); the FE tells them apart by metadata.variant. Reuses the
    existing 'ideal_text' lounge kind — no CHECK migration. Idempotent per
    arc; counts the ACTUAL insert (a swallowed rejection must not read as
    fired). Copy = founder sign-off."""
    if not user_id or not arc_id:
        return False
    try:
        persisted = db.insert_lounge_messages(str(user_id), [{
            "client_id": str(uuid.uuid5(
                uuid.NAMESPACE_URL, f"willab-idealtext-instant:{arc_id}")),
            "role": "bot",
            "kind": "ideal_text",
            "body": ("Your instant ideal text is ready. Your coach is "
                     "still polishing the full version."),
            "metadata": {"arc_id": str(arc_id), "variant": "instant"},
            "client_created_at": datetime.now(timezone.utc).isoformat(),
        }])
        if not persisted:
            logger.error(
                "arc_notifications: instant ideal bubble dropped arc=%s "
                "(check the lounge kind CHECK)", arc_id)
            return False
        return True
    except Exception as e:
        logger.warning("arc_notifications: instant ideal bubble failed "
                       "arc=%s: %s", arc_id, e)
        return False


def _fire_ideal_bubble(db, user_id: Any, arc_id: Any, *, client_key: str,
                       body: str, variant: str, version: Any) -> bool:
    """One idempotent ideal-text lifecycle bubble with an HONEST insert
    count (the #201 lesson: a swallowed CHECK rejection must never read as
    fired). Shared by the per-version ready + verified bubbles."""
    if not user_id or not arc_id:
        return False
    try:
        persisted = db.insert_lounge_messages(str(user_id), [{
            "client_id": str(uuid.uuid5(uuid.NAMESPACE_URL, client_key)),
            "role": "bot",
            "kind": "ideal_text",
            "body": body,
            "metadata": {"arc_id": str(arc_id), "variant": variant,
                         "version": version},
            "client_created_at": datetime.now(timezone.utc).isoformat(),
        }])
        if not persisted:
            logger.error(
                "arc_notifications: ideal bubble dropped arc=%s key=%s",
                arc_id, client_key)
            return False
        return True
    except Exception as e:
        logger.warning("arc_notifications: ideal bubble failed arc=%s: %s",
                       arc_id, e)
        return False


def fire_ideal_version_ready(db, user_id: Any, arc_id: Any,
                             version: Any) -> bool:
    """Single deliverable (founder 2026-07-17): a NEW ideal-text version just
    assembled → the per-VERSION ready bubble. Keyed on arc+version, so an
    unchanged reassembly (same version) dedupes and every real new version
    announces once. Copy = founder sign-off."""
    return _fire_ideal_bubble(
        db, user_id, arc_id,
        client_key=f"willab-ideal-ready:{arc_id}:{version}",
        # Invites the next rep (founder handoff 2026-07-17). No em-dash.
        body=("Your ideal text is ready. You can keep refining it by "
              "recording another take."),
        variant="ready", version=version,
    )


def fire_ideal_verified(db, user_id: Any, arc_id: Any, version: Any) -> bool:
    """Single deliverable (founder 2026-07-17): the coach VERIFIED the
    current version → the per-version verified bubble. Copy = founder
    sign-off."""
    return _fire_ideal_bubble(
        db, user_id, arc_id,
        client_key=f"willab-ideal-verified:{arc_id}:{version}",
        body="Your ideal text was verified by your coach.",
        variant="verified", version=version,
    )


def backfill_ideal_bubbles(db, user_id: Any, arc_id: Any) -> int:
    """Back-fill the ideal-text version bubbles for a JUST-CLAIMED guest
    session (founder bug 2026-07-18).

    THE BUG: the per-version bubbles fire in the analysis worker only when
    the take has a known owner (`_cad_user`). A GUEST has no lounge thread,
    so their takes produced no bubbles at all — and signing in afterwards
    never back-filled them, so the version history started empty. The
    founder's core ask is that the chat IS the version history (1.0
    unverified → N.0 verified), so an empty thread is a broken product.

    Fires, for the arc's CURRENT state: the 'ready' bubble for the current
    version, plus 'verified' when that version is coach-verified. Only the
    current version can be back-filled — earlier versions' texts are not
    retained (a version bump overwrites the machine copy), and inventing
    bubbles for versions we can no longer show would be dishonest.

    Idempotent by construction: both bubbles are keyed per (arc, version),
    so a re-claim or a later worker run dedupes. Returns how many fired;
    best-effort, never raises into the claim path."""
    if not user_id or not arc_id:
        return 0
    try:
        row = db.get_coach_arc_ideal_text(arc_id) or {}
        _coach_owned = bool(row.get("updated_by") or row.get("approved_at"))
        _machine = ((row.get("auto_text") or "").strip()
                    or ((row.get("text") or "").strip()
                        if not _coach_owned else ""))
        version = row.get("version") or (1 if _machine else None)
        if not isinstance(version, int):
            return 0
        fired = 0
        if fire_ideal_version_ready(db, user_id, arc_id, version):
            fired += 1
        _vv = row.get("verified_version")
        if _vv == version and (row.get("verified_text") or "").strip():
            if fire_ideal_verified(db, user_id, arc_id, version):
                fired += 1
        if fired:
            logger.info(
                "arc_notifications: back-filled %d ideal bubble(s) arc=%s "
                "version=%s on guest claim", fired, arc_id, version)
        return fired
    except Exception as e:
        logger.warning("arc_notifications: ideal back-fill failed arc=%s: %s",
                       arc_id, e)
        return 0


def fire_pay_note(db, user_id: Any, arc_id: Any) -> bool:
    """After take 2 is sent on an UNPAID arc: the 25-credit ($25) unlock note.
    Skipped when the arc is already entitled. Idempotent per arc. Per-take
    coach commentary + corrected transcript are FREE unconditionally now — the
    note must correctly sell only what's actually paid: the coach-CORRECTED
    ideal text + the breakthroughs list + game + library. metadata.
    suggested_action lets the FE tap straight into POST /v2/arc/<id>/unlock
    (clean paywall — never an error). Copy = founder sign-off."""
    if not user_id or not arc_id:
        return False
    try:
        from services.arc_entitlement import is_arc_entitled
        if is_arc_entitled(db, arc_id, user_id):
            return False  # already paid — no note
    except Exception:
        # Fail SILENT (review): on an entitlement-check hiccup, skip the note —
        # never show a paying user a stale ask. The note re-fires on a later
        # trigger if the arc really is unpaid.
        return False
    return _insert(
        db, str(user_id),
        client_key=f"willab-paynote:{arc_id}",
        kind="text",
        body=(
            "You keep getting your coach's feedback and corrected transcript "
            "free on every take. To also unlock your best presentation, "
            "corrected by your coach, plus your breakthrough moments, "
            "unlock this training for 25 credits ($25)."
        ),
        metadata={
            "arc_id": str(arc_id),
            "note": "payment",
            "suggested_action": "arc_unlock",
        },
    )
