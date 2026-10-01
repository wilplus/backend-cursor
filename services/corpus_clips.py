"""The licensed corpus (founder 2026-10-01, F4; Phase 4 of the after-practice
paths; migration 0410), dark behind ``Config.PEER_LANE_ENABLED``.

F4: "Licensed corpus clips may be played to speakers, without names, in
'Lend your ear' and 'Bold voices'." A coach files a clip with its licence
(who licensed it, under what) and a passage; a coach's Yes on it lets it
into Bold voices; Lend your ear answers on it stay in
``lend_your_ear_answers`` (it is not a snippet and takes no quorum label).
Nothing here is about any speaker.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from werkzeug.utils import secure_filename

_log = logging.getLogger(__name__)

_EXTENSIONS = (".mp3", ".m4a", ".webm", ".ogg", ".wav")
LABELS = ("yes", "no")


def _enabled() -> bool:
    from services.lend_your_ear import peer_lane_enabled
    return peer_lane_enabled()


def payload(row: dict) -> dict:
    return {
        "id": str(row.get("id")),
        "licence": row.get("licence") or "",
        "passage": row.get("passage") or "",
        "audio_url": row.get("audio_url"),
        "duration_ms": row.get("duration_ms"),
        "coach_value": row.get("coach_value"),
        "active": bool(row.get("active", True)),
        "created_at": row.get("created_at"),
    }


def list_clips(database: Any) -> tuple[int, dict]:
    if not _enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    rows = database.list_corpus_clips(active_only=False) or []
    return 200, {"clips": [payload(r) for r in rows if isinstance(r, dict)]}


def create_clip(database: Any, *, coach_id: str, licence: Any, passage: Any,
                media_file: Any, max_mb: int) -> tuple[int, dict]:
    if not _enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    licence_text = str(licence or "").strip()
    passage_text = str(passage or "").strip()
    if not licence_text or len(licence_text) > 2000:
        return 400, {"code": "INVALID_INPUT", "error": "licence is required"}
    if not passage_text or len(passage_text) > 2000:
        return 400, {"code": "INVALID_INPUT", "error": "passage is required"}
    if media_file is None or not getattr(media_file, "filename", ""):
        return 400, {"code": "INVALID_INPUT", "error": "media_file is required"}
    ext = os.path.splitext(secure_filename(media_file.filename))[1].lower()
    if ext not in _EXTENSIONS:
        return 415, {"code": "UNSUPPORTED_TYPE",
                     "error": f"Upload one of {', '.join(_EXTENSIONS)}."}
    data = media_file.read()
    if len(data) > max(1, int(max_mb)) * 1024 * 1024:
        return 413, {"code": "TOO_LARGE",
                     "error": f"File is too large. Max allowed is {max_mb}MB."}
    from services import journal_media
    content_type = (getattr(media_file, "content_type", None) or "").strip().lower()
    if content_type not in journal_media.allowed_content_types("audio"):
        content_type = "audio/mpeg"
    try:
        stored = journal_media.put_object_bytes(
            kind="audio", content_type=content_type, data=data,
            filename=media_file.filename, folder="corpus")
    except journal_media.JournalMediaError as refused:
        return 503, {"code": "DISABLED", "error": str(refused)}
    except Exception as e:  # noqa: BLE001 — storage named, never raised out
        _log.error("corpus clip upload failed coach=%s: %s", coach_id, e, exc_info=True)
        return 502, {"code": "UPLOAD_FAILED", "error": "Failed to upload to storage."}
    row = database.insert_corpus_clip({
        "added_by": str(coach_id), "licence": licence_text,
        "passage": passage_text, "audio_url": str(stored["public_url"]),
    })
    if not isinstance(row, dict):
        return 500, {"code": "V2_ERROR", "error": "Could not keep the clip."}
    return 201, {"clip": payload(row)}


def label_clip(database: Any, *, coach_id: str, clip_id: str, value: Any) -> tuple[int, dict]:
    """The coach's own read of a licensed clip: yes, no, or null to clear."""
    if not _enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    if value is not None and value not in LABELS:
        return 400, {"code": "INVALID_INPUT", "error": "value must be yes, no or null"}
    row = database.set_corpus_clip_coach_value(
        clip_id=str(clip_id), coach_id=str(coach_id), value=value)
    if not isinstance(row, dict):
        return 404, {"code": "NOT_FOUND", "error": "clip not found"}
    return 200, {"clip": payload(row)}
