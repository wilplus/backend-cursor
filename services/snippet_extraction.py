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

The boundary-adjust path (``recompute_snippet_metrics_for_window``)
was DELETED 2026-08-06: it was the only writer of the six
denormalized metric columns and had no callers, so those columns
read NULL everywhere. Migration 0254 drops them; the blob is the
representation. See services/snippet_values.
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


def extract_recording_snippets_segmented(
    session_id: str,
    user_id: str,
    recording_id: str,
    recording_path: str,
    duration_seconds: float | None,
    storage_bucket: str = "coach_feedback_videos",
    max_snippets: int | None = None,
) -> list[dict]:
    """willab Readout multi-snippet extraction (design §5 / §14).

    Carves ONE recording into multiple snippet windows at silence
    boundaries (services.audio_metrics.segment_into_snippets) instead of
    the single-whole-recording snippet ``extract_recording_snippets``
    produces. Each window becomes a charisma_snippets row sharing the
    SAME parent audio (uploaded once) with its own
    ``[start_offset_ms, duration_ms]`` — the parent-audio + offset-window
    model the boundary-adjust path (``recompute_snippet_metrics_for_
    window``) already uses, so the +/- 2s buttons keep working.

    NOT yet wired to a live caller — the willab Lab upload handler (build
    sequence Phase 1) calls this. The existing single-snippet
    ``extract_recording_snippets`` is left untouched so the live funnel
    is undisturbed until the willab cutover (stay-shippable rule).

    Decodes the parent ONCE and analyzes each window from that PCM
    (``analyze_pcm_window``) — no per-snippet re-decode. Per-window
    metrics carry the full 10-feature Readout set (the librosa block is
    best-effort). Falls back to the single-snippet path on decode
    failure or when segmentation yields nothing, so the pipeline never
    produces zero snippets for a usable recording.

    Returns the list of created snippet dicts.
    """
    from datetime import datetime

    from services.audio_metrics import (
        decode_audio_to_pcm,
        segment_into_snippets,
        analyze_pcm_window,
    )
    from services.audio_storage import get_audio_bytes
    from services.coach_video_storage import (
        put_coach_object_bytes,
        coach_media_public_url,
    )
    from services.db import db

    def _fallback_single() -> list[dict]:
        return extract_recording_snippets(
            session_id, user_id, recording_id, recording_path,
            duration_seconds, storage_bucket,
        )

    try:
        try:
            audio_bytes = get_audio_bytes(recording_path)
        except Exception as e:
            logger.error("segmented: read failed %s: %s", recording_path, e)
            return _fallback_single()
        if not audio_bytes:
            logger.warning("segmented: recording %s empty", recording_path)
            return []

        sig = decode_audio_to_pcm(audio_bytes)
        if sig is None:
            logger.warning(
                "segmented: decode failed for %s — single-snippet fallback",
                recording_path,
            )
            return _fallback_single()

        seg_kwargs = {} if max_snippets is None else {"max_snippets": max_snippets}
        windows = segment_into_snippets(sig, **seg_kwargs)
        if not windows:
            logger.info(
                "segmented: no windows for %s — single-snippet fallback",
                recording_path,
            )
            return _fallback_single()

        # Upload the full recording ONCE as the shared parent; every
        # snippet row points at it with its own offset window.
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        ext = os.path.splitext(recording_path)[1] or ".webm"
        parent_key = f"charisma_snippets/{session_id}/{timestamp}_parent{ext}"
        try:
            put_coach_object_bytes(
                storage_bucket, parent_key, audio_bytes,
                content_type="audio/webm",
            )
        except Exception as e:
            logger.error("segmented: parent upload failed %s: %s", parent_key, e)
            return _fallback_single()
        parent_url = (
            coach_media_public_url(parent_key)
            or f"s3://{storage_bucket}/{parent_key}"
        )

        created: list[dict] = []
        for (start_ms, end_ms) in windows:
            dur_ms = end_ms - start_ms
            metrics = analyze_pcm_window(
                sig, start_offset_ms=start_ms, duration_ms=dur_ms,
                transcript="",  # per-window Whisper is a later enhancement
            )
            row = db.create_charisma_snippet(
                session_id=session_id,
                user_id=user_id,
                recording_id=recording_id,
                start_offset_ms=start_ms,
                duration_ms=dur_ms,
                audio_segment_path=parent_url,
                metrics=metrics,
            )
            if row:
                created.append(row)

        logger.info(
            "segmented extraction: session=%s windows=%d created=%d "
            "(parent=%s)",
            session_id, len(windows), len(created), parent_key,
        )
        # If every row insert somehow failed, fall back so the pipeline
        # still yields a snippet.
        return created or _fallback_single()

    except Exception as e:
        logger.error(
            "extract_recording_snippets_segmented failed: %s", e, exc_info=True,
        )
        try:
            return _fallback_single()
        except Exception:
            return []


# ─── Boundary-adjust path ─────────────────────────────────────────────


