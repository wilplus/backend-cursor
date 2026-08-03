"""Cross-domain helpers shared by more than one v2 route module.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 1). These
are leaf primitives -- an id validator, the upload size limits, and the two
recording-pipeline feature flags -- with no route of their own, so they live
here rather than in any single domain module.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging
import os

from flask import request

from config import Config
from services.db import db

logger = logging.getLogger(__name__)
config = Config()


def _is_valid_uuid(val):
    import re
    return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', str(val or ''), re.I))


# Presentation recordings run minutes, not seconds — 25MB was too tight (a
# real talk 413'd). 100MB headroom; the global MAX_CONTENT_LENGTH (500MB) still
# bounds it, and oversized audio is compressed to a 16kHz mono mp3 before the
# OpenAI Whisper call (which itself caps at 25MB) — see process_lab_recording.
_LAB_MAX_AUDIO_MB = 100
# Video-ONLY extensions rejected at the Lab upload (BE-2 defensive guard).
# Deliberately excludes "webm" — the live mic records audio/webm (.webm).
_VIDEO_UPLOAD_EXTS = (
    "mp4", "mov", "m4v", "avi", "mkv", "mpeg", "mpg", "wmv", "flv", "3gp",
)


_PRESENTATION_MAX_MB = 20  # slide decks; FE mirrors this guard


def _async_analysis_enabled() -> bool:
    """Async analysis (founder 2026-07-15): the upload 202s immediately and
    the pipeline finishes in a server-side daemon — closing the tab / locking
    the phone never kills it; the FE polls the readout GET. DEFAULT OFF until
    the FE ships polling (deploy order: BE → FE handles 202 → flip
    ASYNC_ANALYSIS_ENABLED=1 in Railway). LIVE-LOOP safe by construction."""
    return (os.getenv("ASYNC_ANALYSIS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _pipeline_queue_enabled() -> bool:
    """Durable queue mode (async-queue work 2026-08-03): the upload 202s
    with a job_id and the pipeline runs on the Redis/RQ worker service,
    with job state in processing_jobs (Postgres) — unlike the daemon below,
    a redeploy mid-job re-runs the job (sweeper) instead of stranding the
    session in 'processing'. DEFAULT OFF (PIPELINE_QUEUE_ENABLED + REDIS_URL
    both required); ANY failure falls back to the ASYNC_ANALYSIS_ENABLED
    daemon / sync path, so flipping the flag can never block an upload
    (live loop). Deploy order: migration → Redis + worker service on
    Railway → flip PIPELINE_QUEUE_ENABLED=1 on the web service."""
    from services.job_queue import queue_configured
    return queue_configured()


# Shared by _coach_pseudonym (routes/v2/coach.py) and
# _pseudonymous_user_id (routes/v2_routes.py) -- both hash against it,
# so it must stay one value in one place.
_COACH_PSEUDONYM_SALT = "willab-coach-pseudonym-v1"


def _client_ip_from_request() -> str:
    """Best-effort client IP. Trusts X-Forwarded-For first (Railway/CDN), then remote_addr."""
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        # First entry is the original client per RFC 7239 conventions.
        return xff.split(",")[0].strip() or (request.remote_addr or "0.0.0.0")
    return request.remote_addr or "0.0.0.0"


def _resolve_snippet_audio_url(snippet: dict) -> str | None:
    """Pick a playable audio URL from whichever column the writer used.

    The four snippet states we have to play through one <audio> element:
      - Path A pre-finalize: audio_segment_path = R2 public URL for the
        per-turn .webm, storage_path NULL.
      - Path A post-finalize: storage_path = bucket-relative key of the
        concat'd session full.webm (Supabase Storage). audio_segment_path
        is left intact (historical record + idempotent re-finalize), but
        storage_path is what start_offset_ms / duration_ms are RELATIVE TO,
        so it must win.
      - Path B (extract_recording_snippets): audio_segment_path = full URL,
        storage_path NULL.
      - Path C (charisma_snippet_service) and student uploads: storage_path
        set, audio_segment_path NULL.

    Precedence is therefore: storage_path → audio_segment_path → None.
    Returning None means there's truly nothing playable. Keeping
    audio_segment_path as the fallback (rather than the primary) is what
    makes the per-turn → canonical-recording migration safe — the moment
    finalize_session_recording populates storage_path, the snippet flips
    from playing its per-turn file to playing a slice of the concat'd
    session audio, no DB cleanup required.
    """
    storage = (snippet.get("storage_path") or "").strip()
    if storage:
        # Two classes of storage_path coexist:
        #   - "session_recordings/<sid>/full.webm" and
        #     "guest_funnel/<sid>/turn_N.webm" — interview audio in R2,
        #     served via the audio bucket's public base URL.
        #   - "charisma_snippets/<uuid>" — student-uploaded clips in
        #     Supabase Storage, served via signed URLs.
        # Disambiguate by prefix. Anything that isn't a known
        # Supabase-only prefix is assumed to be audio-bucket content.
        is_supabase_prefix = storage.startswith("charisma_snippets/")
        if not is_supabase_prefix:
            try:
                from services.audio_storage import audio_public_url
                url = audio_public_url(storage)
                if url:
                    return url
            except Exception as e:
                logger.warning(
                    "snippet audio URL: R2 audio URL build failed for %s: %s",
                    storage, e,
                )
            # R2_AUDIO_PUBLIC_BASE_URL not set (local dev) — fall through
            # to the Supabase signed-URL path so dev still works.
        try:
            return db.create_signed_url(
                config.AUDIO_BUCKET_NAME, storage, config.SIGNED_URL_EXPIRY_SECONDS
            )
        except Exception as e:
            logger.warning(
                "snippet audio URL: signed url failed for %s: %s — falling back",
                storage, e,
            )
            # fall through to audio_segment_path
    seg = (snippet.get("audio_segment_path") or "").strip()
    if seg:
        return seg
    return None
