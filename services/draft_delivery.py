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


def auto_approve_payload_for_send(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Set draft_payload UI state to Sent + approved_at after a successful delivery."""
    out = dict(payload or {})
    out["state"] = "Sent"
    out["approved_at"] = datetime.now(timezone.utc).isoformat()
    return out


