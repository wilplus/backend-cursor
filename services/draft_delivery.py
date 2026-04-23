"""Unified draft delivery lifecycle helpers (copilot / Training Studio)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DELIVERY_IDLE = "idle"
DELIVERY_DELIVERING = "delivering"
DELIVERY_DELIVERED = "delivered"
DELIVERY_FAILED = "failed"

FAILED_STEP_RENDER = "render"
FAILED_STEP_EMAIL = "email"


def infer_delivery_lifecycle(row: Optional[Dict[str, Any]]) -> str:
    """Derive lifecycle when DB column missing (pre-migration) or inconsistent."""
    if not row:
        return DELIVERY_IDLE
    explicit = (row.get("delivery_lifecycle") or "").strip().lower()
    if explicit in (DELIVERY_IDLE, DELIVERY_DELIVERING, DELIVERY_DELIVERED, DELIVERY_FAILED):
        return explicit
    st = str(row.get("status") or "").strip().lower()
    if st == "sent":
        return DELIVERY_DELIVERED
    ps = str(row.get("pipeline_status") or "").strip().lower()
    if ps == "failed":
        return DELIVERY_FAILED
    if ps in ("queued", "running_tts", "running_video", "uploading") and st == "pending":
        return DELIVERY_DELIVERING
    return DELIVERY_IDLE


def _strip(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def auto_approve_payload_for_send(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Set draft_payload UI state to Sent + approved_at after a successful delivery."""
    out = dict(payload or {})
    out["state"] = "Sent"
    out["approved_at"] = datetime.now(timezone.utc).isoformat()
    return out


def log_rlhf_auto_accept_events(
    *,
    db: Any,
    user_id: str,
    session_id: Optional[str],
    draft_id: Optional[str],
    row: Dict[str, Any],
    payload: Dict[str, Any],
    created_by: str,
) -> None:
    """Log admin_annotation_events when coach text equals AI baseline (no manual edit)."""
    pairs = [
        (
            "email_message",
            _strip(payload.get("ai_email_draft") or row.get("ai_draft_message")),
            _strip(
                payload.get("email_draft")
                or payload.get("email_message")
                or payload.get("homework_comment")
                or row.get("ai_draft_message")
            ),
        ),
        (
            "script_draft",
            _strip(payload.get("ai_script_draft") or row.get("ai_draft_video_script")),
            _strip(payload.get("script_draft") or payload.get("video_script") or row.get("ai_draft_video_script")),
        ),
        (
            "task_draft",
            _strip(payload.get("ai_task_suggestion") or row.get("ai_suggested_task_text")),
            _strip(payload.get("task_draft") or payload.get("task_text") or row.get("master_task_text")),
        ),
    ]
    for field_name, ai_text, final_text in pairs:
        if not ai_text or not final_text:
            continue
        if ai_text != final_text:
            continue
        try:
            db.create_admin_annotation_event(
                user_id=user_id,
                session_id=session_id,
                section_type="assignment",
                field_name=field_name,
                ai_original_text=ai_text[:4000] or None,
                coach_final_text=final_text[:4000] or None,
                reason_chip="auto_approve_on_send",
                custom_reason=None,
                created_by=created_by,
                draft_id=draft_id,
                previous_value_hash=None,
                new_value_hash=None,
            )
        except Exception as e:
            logger.warning("auto_approve_on_send annotation failed field=%s: %s", field_name, e)
