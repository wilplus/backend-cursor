"""Extract charisma snippets from guest funnel recordings.

For the initial MVP, we extract the entire 15s recording as a single 10-15s snippet.
Future: ML-based detection to extract multiple charisma moments within a longer recording.

Acoustic metrics (WPM, pitch, dB, pause_ms, etc.) are computed ONCE during extraction
and stored as JSONB in the charisma_snippets.metrics column. The admin panel reads
pre-computed metrics from the DB — never re-triggers the Python analysis.
"""
import logging
import os

logger = logging.getLogger(__name__)


def _compute_snippet_metrics(audio_bytes: bytes, duration_seconds: float | None) -> dict | None:
    """Compute acoustic metrics for a snippet's audio chunk.

    Uses the same analyze_audio() pipeline that powers session-level metrics,
    but scoped to the snippet's specific audio segment.

    Returns dict with: wpm, pause_ms, dynamic_db, emphasis_per_min,
    energy_ratio, pitch_center_st, pitch_frame_count, voiced_duration_sec.
    Returns None if metrics can't be computed (missing ffmpeg, too short, etc.).
    """
    try:
        from services.audio_metrics import analyze_audio

        # analyze_audio handles decode, silence detection, pitch, etc.
        # No transcript available for snippet-level WPM (would need Whisper),
        # so WPM will be None unless we add transcription later.
        metrics = analyze_audio(
            audio_bytes=audio_bytes,
            transcript="",  # no per-snippet transcript in MVP
            duration_sec=duration_seconds or 0.0,
        )

        if metrics:
            logger.info(
                "snippet_metrics: computed pause_ms=%.0f dynamic_db=%.1f pitch_st=%.1f",
                metrics.get("pause_ms") or 0,
                metrics.get("dynamic_db") or 0,
                metrics.get("pitch_center_st") or 0,
            )
        return metrics
    except Exception as e:
        logger.warning("snippet_metrics: compute failed (non-fatal): %s", e, exc_info=True)
        return None


def extract_recording_snippets(
    session_id: str,
    user_id: str,
    recording_id: str,
    recording_path: str,
    duration_seconds: float | None,
    storage_bucket: str = "coach_feedback_videos",
) -> list[dict]:
    """Extract snippets from a guest funnel recording and create DB records.

    For MVP: Extract the entire recording as one snippet (assuming it's already 15s or less).
    Computes acoustic metrics once and stores them in the snippet's metrics JSONB column.

    Returns list of created snippet dicts.
    """
    from services.coach_video_storage import (
        get_coach_object_bytes,
        put_coach_object_bytes,
        coach_media_public_url,
    )
    from services.db import db
    from datetime import datetime

    try:
        # For MVP: treat the entire 15s recording as one snippet
        duration_ms = int((duration_seconds or 15) * 1000)
        start_offset_ms = 0

        # Clamp duration to 15s max for guest funnel (per spec)
        if duration_ms > 15000:
            duration_ms = 15000

        # Download the original recording
        try:
            audio_bytes = get_coach_object_bytes("audio_recordings", recording_path)
        except Exception as e:
            logger.error(f"Failed to read recording {recording_path}: {e}")
            return []

        if not audio_bytes:
            logger.warning(f"Recording {recording_path} is empty")
            return []

        # For MVP: use the entire audio as the snippet (no re-encoding/trimming)
        snippet_audio = audio_bytes

        # --- Compute acoustic metrics ONCE during extraction ---
        # These are saved to DB and served to admin panel from there.
        # The admin panel NEVER re-triggers this computation.
        snippet_metrics = _compute_snippet_metrics(
            audio_bytes=snippet_audio,
            duration_seconds=duration_seconds,
        )

        # Generate storage path for the snippet
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        ext = os.path.splitext(recording_path)[1] or ".webm"
        snippet_storage_key = f"charisma_snippets/{session_id}/{timestamp}_snippet{ext}"

        # Upload snippet audio
        try:
            put_coach_object_bytes(
                storage_bucket,
                snippet_storage_key,
                snippet_audio,
                content_type="audio/webm",
            )
        except Exception as e:
            logger.error(f"Failed to upload snippet {snippet_storage_key}: {e}")
            return []

        # Generate public URL for the snippet
        snippet_url = coach_media_public_url(snippet_storage_key)
        if not snippet_url:
            logger.warning(f"Could not generate public URL for {snippet_storage_key}")
            snippet_url = f"s3://{storage_bucket}/{snippet_storage_key}"

        # Create snippet record in DB (metrics stored as JSONB)
        snippet_dict = db.create_charisma_snippet(
            session_id=session_id,
            user_id=user_id,
            recording_id=recording_id,
            start_offset_ms=start_offset_ms,
            duration_ms=duration_ms,
            audio_segment_path=snippet_url,
            metrics=snippet_metrics,
        )

        if snippet_dict:
            has_metrics = "with metrics" if snippet_metrics else "without metrics"
            logger.info(
                f"Created charisma snippet {has_metrics}: session={session_id} user={user_id} "
                f"offset={start_offset_ms}ms duration={duration_ms}ms path={snippet_storage_key}"
            )
            return [snippet_dict]
        else:
            logger.error(f"Failed to create snippet record for session {session_id}")
            return []

    except Exception as e:
        logger.error(f"extract_recording_snippets failed: {e}", exc_info=True)
        return []
