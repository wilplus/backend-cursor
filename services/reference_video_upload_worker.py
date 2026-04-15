"""
Reference video upload: storage + DB row + optional Whisper transcription.
Optional job_id updates copilot_reference_upload_jobs for admin UI polling.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

import sentry_sdk

from config import Config
from services.db import db
from services.ffmpeg_audio_extract import extract_audio_mp3_for_whisper, ffmpeg_available

config = Config()
logger = logging.getLogger(__name__)

# Containers we send to Whisper as-is (API accepts these).
REFERENCE_VIDEO_WHISPER_DIRECT_EXTENSIONS = {".mp4", ".webm", ".m4v"}


def _value_hash(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _job_progress(
    job_id: str | None,
    *,
    stage: str,
    percent: int,
    message: str | None = None,
    reference_video_id: str | None = None,
    error: str | None = None,
) -> None:
    if not job_id:
        return
    try:
        fields: Dict[str, Any] = {
            "stage": stage,
            "percent": max(0, min(100, int(percent))),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if message is not None:
            fields["message"] = message
        if reference_video_id is not None:
            fields["reference_video_id"] = reference_video_id
        if error is not None:
            fields["error"] = error
        db.update_copilot_reference_upload_job(job_id, fields)
    except Exception as e:
        logger.warning("reference upload job progress failed job_id=%s: %s", job_id, e)


def run_reference_video_upload(
    *,
    job_id: str | None,
    video_bytes: bytes,
    safe_name: str,
    ext: str,
    student_user_id: str,
    session_id: Optional[str],
    draft_id: Optional[str],
    title: Optional[str],
    tags: List[str],
    is_universal: bool,
    admin_user_id: str,
) -> Dict[str, Any]:
    """
    Returns {"reference_video": dict, "preview_url": str | None}.
    Raises on hard failures (storage/DB insert).
    """
    _job_progress(job_id, stage="storage", percent=12, message="Uploading file to storage…")
    bucket = config.COACH_FEEDBACK_VIDEO_BUCKET
    ref_storage_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    storage_path = f"copilot/reference_videos/{now:%Y/%m}/{ref_storage_id}{ext}"
    content_type = mimetypes.guess_type(safe_name)[0] or "video/mp4"
    db.upload_audio(bucket, storage_path, video_bytes, content_type)

    _job_progress(job_id, stage="database", percent=38, message="Saving database record…")
    created = db.create_admin_uploaded_reference_video(
        draft_id=draft_id,
        user_id=student_user_id,
        session_id=session_id,
        storage_path=storage_path,
        source_video_url=None,
        transcript_text=None,
        feature_metadata={
            "bucket": bucket,
            "content_type": content_type,
            "size_bytes": len(video_bytes),
            "original_filename": safe_name,
            "uploaded_by_admin_id": admin_user_id,
        },
        tags=tags,
        is_universal=is_universal,
        created_by=admin_user_id,
        transcription_status="processing",
        transcription_error=None,
        title=title,
    )
    if not created:
        raise RuntimeError("Could not store reference video metadata")

    rid = str(created.get("id"))
    _job_progress(job_id, stage="database", percent=48, message="Metadata saved", reference_video_id=rid)

    whisper_bytes: bytes = video_bytes
    whisper_filename = safe_name or "reference-video.mp4"
    audio_source = "direct"

    if ext not in REFERENCE_VIDEO_WHISPER_DIRECT_EXTENSIONS:
        _job_progress(
            job_id,
            stage="transcription",
            percent=52,
            message="Extracting audio with ffmpeg for Whisper…",
            reference_video_id=rid,
        )
        extracted = extract_audio_mp3_for_whisper(
            video_bytes,
            max_seconds=config.REFERENCE_VIDEO_WHISPER_MAX_AUDIO_SECONDS,
        )
        if not extracted:
            err_txt = (
                "ffmpeg is not available on this server; add it (apt.txt / image) or upload .mp4/.webm/.m4v."
                if not ffmpeg_available()
                else "ffmpeg could not decode audio from this file (codec missing or no audio track?)."
            )
            created = db.update_admin_uploaded_reference_video(
                rid,
                {"transcription_status": "failed", "transcription_error": err_txt[:1000]},
            ) or created
            _job_progress(
                job_id,
                stage="transcription",
                percent=80,
                message="Transcription skipped after audio extract failure",
                reference_video_id=rid,
            )
        else:
            whisper_bytes = extracted
            whisper_filename = "reference-extracted-audio.mp3"
            audio_source = "ffmpeg_mp3"

    if (created.get("transcription_status") or "") != "failed":
        _job_progress(
            job_id,
            stage="transcription",
            percent=58 if audio_source == "ffmpeg_mp3" else 55,
            message=(
                "Transcribing with Whisper (API has no per-second progress; "
                f"after extract, at most first {config.REFERENCE_VIDEO_WHISPER_MAX_AUDIO_SECONDS}s of audio)…"
            ),
            reference_video_id=rid,
        )
        try:
            from services.openai_service import openai_service

            tr = openai_service.transcribe_audio(BytesIO(whisper_bytes), whisper_filename)
            transcript_text = (tr.get("text") or "").strip()
            fm = dict(created.get("feature_metadata") or {})
            fm["whisper_audio_source"] = audio_source
            created = db.update_admin_uploaded_reference_video(
                rid,
                {
                    "transcript_text": transcript_text or None,
                    "transcription_status": "done",
                    "transcription_error": None,
                    "feature_metadata": fm,
                },
            ) or created
            if transcript_text:
                try:
                    db.create_admin_annotation_event(
                        user_id=student_user_id,
                        session_id=session_id,
                        section_type="assignment",
                        field_name="reference_video_transcript",
                        ai_original_text=None,
                        coach_final_text=transcript_text[:4000],
                        reason_chip="video_upload",
                        custom_reason=f"reference_video_id={created.get('id')}",
                        created_by=admin_user_id,
                        draft_id=draft_id,
                        previous_value_hash=None,
                        new_value_hash=_value_hash(transcript_text[:4000]),
                    )
                except Exception as ann_err:
                    logger.warning("reference video upload annotation failed: %s", ann_err)
            _job_progress(
                job_id,
                stage="transcription",
                percent=85,
                message="Transcription finished",
                reference_video_id=rid,
            )
        except Exception as tr_err:
            sentry_sdk.capture_exception(tr_err)
            created = db.update_admin_uploaded_reference_video(
                rid,
                {
                    "transcription_status": "failed",
                    "transcription_error": str(tr_err)[:1000],
                },
            ) or created
            _job_progress(
                job_id,
                stage="transcription",
                percent=85,
                message="Transcription failed; video is still saved",
                reference_video_id=rid,
            )

    _job_progress(job_id, stage="finalize", percent=92, message="Preparing preview…", reference_video_id=rid)
    preview_url = None
    try:
        preview_url = db.create_signed_url(bucket, storage_path, 3600)
    except Exception as sign_err:
        logger.warning("reference video signed URL failed: %s", sign_err)

    _job_progress(job_id, stage="completed", percent=100, message="Ready", reference_video_id=rid)
    return {"reference_video": created, "preview_url": preview_url}
