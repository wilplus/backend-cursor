"""Durable background jobs for the recording pipeline (F1-SURFACE).

The lifecycle, end to end:

  upload route ──► create_processing_job (Postgres row, dedup-guarded)
               ──► RQ enqueue (Redis delivers job_id only — never bytes)
               ──► 202 {job_id} + v2_sessions.analysis_state='processing'

  worker       ──► run_processing_job(job_id)
                    · idempotency guards (terminal row → no-op)
                    · CAS claim on the attempts counter (double delivery,
                      sweeper races → exactly one runner)
                    · heartbeat thread stamps heartbeat_at every 60s
                    · re-run cleanup (delete this recording's snippets —
                      candidate windows upsert, token charge is ledger-
                      idempotent per recording_id, the rest is idempotent
                      per arc/version by construction)
                    · re-download audio from object storage
                    · services.analysis_worker.run_full_analysis(...)
                    · completed → analysis_state 'ready'
                    · raise → release for retry (backoff) until the
                      attempts cap, then terminal 'failed' →
                      analysis_state 'failed' (the FE NEVER polls forever)

  sweeper      ──► sweep_stale_jobs(): 'processing' rows with a stale
                   heartbeat (redeploy killed the worker) and 'pending'
                   rows nothing delivered (Redis wiped) are re-enqueued —
                   or terminally failed once out of attempts. Runs at
                   worker boot + every few minutes in the worker, at web
                   boot (app.py), and via POST /v2/internal/jobs/sweep.

Nothing here surfaces scores/verdicts (AC-9): job rows carry mechanical
stage labels and plumbing errors only.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Dict, Optional

import sentry_sdk

from services import job_queue
from services.db import db

logger = logging.getLogger(__name__)

# Dotted path RQ resolves in the worker — the web process enqueues the
# string and never imports the analysis stack.
TASK_PATH = "services.pipeline_jobs.run_processing_job"

KIND_SESSION_RECORDING = "session_recording"


def _int_env(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


class ConfigMismatchError(RuntimeError):
    """A misconfiguration no retry can fix — fail the job immediately.

    Distinct from a transient error on purpose: burning three attempts and
    two backoff waits on a missing env var wastes minutes and buries the
    real cause under a generic message.
    """


def _storage_provider() -> str:
    """'r2' or 'supabase' — whichever THIS process's env resolves to."""
    try:
        from services.coach_video_storage import coach_videos_use_r2
        return "r2" if coach_videos_use_r2() else "supabase"
    except Exception:
        return "unknown"


def stale_minutes() -> int:
    """How long a silent heartbeat means 'the worker is dead'."""
    return max(2, _int_env("PIPELINE_JOB_STALE_MINUTES", 15))


def heartbeat_interval_seconds() -> int:
    return max(10, _int_env("PIPELINE_JOB_HEARTBEAT_SECONDS", 60))


# ── enqueue (web process) ────────────────────────────────────────────────

def enqueue_session_recording_job(
    *,
    session_id: str,
    user_id: Optional[str],
    recording_id: str,
    bucket: str,
    storage_key: str,
    filename: str,
    session_context: Optional[dict],
    parent_audio_url: str,
    recording_kind: str,
    paired_session_id: Optional[str],
    arc_id: Optional[str],
    take_index: Optional[int],
    arc_take_count: Optional[int],
    spark_enabled: bool,
) -> Optional[Dict[str, Any]]:
    """Create the durable job row + hand it to the broker.

    Returns the job row on success, None on ANY failure — the caller falls
    back to the daemon/sync path, so a dead Redis can never block an
    upload (live loop).
    """
    if not job_queue.queue_configured():
        return None
    dedup_key = f"{KIND_SESSION_RECORDING}:{session_id}"
    payload = {
        "session_id": session_id,
        "user_id": user_id,
        "recording_id": recording_id,
        "bucket": bucket,
        # Which storage the WEB side actually wrote these bytes to. The
        # worker resolves its own provider from ITS env, and the two can
        # silently disagree: R2 needs three secrets, and a worker missing
        # them falls back to Supabase Storage and looks for an object that
        # was never put there. Recording the writer's answer turns that
        # into a named config error instead of "missing in storage".
        "storage_provider": _storage_provider(),
        "storage_key": storage_key,
        "filename": filename,
        "session_context": session_context,
        "parent_audio_url": parent_audio_url,
        "recording_kind": recording_kind,
        "paired_session_id": paired_session_id,
        "arc_id": arc_id,
        "take_index": take_index,
        "arc_take_count": arc_take_count,
        "spark_enabled": bool(spark_enabled),
    }
    row = db.create_processing_job(
        kind=KIND_SESSION_RECORDING,
        user_id=user_id,
        session_id=session_id,
        dedup_key=dedup_key,
        payload=payload,
        max_attempts=_int_env("PIPELINE_JOB_MAX_ATTEMPTS", 3),
    )
    if row is None:
        # Most likely the partial-unique dedup index: an ACTIVE job already
        # holds this session (double-click / replay) — collapse onto it.
        existing = db.get_active_processing_job_by_dedup(dedup_key)
        if existing:
            logger.info("pipeline_jobs: dedup hit sid=%s job=%s",
                        session_id, existing.get("id"))
            return existing
        return None
    job_id = str(row.get("id"))
    if not job_queue.enqueue(TASK_PATH, job_id):
        # Row without delivery would strand the session once the route
        # 202s — fail it NOW so the route falls back to sync instead.
        db.finish_processing_job(
            job_id, "failed", error="enqueue failed (broker unreachable)",
        )
        return None
    return row


# ── the worker task ──────────────────────────────────────────────────────

class _Heartbeat:
    """Stamps heartbeat_at on a background thread while the pipeline runs,
    so a multi-minute Whisper call doesn't read as a dead worker."""

    def __init__(self, job_id: str):
        self._job_id = job_id
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        from datetime import datetime, timezone
        while not self._stop.wait(heartbeat_interval_seconds()):
            db.update_processing_job(self._job_id, {
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            })

    def __enter__(self) -> "_Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()


def _heartbeat_is_fresh(job: Dict[str, Any]) -> bool:
    """True if the job's heartbeat is recent enough that another worker is
    plausibly still running it."""
    from datetime import datetime, timedelta, timezone
    raw = job.get("heartbeat_at") or job.get("started_at")
    if not raw:
        return False
    try:
        ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts) < timedelta(
        minutes=stale_minutes())


def _fail_terminal(job: Dict[str, Any], error: str) -> None:
    """Out of attempts (or unrunnable): terminal 'failed' + flip the
    session to analysis_state 'failed' so the FE stops polling and offers
    re-record — a session must NEVER stay in 'processing' forever."""
    job_id = str(job.get("id"))
    db.finish_processing_job(job_id, "failed", error=error)
    sid = job.get("session_id")
    if sid:
        try:
            db.set_session_analysis_state(str(sid), "failed", error)
        except Exception as e:
            logger.warning("pipeline_jobs: analysis_state failed-write "
                           "sid=%s: %s", sid, e)


def _retry_backoff_seconds(attempts: int) -> int:
    """60s, 120s, 240s… capped at 10 min."""
    return min(600, 60 * (2 ** max(0, attempts - 1)))


def _cleanup_before_rerun(payload: Dict[str, Any]) -> None:
    """Make a re-run safe: drop the partial artifacts a killed run may have
    left. Everything else the pipeline writes is idempotent already —
    candidate windows UPSERT (db.insert_candidate_windows), the token
    charge dedups on recording_id (services/token_account.charge), slide
    transcripts / boundary metrics are set_-overwrites, and the cadence /
    ideal-text stages dedup per arc/version by construction."""
    rec_id = payload.get("recording_id")
    sid = payload.get("session_id")
    if rec_id:
        try:
            n = db.v2_delete_lab_snippets_for_recording(str(rec_id))
            if n:
                logger.info("pipeline_jobs: rerun cleanup removed %d "
                            "snippet(s) rec=%s", n, rec_id)
        except Exception as e:
            logger.warning("pipeline_jobs: snippet cleanup failed rec=%s: %s",
                           rec_id, e)
    if sid:
        try:
            db.delete_coach_snippet_drafts_for_session(str(sid))
        except Exception as e:
            logger.warning("pipeline_jobs: draft cleanup failed sid=%s: %s",
                           sid, e)


def _run_session_recording(job: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one attempt of the full analysis for a claimed job.
    Raises on failure — the caller decides retry vs terminal."""
    from services.analysis_worker import run_full_analysis
    from services.lab_audio_storage import get_lab_audio_bytes

    job_id = str(job.get("id"))
    payload = dict(job.get("payload") or {})
    if int(job.get("attempts") or 1) > 1:
        _cleanup_before_rerun(payload)

    db.update_processing_job(job_id, {
        "stage": "fetch_audio", "percent": 5,
        "message": "Loading your recording…",
    })
    # Provider agreement, checked BEFORE the download so the failure names
    # its cause. R2 is gated on THREE secrets (R2_ACCOUNT_ID / ACCESS_KEY_ID
    # / SECRET_ACCESS_KEY); a worker missing them silently resolves to
    # Supabase and hunts every bucket for an object the web service put in
    # R2. Without this the symptom is "not found — tried: a, b, c", which
    # reads like a missing file rather than a missing credential.
    wrote = str(payload.get("storage_provider") or "").strip()
    reads = _storage_provider()
    if wrote and wrote != "unknown" and reads != wrote:
        raise ConfigMismatchError(
            f"storage mismatch: the upload wrote to {wrote!r} but this "
            f"worker resolves storage to {reads!r}. Set the R2 credentials "
            f"(R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY) on "
            f"the worker service so it reads where the web service writes."
        )

    # The payload records the bucket the upload actually landed in; the
    # helper tries that first and falls back across the others, so a job
    # enqueued either side of the lab-bucket split still finds its audio
    # (P0 audit 2026-08-03).
    audio_bytes = get_lab_audio_bytes(
        str(payload.get("storage_key") or ""),
        bucket_hint=str(payload.get("bucket") or "") or None,
    )
    if not audio_bytes:
        raise RuntimeError("audio object empty or missing in storage")

    def _progress(stage: str, percent: int, message: Optional[str]) -> None:
        db.update_processing_job(job_id, {
            "stage": stage, "percent": max(0, min(100, int(percent))),
            "message": message,
        })

    readout, sent = run_full_analysis(
        session_id=str(payload.get("session_id")),
        user_id=payload.get("user_id"),
        recording_id=str(payload.get("recording_id")),
        audio_bytes=audio_bytes,
        filename=str(payload.get("filename") or "lab.webm"),
        session_context=payload.get("session_context"),
        parent_audio_url=str(payload.get("parent_audio_url") or ""),
        recording_kind=str(payload.get("recording_kind") or "spoken"),
        paired_session_id=payload.get("paired_session_id"),
        arc_id=payload.get("arc_id"),
        take_index=payload.get("take_index"),
        arc_take_count=payload.get("arc_take_count"),
        spark_enabled=bool(payload.get("spark_enabled")),
        progress=_progress,
    )
    # Small mechanical summary only — the readout itself is served by the
    # existing GETs, and job rows never carry scores/verdicts (AC-9).
    return {
        "snippet_count": len((readout or {}).get("snippets") or []),
        "sent_to_coach": bool(sent),
    }


_KIND_RUNNERS = {
    KIND_SESSION_RECORDING: _run_session_recording,
}


def run_processing_job(job_id: str) -> None:
    """RQ entrypoint. At-least-once safe: every guard below assumes this
    exact call can be delivered twice."""
    job = db.get_processing_job(str(job_id))
    if not job:
        logger.warning("pipeline_jobs: unknown job %s", job_id)
        return
    status = str(job.get("status") or "")
    if status in ("completed", "failed"):
        return  # duplicate delivery of a finished job — no-op
    attempts = int(job.get("attempts") or 0)
    max_attempts = int(job.get("max_attempts") or 3)
    if status == "processing" and _heartbeat_is_fresh(job):
        return  # another worker is live on it — let it finish
    if attempts >= max_attempts:
        _fail_terminal(job, str(job.get("error") or "attempt cap reached"))
        return
    runner = _KIND_RUNNERS.get(str(job.get("kind") or ""))
    if runner is None:
        _fail_terminal(job, f"unknown job kind: {job.get('kind')}")
        return

    claimed = db.claim_processing_job(str(job.get("id")), attempts)
    if not claimed:
        return  # lost the claim race — exactly one runner proceeds

    jid = str(claimed.get("id"))
    # Belt-and-braces state stamp: the web route sets 'processing' after a
    # successful enqueue, but if it crashed in between, the FE poll contract
    # still gets the right state from here. Idempotent.
    if claimed.get("session_id"):
        try:
            db.set_session_analysis_state(
                str(claimed["session_id"]), "processing")
        except Exception as se:
            logger.warning("pipeline_jobs: processing-state write sid=%s: %s",
                           claimed.get("session_id"), se)
    try:
        with _Heartbeat(jid):
            result = runner(claimed)
        db.finish_processing_job(jid, "completed", result=result)
        sid = claimed.get("session_id")
        if sid:
            db.set_session_analysis_state(str(sid), "ready")
        logger.info("pipeline_jobs: job %s completed (attempt %d)",
                    jid, claimed.get("attempts"))
    except ConfigMismatchError as cfg_err:
        # No retry can fix an env var. Burning three attempts plus two
        # backoff waits (3+ minutes) on it only buries the cause under a
        # generic "attempt cap reached". Fail once, loudly, with the fix.
        sentry_sdk.capture_exception(cfg_err)
        logger.error("pipeline_jobs: job %s misconfigured, not retrying: %s",
                     jid, cfg_err)
        _fail_terminal(claimed, str(cfg_err)[:500])
        return
    except Exception as err:
        sentry_sdk.capture_exception(err)
        used = int(claimed.get("attempts") or 1)
        logger.error("pipeline_jobs: job %s attempt %d/%d failed: %s",
                     jid, used, max_attempts, err, exc_info=True)
        if used >= max_attempts:
            _fail_terminal(claimed, str(err)[:500])
            return
        db.release_processing_job_for_retry(jid, str(err)[:500])
        if not job_queue.enqueue(
            TASK_PATH, jid, delay_seconds=_retry_backoff_seconds(used),
        ):
            # Broker down mid-retry: leave the row 'pending' — the sweeper
            # re-enqueues it once the broker is back.
            logger.warning("pipeline_jobs: retry enqueue failed job=%s "
                           "(sweeper will recover)", jid)


# ── the sweeper ──────────────────────────────────────────────────────────

def sweep_stale_jobs(max_rows: int = 100) -> Dict[str, int]:
    """Recover jobs the queue lost track of. Safe to run from anywhere,
    any number of times — recovery re-enters run_processing_job, whose
    claim CAS dedups racing runners."""
    counts = {"requeued": 0, "failed": 0}
    for job in db.list_stale_processing_jobs(
        stale_minutes=stale_minutes(), max_rows=max_rows,
    ):
        jid = str(job.get("id"))
        attempts = int(job.get("attempts") or 0)
        max_attempts = int(job.get("max_attempts") or 3)
        if attempts >= max_attempts:
            _fail_terminal(job, str(
                job.get("error") or "worker lost; attempt cap reached"))
            counts["failed"] += 1
            continue
        if str(job.get("status")) == "processing":
            db.release_processing_job_for_retry(
                jid, "worker lost (stale heartbeat) — requeued")
        if job_queue.enqueue(TASK_PATH, jid):
            counts["requeued"] += 1
            logger.info("pipeline_jobs: sweeper requeued job %s "
                        "(attempts %d/%d)", jid, attempts, max_attempts)
        else:
            logger.warning("pipeline_jobs: sweeper enqueue failed job=%s "
                           "(broker down?)", jid)
    # Additive and strictly best-effort: the orphan pass is a newer, softer
    # concern than job recovery, and must never be able to break it.
    try:
        counts["orphans_failed"] = sweep_orphaned_sessions(max_rows=max_rows)
    except Exception as e:
        logger.warning("pipeline_jobs: orphan sweep failed: %s", e)
        counts["orphans_failed"] = 0
    return counts


def orphan_stale_minutes() -> int:
    """How long a 'processing' session with no job may sit before it is
    presumed stranded. Deliberately longer than the JOB staleness window —
    a job row is protection, and a session without one gets more rope."""
    return max(5, _int_env("PIPELINE_ORPHAN_STALE_MINUTES", 30))


def sweep_orphaned_sessions(max_rows: int = 100) -> int:
    """Fail sessions stuck on analysis_state='processing' with NO active job.

    Without this the queue sweeper's promise ("a session NEVER strands in
    processing") had a hole: it only recovered rows in processing_jobs, so a
    session flipped to 'processing' whose job was never created — the
    pre-queue daemon path, or a crash-looping worker window — showed
    "Working on your take" forever, with nothing alive to finish it.

    Terminal 'failed' is the right landing: there is no audio job to resume
    (a real one would have a job row protecting it), and 'failed' is what
    makes the FE stop polling and offer a re-record. Returns the count.
    """
    n = 0
    for row in db.list_orphaned_processing_sessions(
        stale_minutes=orphan_stale_minutes(), max_rows=max_rows,
    ):
        sid = str(row.get("id") or "")
        if not sid:
            continue
        try:
            db.set_session_analysis_state(
                sid, "failed",
                "analysis was interrupted and could not be resumed — "
                "please record again",
            )
            n += 1
            logger.info("pipeline_jobs: orphaned session %s failed "
                        "(created %s, no active job)", sid,
                        row.get("created_at"))
        except Exception as e:
            logger.warning("pipeline_jobs: orphan reap failed sid=%s: %s",
                           sid, e)
    return n


SWEEP_LOOP_PATH = "services.pipeline_jobs.run_sweep_loop"


def sweep_interval_seconds() -> int:
    return max(60, _int_env("PIPELINE_SWEEP_INTERVAL_SECONDS", 300))


def run_sweep_loop() -> None:
    """Self-rescheduling sweep, run THROUGH the queue (RQ entrypoint).

    Runs in a forked work horse — deliberately NOT a thread inside the RQ
    worker parent, because a db-touching thread there would share inherited
    httpx sockets with forked job children. Each worker boot (worker.py)
    starts a chain; multiple replicas → multiple chains, which is harmless
    (sweeps are CAS-guarded and cheap when nothing is stale). A Redis wipe
    kills the chain; the next worker boot recreates it, and the web-boot
    sweep + POST /v2/internal/jobs/sweep remain as backstops."""
    try:
        counts = sweep_stale_jobs()
        if counts.get("requeued") or counts.get("failed"):
            logger.info("pipeline_jobs: sweep loop %s", counts)
    finally:
        job_queue.enqueue(
            SWEEP_LOOP_PATH, delay_seconds=sweep_interval_seconds(),
        )
