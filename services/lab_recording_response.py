"""Build the immediate response for a completed Lab recording analysis."""
from __future__ import annotations

from typing import Any, Callable


def project_recording_progress(
    *,
    user_id: str | None,
    duration_seconds: int,
    session_id: str,
    database: Any,
    log: Any,
) -> dict[str, Any] | None:
    """Project the authenticated user's progress including this take.

    The persisted cumulative value may not include the just-uploaded guest
    session until claim/merge, so this response-only projection adds the new
    duration. Failures stay non-fatal and guests receive no projection.
    """
    if not user_id:
        return None
    try:
        from services.user_audit import AUDIT_UNLOCK_SECONDS

        base = int(
            database.v2_get_cumulative_recorded_seconds(str(user_id)) or 0
        )
        projected = base + int(duration_seconds or 0)
        return {
            "recorded_seconds": projected,
            "threshold_seconds": AUDIT_UNLOCK_SECONDS,
            "unlocked": projected >= AUDIT_UNLOCK_SECONDS,
        }
    except Exception as exc:
        log.warning(
            "lab: recording_progress projection failed sid=%s: %s",
            session_id,
            exc,
        )
        return None


def rederive_readout_with_slides(
    readout: dict[str, Any],
    *,
    session_id: str,
    audit_paid: bool,
) -> dict[str, Any]:
    """Prefer the persisted readout carrying slide associations.

    The analysis result remains the fallback when re-derivation fails or has
    no snippets. This preserves the immediate 201 response while recording
    the degraded slide-less path.
    """
    try:
        from services.lab_recording import build_readout_from_session

        full_readout = build_readout_from_session(
            session_id,
            audit_paid=audit_paid,
            include_upgrade_cards=False,
        )
        if isinstance(full_readout, dict) and full_readout.get("snippets"):
            return full_readout
    except Exception as exc:
        from services.f1_observability import observe_f1_degrade

        observe_f1_degrade(
            "readout_rederive_failed",
            exc=exc,
            session_id=session_id,
        )
    return readout


def build_completed_recording_response(
    *,
    session_id: str,
    recording_id: str,
    session_context: dict[str, Any],
    readout: dict[str, Any],
    sent_to_coach: bool,
    arc_id: str | None,
    take_index: int | None,
    take_count: int | None,
    duration_seconds: int,
    user_id: str | None,
    database: Any,
    audit_paid_for_arc: Callable[[str | None, str | None], bool],
    log: Any,
) -> dict[str, Any]:
    """Assemble the stable wire payload for a completed analysis."""
    progress = project_recording_progress(
        user_id=user_id,
        duration_seconds=duration_seconds,
        session_id=session_id,
        database=database,
        log=log,
    )
    audit_paid = audit_paid_for_arc(arc_id, user_id)
    response_readout = rederive_readout_with_slides(
        readout,
        session_id=session_id,
        audit_paid=audit_paid,
    )
    duration = int(duration_seconds or 0)
    return {
        "status": "ok",
        "session_id": session_id,
        "recording_id": recording_id,
        "duration_minutes": round(duration / 60.0, 1),
        "audits_needed": max(1, -(-duration // 600)),
        "state": "review_pending" if sent_to_coach else "readout_ready",
        "session_context": session_context,
        "readout": response_readout,
        "arc_id": arc_id,
        "take_index": take_index,
        "take_count": take_count,
        "audit_paid": audit_paid,
        "recording_progress": progress,
    }
