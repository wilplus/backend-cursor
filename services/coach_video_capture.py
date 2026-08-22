"""willab — coach-video corpus capture (Subsystem V). CAPTURE ONLY; model deferred.

Captures take-level coach feedback videos in ``coach_video_assets``. No model
is built here.

THE ONE RULE: TAG, DON'T GATE. Every recorded video is stored; ``quality_rate``
is a training-time FILTER label, never a store-or-discard decision. Nothing here
drops a clip.

FENCES: private/training-bound (AC-9 split-sink) — ``coach_video_assets`` is
RLS-locked, never read by any user surface (the user keeps seeing
``coach_video_ref``). Best-effort (live-loop) —
nothing here may break or slow the video upload; every function swallows errors.
"""
from __future__ import annotations

import logging
import os
import threading
from io import BytesIO
from typing import Any, Optional

logger = logging.getLogger(__name__)

CONTENT_TYPES = ("take_summary",)

# Founder self-records are provenance-permissive by default. Legal consent is the
# SEPARATE off-app coach agreement — this field is provenance, not the mechanism.
DEFAULT_CONSENT_SCOPE = ["internal_training", "client_shown", "synthetic_generation"]

# Containers we extract audio from before Whisper (mirrors the reference-video worker).
_EXTRACT_EXTS = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv", ".m4a"}
_WHISPER_MAX_INPUT_BYTES = 24 * 1024 * 1024
_EXTRACT_MAX_SECONDS = 1800  # coach clips are short; generous cap


def build_asset_row(
    *, session_id: Any, snippet_id: Optional[Any], content_type: str,
    recorded_by: Optional[Any], video_ref: Optional[str],
    comment_text: Optional[str], device: Optional[str], source: Optional[str],
    duration: Any, idempotency_key: Optional[str],
    quality_rate: Optional[str] = None,
) -> dict:
    """Assemble the ``coach_video_assets`` row. Pure.

    ``train_eligible`` is computed ONCE here (NOT a generated/stored column) so it
    stays INDEPENDENTLY overridable later via the rating-events lane — a reject
    rating flips it, but a later manual override isn't fought by a re-derivation.
    """
    train_eligible = (quality_rate != "reject")  # None / good / usable → eligible
    row: dict = {
        "session_id": session_id,
        "snippet_id": snippet_id,
        "content_type": content_type,
        "recorded_by": recorded_by,
        "video_ref": video_ref,
        "comment_text_snapshot": (comment_text or None),
        "transcription_status": "pending",
        "device": (device or None),
        "source": (source or None),
        "is_current": True,
        "origin": "recorded",
        "train_eligible": train_eligible,
        "consent_scope": list(DEFAULT_CONSENT_SCOPE),
    }
    if quality_rate:
        row["quality_rate"] = quality_rate
    if duration is not None:
        try:
            row["duration"] = float(duration)
        except (TypeError, ValueError):
            pass
    if idempotency_key:
        row["upload_idempotency_key"] = str(idempotency_key)
    return row


def capture_coach_video(
    *, database, session_id: Any, content_type: str, recorded_by: Optional[Any],
    video_ref: Optional[str], comment_text: Optional[str] = None,
    snippet_id: Optional[Any] = None, device: Optional[str] = None,
    source: Optional[str] = None, duration: Any = None,
    idempotency_key: Optional[str] = None,
    video_bytes: Optional[bytes] = None, filename: Optional[str] = None,
) -> None:
    """Insert the asset row for a NEW take, supersede the prior current take (the
    kept↔superseded preference pair), and spawn async transcription.

    BEST-EFFORT: never raises (live-loop fence). Idempotency (retry dedupe) is
    handled by the ROUTE before storage, so this is only called for a genuine new
    take. ``content_type`` must be one of CONTENT_TYPES.
    """
    db = database
    try:
        if content_type not in CONTENT_TYPES:
            logger.warning("capture_coach_video: bad content_type=%s", content_type)
            return
        prior = db.get_current_coach_video_asset(session_id, content_type, snippet_id)
        row = build_asset_row(
            session_id=session_id, snippet_id=snippet_id, content_type=content_type,
            recorded_by=recorded_by, video_ref=video_ref, comment_text=comment_text,
            device=device, source=source, duration=duration,
            idempotency_key=idempotency_key,
        )
        created = db.insert_coach_video_asset(row)
        if not created:
            logger.warning(
                "capture_coach_video: insert returned None sid=%s ct=%s (run "
                "migrations/add_coach_video_assets.sql?)", session_id, content_type,
            )
            return
        new_id = created.get("id")
        # Supersede the prior current take → label the (kept, superseded) pair.
        if (prior and prior.get("id") and new_id
                and str(prior.get("id")) != str(new_id)):
            db.supersede_coach_video_asset(prior["id"], new_id)
        # Async transcription — best-effort; the video bytes are stored, so a
        # failed transcript is recoverable by a later sweep (never irreversible).
        if new_id and video_bytes:
            _spawn_transcription(db, str(new_id), video_bytes, filename or "coach-video.mp4")
    except Exception as e:
        logger.warning(
            "capture_coach_video failed sid=%s ct=%s err=%s (non-fatal)",
            session_id, content_type, e,
        )


def _spawn_transcription(db, asset_id: str, video_bytes: bytes, filename: str) -> None:
    def _run():
        try:
            _transcribe_and_backfill(db, asset_id, video_bytes, filename)
        except Exception as e:  # pragma: no cover - thread guard
            logger.warning("coach_video transcription thread failed asset=%s err=%s", asset_id, e)
    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception as e:
        logger.warning("coach_video transcription spawn failed asset=%s err=%s", asset_id, e)


def _transcribe_and_backfill(db, asset_id: str, video_bytes: bytes, filename: str) -> None:
    """Extract audio (if a video container) → Whisper → backfill transcript +
    status. Best-effort; marks 'failed' on any error (never raises)."""
    whisper_bytes = video_bytes
    whisper_name = filename or "coach-video.mp4"
    ext = os.path.splitext(filename or "")[1].lower()
    if ext in _EXTRACT_EXTS:
        try:
            from services.ffmpeg_audio_extract import extract_audio_mp3_for_whisper
            whisper_bytes = extract_audio_mp3_for_whisper(
                video_bytes, max_seconds=_EXTRACT_MAX_SECONDS,
            )
            whisper_name = "coach-extracted-audio.mp3"
        except Exception as e:
            logger.warning("coach_video transcription: ffmpeg extract failed asset=%s err=%s", asset_id, e)
    if not whisper_bytes or len(whisper_bytes) > _WHISPER_MAX_INPUT_BYTES:
        db.update_coach_video_transcript(asset_id, None, "failed")
        return
    try:
        from services.openai_service import openai_service
        tr = openai_service.transcribe_audio(BytesIO(whisper_bytes), whisper_name)
        text = (tr.get("text") or "").strip() if isinstance(tr, dict) else ""
        db.update_coach_video_transcript(asset_id, text or None, "done")
    except Exception as e:
        logger.warning("coach_video transcription failed asset=%s err=%s", asset_id, e)
        db.update_coach_video_transcript(asset_id, None, "failed")
