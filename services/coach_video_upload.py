"""A coach's video upload: one validation for both coach video doors, and
the coach's feedback video for a Take.

Moved out of ``routes.v2.coach`` (``POST /v2/coach/sessions/<sid>/video``)
and ``routes.v2.coach_exercises`` (``POST /v2/coach/exercises/<id>/video``),
which carried the same checks twice (founder 2026-10-12: "cut glue").

REUSES the existing coach video transport/storage (services/coach_video_
storage — same bucket + R2/Supabase path the funnel afterwards-video +
feedback videos use; no new infra/bucket/transcoding).
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from werkzeug.utils import secure_filename

from services.coach_video_storage import refreshed_media_url

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}


class VideoRefusal(Exception):
    """A refused upload: the route answers ``body`` with ``status``."""

    def __init__(self, code: str, error: str, status: int) -> None:
        super().__init__(code)
        self.status = status
        self.body = {"code": code, "error": error}


@dataclass(frozen=True)
class VideoUpload:
    safe_name: str
    ext: str
    data: bytes
    content_type: str


def video_max_mb(app_config: Any) -> int:
    return max(1, int(getattr(app_config, "COACH_FEEDBACK_VIDEO_MAX_MB", 100)))


def _too_large(max_mb: int) -> VideoRefusal:
    return VideoRefusal(
        "PAYLOAD_TOO_LARGE", f"Video is too large. Max allowed is {max_mb}MB.", 413)


def read_video_upload(files: Any, content_length: Optional[int],
                      max_mb: int) -> VideoUpload:
    """multipart ``video_file`` (.mp4/.mov/.webm/.m4v), checked in order:
    declared size (413), present (400), format (415), empty (400), read
    size (413)."""
    max_bytes = max_mb * 1024 * 1024
    if (content_length or 0) > max_bytes:
        raise _too_large(max_mb)
    video_file = files.get("video_file")
    if video_file is None or not (video_file.filename or "").strip():
        raise VideoRefusal("INVALID_INPUT", "video_file is required", 400)
    safe_name = secure_filename(video_file.filename or "")
    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in VIDEO_EXTENSIONS:
        raise VideoRefusal("INVALID_VIDEO_FORMAT",
                           "Supported formats: .mp4, .mov, .webm, .m4v", 415)
    data = video_file.read() or b""
    if not data:
        raise VideoRefusal("INVALID_INPUT", "video_file is empty", 400)
    if len(data) > max_bytes:
        raise _too_large(max_mb)
    return VideoUpload(safe_name=safe_name, ext=ext, data=data,
                       content_type=video_file.content_type or "video/mp4")


def store_session_video(database: Any, session_id: str, upload: VideoUpload,
                        idempotency_key: Optional[str]) -> dict:
    """Store the coach's feedback video for a Take and point the session at
    it; the response payload. Raises ``VideoRefusal`` (502) when storage
    refuses the bytes."""
    # Local import on purpose: binds at CALL time, so tests that monkeypatch
    # services.coach_video_storage attributes take effect.
    from services.coach_video_storage import default_media_bucket, put_coach_object_bytes

    # Subsystem V — idempotency (retry dedupe). A re-upload of the SAME
    # record action (same key) reuses the stored take instead of creating a
    # phantom one. Best-effort: a missing table just falls through.
    if idempotency_key:
        existing = database.get_coach_video_asset_by_idempotency_key(idempotency_key)
        if existing and existing.get("video_ref"):
            database.takes.set_session_coach_video_ref(session_id, existing["video_ref"])
            return {"status": "ok", "session_id": session_id,
                    "video_ref": refreshed_media_url(existing["video_ref"]),
                    "deduped": True}

    bucket = default_media_bucket()  # never the literal: #484, _store_presentation_pdf
    # Subsystem V — NON-deterministic key so a re-record does NOT overwrite
    # the prior take (which is training/preference data). The user-facing ref
    # is repointed to the newest take below.
    storage_key = f"coach-feedback/{session_id}/{uuid.uuid4().hex}{upload.ext}"
    try:
        put_coach_object_bytes(bucket, storage_key, upload.data, upload.content_type)
    except Exception as upload_err:
        logger.error("coach video upload failed sid=%s err=%s", session_id, upload_err)
        raise VideoRefusal("UPLOAD_FAILED", "Failed to upload video to storage.",
                           502) from upload_err

    video_ref = f"s3://{bucket}/{storage_key}"  # private bucket: signed on read
    database.takes.set_session_coach_video_ref(session_id, video_ref)
    logger.info("coach video stored sid=%s key=%s", session_id, storage_key)
    # Phase 1 stores the coach's product video only.  The former
    # best-effort corpus capture was a hidden pooled-learning write and is
    # deliberately absent until a separately approved Phase-2 cutover.
    return {"status": "ok", "session_id": session_id,
            "video_ref": refreshed_media_url(video_ref)}
