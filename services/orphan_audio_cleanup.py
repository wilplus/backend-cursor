"""Reference-checked cleanup for verified uploads not attached to a Take.

The database owns claiming and both reference checks. The worker receives one
exact provider/bucket/key/hash tuple and never searches by prefix or fallback
bucket. At-least-once delivery is safe because terminal rows are not claimed.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from services.lab_audio_storage import delete_verified_lab_audio_object


logger = logging.getLogger(__name__)


def _rows(value: Any) -> list[dict]:
    if isinstance(value, list):
        return [row for row in value if isinstance(row, dict)]
    return []


def sweep_phase1_orphan_audio(*, database: Any, limit: int = 25) -> dict[str, int]:
    """Delete a bounded batch and return aggregate operational counts."""
    mode = os.getenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "off").strip().lower()
    if mode not in {"enforce", "enforced", "active"}:
        return {"claimed": 0, "deleted": 0, "failed": 0}
    claimed = database.client.rpc("claim_phase1_orphan_audio_v1", {
        "p_limit": max(1, min(100, int(limit))),
    }).execute()
    counts = {"claimed": 0, "deleted": 0, "failed": 0}
    for row in _rows(claimed.data):
        counts["claimed"] += 1
        outcome, error_code = "deleted", None
        try:
            verified = delete_verified_lab_audio_object(
                str(row.get("object_key") or ""),
                bucket=str(row.get("bucket") or ""),
                storage_provider=str(row.get("storage_provider") or ""),
                expected_sha256=str(row.get("exact_bytes_sha256") or ""),
            )
            if not verified:
                raise RuntimeError("OBJECT_DELETION_NOT_VERIFIED")
            counts["deleted"] += 1
        except Exception as error:
            outcome = "failed"
            error_code = type(error).__name__
            counts["failed"] += 1
            logger.warning(
                "phase1 orphan cleanup failed orphan_id=%s code=%s",
                row.get("id"), error_code,
            )
        database.client.rpc("resolve_phase1_orphan_audio_v1", {
            "p_orphan_id": str(row.get("id")),
            "p_outcome": outcome,
            "p_error_code": error_code,
        }).execute()
    return counts
