"""Extract charisma snippets from guest funnel recordings + recompute
the per-window metrics blob when an admin nudges snippet boundaries.

For the initial MVP we extract the entire 15 s recording as a single
snippet. Future: ML-based detection to extract multiple charisma
moments within a longer recording.

Acoustic metrics (WPM, pitch, dB, pause_ms, etc.) are computed at
extraction time AND re-computed every time the admin shifts the
snippet's [start_offset_ms, duration_ms] window via the +/- 2 s
buttons. The JSONB ``metrics`` blob on each row always reflects the
*current* time-bounded slice — never the parent recording. The admin
panel reads pre-computed numbers from the DB; no live Python
analysis runs on the read path.

See ``recompute_snippet_metrics_for_window`` for the boundary-
adjust path.
"""
import logging
import os
from io import BytesIO
from typing import Optional

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

        # Download the original recording through services.audio_storage.
        # The helper reads from R2_AUDIO_BUCKET_NAME in production (where
        # interview-turn audio lives now) and falls back to Supabase
        # Storage AUDIO_BUCKET_NAME in dev. The prior comment about
        # "cold-start funnel uploads to Supabase" is obsolete now that
        # both the cold-start funnel and interview-turn flow share the
        # same audio backend (R2 in prod, Supabase in dev).
        try:
            from services.audio_storage import get_audio_bytes
            audio_bytes = get_audio_bytes(recording_path)
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


# ─── Boundary-adjust path ─────────────────────────────────────────────


def recompute_snippet_metrics_for_window(snippet_id: str) -> Optional[dict]:
    """Recompute the metrics blob for a snippet's current time window.

    Called after any path that mutates ``start_offset_ms`` /
    ``duration_ms`` (POST /admin/snippets/<id>/boundaries, PATCH
    /admin/snippets/<id>). The contract: by the time this returns,
    the row's ``metrics`` JSONB + the individual acoustic columns
    + ``transcript`` + ``wpm`` + ``fillers`` ALL reflect the new
    window — not the previous boundaries, not the parent recording.

    Flow:
      1. Load the snippet row to pick up the current offsets.
      2. Download the parent audio (``audio_segment_path``) — same
         file the boundaries index into.
      3. Slice the PCM to [start_offset_ms, +duration_ms] and run
         ``analyze_audio_window`` so the acoustic metrics describe
         ONLY that window.
      4. Re-Whisper the sliced window (wrapped as WAV) for a fresh
         transcript; recompute WPM and fillers against it.
      5. Persist all of the above atomically via
         ``db.update_snippet_metrics``.

    Returns the new metrics dict on success, ``None`` on any
    irrecoverable failure (snippet missing, audio unavailable,
    window too short for stable analysis). Caller is responsible
    for surfacing the result to the admin UI; failure is non-fatal
    — the row keeps its previous numbers rather than going blank.

    Runs synchronously. The expensive step is the Whisper call
    (~1-2 s for a 10-20 s slice), which is well within the latency
    budget of an admin button click; if we ever push to async we'd
    swap this for an enqueue here.
    """
    from services.db import db

    snippet = db.get_snippet_by_id(snippet_id)
    if not snippet:
        logger.warning(
            "recompute_snippet_metrics_for_window: snippet %s not found",
            snippet_id,
        )
        return None

    start_offset_ms = int(snippet.get("start_offset_ms") or 0)
    duration_ms = int(snippet.get("duration_ms") or 0)
    if duration_ms <= 0:
        logger.warning(
            "recompute_snippet_metrics_for_window: snippet %s has "
            "non-positive duration_ms=%s",
            snippet_id, duration_ms,
        )
        return None

    audio_path = (snippet.get("audio_segment_path") or "").strip()
    if not audio_path:
        logger.warning(
            "recompute_snippet_metrics_for_window: snippet %s has no "
            "audio_segment_path",
            snippet_id,
        )
        return None

    audio_bytes = _load_parent_audio(audio_path)
    if not audio_bytes:
        logger.warning(
            "recompute_snippet_metrics_for_window: parent audio not "
            "fetchable for snippet %s path=%s",
            snippet_id, audio_path,
        )
        return None

    # Re-Whisper the sliced window so WPM + fillers reflect what was
    # actually said inside the new boundaries. Best-effort: if
    # Whisper is down we fall back to the existing transcript
    # (better than blanking the column).
    new_transcript = _retranscribe_window(
        audio_bytes,
        start_offset_ms=start_offset_ms,
        duration_ms=duration_ms,
    )
    if new_transcript is None:
        new_transcript = (snippet.get("transcript") or "").strip() or None
        write_transcript = False
    else:
        write_transcript = True

    # Acoustic + WPM analysis ON THE SLICE.
    from services.audio_metrics import analyze_audio_window
    metrics = analyze_audio_window(
        audio_bytes,
        start_offset_ms=start_offset_ms,
        duration_ms=duration_ms,
        transcript=new_transcript or "",
    )
    if not metrics:
        logger.warning(
            "recompute_snippet_metrics_for_window: analyze_audio_window "
            "returned None for snippet %s",
            snippet_id,
        )
        return None

    # Filler count from the window-accurate transcript.
    filler_count: Optional[int] = None
    if new_transcript:
        try:
            from utils.metrics import count_fillers
            filler_count = int(count_fillers(new_transcript).get("total") or 0)
        except Exception as e:
            logger.warning(
                "recompute: filler count failed for snippet %s: %s",
                snippet_id, e,
            )

    db.update_snippet_metrics(
        snippet_id=snippet_id,
        wpm=metrics.get("wpm"),
        fillers=filler_count,
        pause_ms=metrics.get("pause_ms"),
        dynamic_db=metrics.get("dynamic_db"),
        pitch_center=metrics.get("pitch_center_st"),
        energy=metrics.get("energy_ratio"),
        metrics_json=metrics,
        transcript=new_transcript if write_transcript else None,
    )

    logger.info(
        "recompute_snippet_metrics_for_window: snippet=%s "
        "window=[%dms, +%dms] wpm=%s fillers=%s pause_ms=%s "
        "dynamic_db=%s pitch_st=%s",
        snippet_id, start_offset_ms, duration_ms,
        metrics.get("wpm"), filler_count, metrics.get("pause_ms"),
        metrics.get("dynamic_db"), metrics.get("pitch_center_st"),
    )
    return metrics


def _load_parent_audio(audio_path: str) -> Optional[bytes]:
    """Fetch the parent audio bytes for a snippet.

    ``audio_segment_path`` on a row is either:
      - a storage key (``charisma_snippets/<sid>/<ts>.webm`` or
        ``session_recordings/<sid>/full.webm``)
      - a public URL the upload service stamped at create-time
      - a legacy s3:// URL

    We try the storage-key forms via the existing R2/Supabase
    helpers first (cheap, no HTTP), then fall back to a public-URL
    GET. Returns None when no path works.
    """
    if not audio_path:
        return None

    # Storage-key path: try R2/Supabase audio bucket, then the
    # coach video bucket (legacy snippet audio lived there).
    if not audio_path.startswith(("http://", "https://", "s3://")):
        try:
            from services.audio_storage import get_audio_bytes
            return get_audio_bytes(audio_path)
        except Exception as e:
            logger.info(
                "recompute: get_audio_bytes(%s) miss: %s",
                audio_path, e,
            )
        for bucket in ("coach_feedback_videos", "audio_recordings"):
            try:
                from services.coach_video_storage import (
                    get_coach_object_bytes,
                )
                return get_coach_object_bytes(bucket, audio_path)
            except Exception as e:
                logger.info(
                    "recompute: get_coach_object_bytes(%s, %s) miss: %s",
                    bucket, audio_path, e,
                )
        return None

    # URL path: pull bytes over HTTP. Short timeout — the admin is
    # waiting on a button click.
    try:
        import httpx
        resp = httpx.get(audio_path, timeout=15)
        if resp.status_code == 200 and resp.content:
            return resp.content
        logger.warning(
            "recompute: parent audio HTTP %s for %s",
            resp.status_code, audio_path,
        )
    except Exception as e:
        logger.warning(
            "recompute: parent audio fetch failed url=%s err=%s",
            audio_path, e,
        )
    return None


def _retranscribe_window(
    audio_bytes: bytes,
    *,
    start_offset_ms: int,
    duration_ms: int,
) -> Optional[str]:
    """Re-Whisper just the sliced window. Returns the transcript
    text on success, ``None`` on any failure — caller falls back
    to the existing transcript in that case so we never blank the
    column on a transient API hiccup.
    """
    from services.audio_metrics import extract_window_as_wav

    wav = extract_window_as_wav(
        audio_bytes,
        start_offset_ms=start_offset_ms,
        duration_ms=duration_ms,
    )
    if not wav:
        return None

    try:
        from services.openai_service import OpenAIService
        ois = OpenAIService()
        if not ois.client:
            return None
        result = ois.transcribe_audio(BytesIO(wav), "snippet_window.wav")
    except Exception as e:
        logger.warning("recompute: Whisper call failed: %s", e)
        return None

    # transcribe_audio may return either a dict {text, duration} or
    # a raw string depending on caller version — handle both.
    if isinstance(result, dict):
        text = (result.get("text") or "").strip()
    elif isinstance(result, str):
        text = result.strip()
    else:
        return None
    return text or None
