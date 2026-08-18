"""Operational policy for owner/coach Confident Voice disagreement.

Owner responses remain routing-only. This module reads them to decide workflow
but never copies them into a label, quorum, calibration, evaluation, SFT, or
DPO table.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _owner_response(database, arc_id: Any, snippet_id: Any) -> Optional[str]:
    for row in database.list_owner_voice_album_routes(str(arc_id)) or []:
        if str((row or {}).get("snippet_id") or "") == str(snippet_id):
            return str((row or {}).get("response") or "") or None
    return None


def _latest_professional_value(database, snippet_id: Any) -> Optional[str]:
    rows = (database.get_confidence_labels_by_snippet_ids(
        [str(snippet_id)]) or {}).get(str(snippet_id), []) or []
    professional = [
        row for row in rows if isinstance(row, dict)
        and not row.get("self_report")
        and (row.get("lane") == "coach"
             or (row.get("lane") is None and row.get("source") == "coach"))
        and row.get("state_id") in (None, "confidence")
        and not row.get("unrateable")
        and row.get("value") in ("yes", "no")
    ]
    professional.sort(key=lambda row: row.get("updated_at") or "")
    return professional[-1].get("value") if professional else None


def reconcile_confidence_review(
    database, *, snippet_id: Any, session: dict, owner_user_id: Any,
    coach_value: Optional[str] = None, coach_note: Optional[str] = None,
    coach_write: bool = False, is_rereview: bool = False,
) -> str:
    """Reconcile one snippet and return its operational state.

    ``pending`` means user Yes / coach No and a second listen is required.
    Only a coach write explicitly originating from a re-review can confirm No;
    a retried owner request or ordinary poll can never promote the state.
    """
    arc_id = session.get("arc_id") if isinstance(session, dict) else None
    session_id = session.get("id") if isinstance(session, dict) else None
    if not arc_id or not session_id or not snippet_id or not owner_user_id:
        return "unchanged"
    try:
        owner = _owner_response(database, arc_id, snippet_id)
        existing = database.get_confidence_rereview(str(snippet_id))
        if owner != "yes":
            if existing:
                database.resolve_confidence_rereview(str(snippet_id))
            return "silent"

        value = coach_value or _latest_professional_value(
            database, snippet_id)
        if value == "yes":
            if existing:
                database.resolve_confidence_rereview(str(snippet_id))
            from services.voice_album import refresh_voice_album
            refresh_voice_album(arc_id, database=database)
            from services.arc_notifications import fire_voice_album_ready
            fire_voice_album_ready(database, owner_user_id, arc_id)
            return "coach_reviewed"

        if value != "no":
            return "pending_coach_review"

        if coach_write and is_rereview and existing \
                and existing.get("status") == "pending":
            database.resolve_confidence_rereview(
                str(snippet_id), confirmed_no=True, coach_note=coach_note)
            from services.arc_notifications import (
                fire_confidence_not_confirmed,
            )
            fire_confidence_not_confirmed(
                database, owner_user_id, arc_id, session_id, snippet_id,
                coach_note)
            return "not_confirmed"

        if not existing or existing.get("status") != "pending":
            database.upsert_confidence_rereview(
                snippet_id=str(snippet_id), session_id=str(session_id),
                arc_id=str(arc_id), owner_user_id=str(owner_user_id))
        return "pending_rereview"
    except Exception as e:
        logger.warning("confidence review reconciliation failed snip=%s: %s",
                       snippet_id, e)
        return "unchanged"
