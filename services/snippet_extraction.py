"""Extract charisma snippets from guest funnel recordings.

For the initial MVP, we extract the entire 15s recording as a single 10-15s snippet.
Future: ML-based detection to extract multiple charisma moments within a longer recording.
"""
import logging
import os
from io import BytesIO

logger = logging.getLogger(__name__)


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
    Returns list of created snippet dicts.

    Args:
        session_id: Guest session ID (maps to v2_sessions.id)
        user_id: User ID (null for guest initially, set after claim)
        recording_id: Recording ID (maps to recording_1.id)
        recording_path: S3/Supabase Storage path to the audio file
        duration_seconds: Duration of the recording in seconds (informational)
        storage_bucket: Bucket to store snippet audio files

    Returns:
        List of created snippet dicts
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
        # In future, could use ffmpeg/librosa to detect multiple charisma moments
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
            # Return empty list if we can't read the file; don't fail the whole upload
            return []

        if not audio_bytes:
            logger.warning(f"Recording {recording_path} is empty")
            return []

        # For MVP: use the entire audio as the snippet (no re-encoding/trimming)
        # In production: use ffmpeg to extract exact time range and convert to MP3
        snippet_audio = audio_bytes

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

        # Create snippet record in DB
        snippet_dict = db.create_charisma_snippet(
            session_id=session_id,
            user_id=user_id,
            recording_id=recording_id,
            start_offset_ms=start_offset_ms,
            duration_ms=duration_ms,
            audio_segment_path=snippet_url,
        )

        if snippet_dict:
            logger.info(
                f"Created charisma snippet: session={session_id} user={user_id} "
                f"offset={start_offset_ms}ms duration={duration_ms}ms path={snippet_storage_key}"
            )
            return [snippet_dict]
        else:
            logger.error(f"Failed to create snippet record for session {session_id}")
            return []

    except Exception as e:
        logger.error(f"extract_recording_snippets failed: {e}", exc_info=True)
        return []
