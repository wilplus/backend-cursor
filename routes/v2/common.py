"""Cross-domain helpers shared by more than one v2 route module.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 1). These
are leaf primitives -- an id validator, the upload size limits, and the two
recording-pipeline feature flags -- with no route of their own, so they live
here rather than in any single domain module.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import os


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
