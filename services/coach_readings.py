"""A coach's model readings (founder 2026-10-01; Phase 3 of the after-practice
paths; migration 0409), dark behind ``Config.PRAISE_AFTER_PRACTICE_ENABLED``.

The coach tool: a coach records five to ten readings of short passages and
publishes the ones they stand behind. A published reading plays to speakers
in Bold voices without the coach's name; the coach agreement covers that
use. Stored like an exercise video (journal media, public base). Nothing
here is a judgement about any speaker.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from werkzeug.utils import secure_filename

_log = logging.getLogger(__name__)

_EXTENSIONS = {
    "audio": (".mp3", ".m4a", ".webm", ".ogg", ".wav"),
    "video": (".mp4", ".mov", ".webm", ".m4v"),
}
_DEFAULT_TYPE = {"audio": "audio/mpeg", "video": "video/mp4"}
PASSAGE_MAX = 2000


def _enabled() -> bool:
    from services.after_practice import praise_after_practice_enabled
    return praise_after_practice_enabled()


def payload(row: dict) -> dict:
    return {
        "id": str(row.get("id")),
        "passage": row.get("passage") or "",
        "media_url": row.get("media_url"),
        "media_kind": row.get("media_kind") or "audio",
        "published_at": row.get("published_at"),
        "created_at": row.get("created_at"),
    }


def list_readings(database: Any, *, coach_id: str) -> tuple[int, dict]:
    if not _enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    rows = database.list_coach_readings(str(coach_id)) or []
    return 200, {"readings": [payload(r) for r in rows if isinstance(r, dict)]}


def create_reading(database: Any, *, coach_id: str, passage: Any,
                   media_file: Any, media_kind: Any, max_mb: int) -> tuple[int, dict]:
    """(status, payload): 201 {reading}, or the refusal named."""
    if not _enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    text = str(passage or "").strip()
    if not text or len(text) > PASSAGE_MAX:
        return 400, {"code": "INVALID_INPUT", "error": "passage is required"}
    kind = str(media_kind or "audio").strip().lower()
    if kind not in _EXTENSIONS:
        return 400, {"code": "INVALID_INPUT", "error": "media_kind must be audio or video"}
    if media_file is None or not getattr(media_file, "filename", ""):
        return 400, {"code": "INVALID_INPUT", "error": "media_file is required"}
    ext = os.path.splitext(secure_filename(media_file.filename))[1].lower()
    if ext not in _EXTENSIONS[kind]:
        return 415, {"code": "UNSUPPORTED_TYPE",
                     "error": f"Upload one of {', '.join(_EXTENSIONS[kind])}."}
    data = media_file.read()
    if len(data) > max(1, int(max_mb)) * 1024 * 1024:
        return 413, {"code": "TOO_LARGE",
                     "error": f"File is too large. Max allowed is {max_mb}MB."}
    from services import journal_media
    content_type = (getattr(media_file, "content_type", None) or "").strip().lower()
    if content_type not in journal_media.allowed_content_types(kind):
        content_type = _DEFAULT_TYPE[kind]
    try:
        stored = journal_media.put_object_bytes(
            kind=kind, content_type=content_type, data=data,
            filename=media_file.filename, folder="reading")
    except journal_media.JournalMediaError as refused:
        return 503, {"code": "DISABLED", "error": str(refused)}
    except Exception as e:  # noqa: BLE001 — storage named, never raised out
        _log.error("coach reading upload failed coach=%s: %s", coach_id, e, exc_info=True)
        return 502, {"code": "UPLOAD_FAILED", "error": "Failed to upload to storage."}
    row = database.insert_coach_reading({
        "coach_id": str(coach_id), "passage": text,
        "media_url": str(stored["public_url"]), "media_kind": kind,
    })
    if not isinstance(row, dict):
        return 500, {"code": "V2_ERROR", "error": "Could not keep the reading."}
    return 201, {"reading": payload(row)}


def publish_reading(database: Any, *, coach_id: str, reading_id: str,
                    published: Any) -> tuple[int, dict]:
    """Publish or withdraw one of the coach's own readings."""
    if not _enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    if not isinstance(published, bool):
        return 400, {"code": "INVALID_INPUT", "error": "published must be true or false"}
    row = database.set_coach_reading_published(
        reading_id=str(reading_id), coach_id=str(coach_id), published=published)
    if not isinstance(row, dict):
        return 404, {"code": "NOT_FOUND", "error": "reading not found"}
    return 200, {"reading": payload(row)}
