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

from contextlib import nullcontext
import logging
import os
import threading
from typing import Any, Dict, Optional

import sentry_sdk

from services import job_queue
from services.db import db
from services.ideal_text_confirmation import (
    IdealTextUnconfirmedError,
    build_initial_ideal_text_from_stored_artifacts,
    mark_ideal_text_unconfirmed,
)
from services.take_lifecycle import (
    TakeLifecycleError,
    confidence_source_manifest,
    complete_attempt,
    transition_attempt,
)

logger = logging.getLogger(__name__)

# Dotted path RQ resolves in the worker — the web process enqueues the
# string and never imports the analysis stack.
TASK_PATH = "services.pipeline_jobs.run_processing_job"

KIND_SESSION_RECORDING = "session_recording"
KIND_IDEAL_TEXT_RETRY = "ideal_text_retry"
TAKE_LIFECYCLE_CONTRACT = "recording-attempt-v1"


def _has_canonical_attempt(job: Dict[str, Any]) -> bool:
    payload = dict(job.get("payload") or {})
    if payload.get("lifecycle_contract_version") != TAKE_LIFECYCLE_CONTRACT:
        return False
    marker = payload.get("canonical_attempt_registered")
    if marker is True:
        return True
    if marker is False:
        return False

    # Production repair for jobs created before the producer began carrying
    # the registration proof.  That producer stamped every queued job with the
    # lifecycle version even though only the canary owner received an Attempt
    # row.  Resolve those already-durable jobs against the database: a real
    # canary Attempt remains strict; a job with no Attempt resumes the legacy
    # product path.  New jobs never enter this compatibility branch.
    getter = getattr(db, "get_recording_attempt", None)
    session_id = str(job.get("session_id") or payload.get("session_id") or "")
    if not session_id or not callable(getter):
        return False
    return bool(getter(session_id))


def _job_attempt_input(job: Dict[str, Any]) -> dict:
    payload = dict(job.get("payload") or {})
    return {
        "job_id": job.get("id"),
        "job_kind": job.get("kind"),
        "job_created_at": job.get("created_at"),
        "job_started_at": job.get("started_at"),
        "attempt_count": int(job.get("attempts") or 1),
        "session_id": payload.get("session_id") or job.get("session_id"),
        "recording_id": payload.get("recording_id"),
        "recording_kind": payload.get("recording_kind") or "spoken",
        "project_id": payload.get("arc_id"),
        "storage_provider": payload.get("storage_provider"),
        "storage_key": payload.get("storage_key"),
    }


def _transition_job_attempt(
    job: Dict[str, Any], to_status: str, stage: str,
    *, error: Optional[BaseException] = None,
) -> Optional[dict]:
    """Advance a new canonical Attempt; preserve explicit legacy parity."""
    if not _has_canonical_attempt(job):
        return None
    session_id = str(job.get("session_id") or "")
    if not session_id:
        raise TakeLifecycleError("canonical processing job has no session")
    return transition_attempt(
        database=db,
        attempt_id=session_id,
        to_status=to_status,
        stage=stage,
        attempt_count=max(1, int(job.get("attempts") or 1)),
        processing_job_id=str(job.get("id") or "") or None,
        input_provenance=_job_attempt_input(job),
        error=error,
    )


def _complete_job_attempt(job: Dict[str, Any], result: Any) -> Optional[dict]:
    if not _has_canonical_attempt(job):
        return None
    payload = dict(job.get("payload") or {})
    session_id = str(job.get("session_id") or payload.get("session_id") or "")
    if not session_id:
        raise TakeLifecycleError("canonical processing job has no session")
    result_payload = dict(result) if isinstance(result, dict) else result
    confidence_manifest = None
    if isinstance(result_payload, dict):
        confidence_manifest = result_payload.pop(
            "_confidence_producer_manifest", None
        )
        if isinstance(result, dict):
            result.pop("_confidence_producer_manifest", None)
    return complete_attempt(
        database=db,
        attempt_id=session_id,
        recording_kind=str(payload.get("recording_kind") or "spoken"),
        result=result_payload,
        attempt_count=max(1, int(job.get("attempts") or 1)),
        processing_job_id=str(job.get("id") or "") or None,
        input_provenance=_job_attempt_input(job),
        confidence_producer_manifest=confidence_manifest,
    )


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
        from services.lab_audio_storage import storage_provider

        return storage_provider()
    except Exception:
        return "unknown"


def stale_minutes() -> int:
    """How long a silent heartbeat means 'the worker is dead'.

    Heartbeats arrive every 60 seconds by default.  Five minutes preserves a
    safe margin for CPU-heavy audio work that can temporarily starve the
    heartbeat thread, while the one-minute sweep still cuts the old
    15-to-20-minute recovery gap to at most six minutes.
    """
    return max(2, _int_env("PIPELINE_JOB_STALE_MINUTES", 5))


def heartbeat_interval_seconds() -> int:
    return max(10, _int_env("PIPELINE_JOB_HEARTBEAT_SECONDS", 60))


# ── enqueue (web process) ────────────────────────────────────────────────

def _sync_phase1_job(
    job: Dict[str, Any], status: str, *, error: Exception | str | None = None,
) -> None:
    """Mirror a runtime job transition into the canonical Phase-1 boundary."""
    payload = dict(job.get("payload") or {})
    if not payload.get("phase1_boundary_registered"):
        return
    from services.processing_authorization import ProcessingAuthorizationService

    ProcessingAuthorizationService(db).sync_processing_job(
        attempt_id=str(payload.get("session_id") or job.get("session_id") or ""),
        runtime_job_id=str(job.get("id") or "") or None,
        status=status,
        attempts=int(job.get("attempts") or 0),
        error_code=(type(error).__name__ if isinstance(error, Exception)
                    else str(error)[:160] if error else None),
    )

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
    canonical_attempt_registered: bool = False,
    phase1_boundary_registered: bool = False,
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
    if canonical_attempt_registered:
        payload.update({
            "lifecycle_contract_version": TAKE_LIFECYCLE_CONTRACT,
            "canonical_attempt_registered": True,
        })
    if phase1_boundary_registered:
        payload["phase1_boundary_registered"] = True
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
    try:
        _sync_phase1_job(row, "pending")
    except Exception as error:
        db.finish_processing_job(
            job_id, "failed", error=f"Phase-1 job sync failed: {error}",
        )
        return None
    if not job_queue.enqueue(TASK_PATH, job_id):
        # Row without delivery would strand the session once the route
        # 202s — fail it NOW so the route falls back to sync instead.
        db.finish_processing_job(
            job_id, "failed", error="enqueue failed (broker unreachable)",
        )
        return None
    return row


def enqueue_ideal_text_retry_job(
    *,
    session_id: str,
    user_id: Optional[str],
    arc_id: str,
    take_index: int,
) -> Optional[Dict[str, Any]]:
    """Enqueue Take 1 document generation from stored analysis artifacts.

    The deliberately tiny payload is the architectural boundary: it has no
    bucket, storage key, recording id, filename, or audio bytes, so this job
    cannot upload, download, or transcribe the take. Repeated taps collapse on
    one active dedup key; a later tap after terminal failure creates one fresh
    attempt without touching the original full-pipeline job.
    """
    if (
        not session_id
        or not arc_id
        or isinstance(take_index, bool)
        or take_index != 1
        or not job_queue.queue_configured()
    ):
        return None
    dedup_key = f"{KIND_IDEAL_TEXT_RETRY}:{session_id}"
    payload = {
        "session_id": str(session_id),
        "user_id": str(user_id) if user_id else None,
        "arc_id": str(arc_id),
        "take_index": 1,
    }
    canonical_attempt = db.get_recording_attempt(str(session_id))
    if (isinstance(canonical_attempt, dict)
            and canonical_attempt.get("id")):
        payload["lifecycle_contract_version"] = TAKE_LIFECYCLE_CONTRACT
    row = db.create_processing_job(
        kind=KIND_IDEAL_TEXT_RETRY,
        user_id=user_id,
        session_id=str(session_id),
        dedup_key=dedup_key,
        payload=payload,
        # A confirmation timeout is already the terminal boundary. Repeating
        # the whole 120-second document attempt automatically would contradict
        # the explicit user action this job represents.
        max_attempts=1,
    )
    if row is None:
        existing = db.get_active_processing_job_by_dedup(dedup_key)
        if existing:
            return existing
        return None
    job_id = str(row.get("id"))
    if not job_queue.enqueue(TASK_PATH, job_id):
        db.finish_processing_job(
            job_id, "failed", error="enqueue failed (broker unreachable)",
        )
        return None
    db.set_session_analysis_state(str(session_id), "processing")
    return row


def retry_failed_session_job(session_id: str, user_id: str = "") -> Optional[dict]:
    """Requeue the stored recording; never asks the user to record again."""
    if not session_id or not job_queue.queue_configured():
        return None
    job = db.get_latest_processing_job_by_session(str(session_id))
    if (not job
            or str(job.get("kind") or "") != KIND_SESSION_RECORDING
            or str(job.get("user_id") or "") != str(user_id)):
        return None
    status = str(job.get("status") or "")
    if status in ("pending", "processing"):
        return job
    if status != "failed":
        return None
    job_id = str(job.get("id") or "")
    if not job_id or not db.reset_processing_job_for_manual_retry(job_id):
        return None
    reopened = {**job, "status": "pending", "attempts": 1}
    try:
        _sync_phase1_job(reopened, "pending")
    except Exception:
        db.finish_processing_job(
            job_id, "failed", error="Phase-1 retry authorization failed",
        )
        return None
    try:
        _transition_job_attempt(reopened, "processing", "manual_retry")
    except TakeLifecycleError as error:
        db.finish_processing_job(job_id, "failed", error=str(error)[:500])
        return None
    if not job_queue.enqueue(TASK_PATH, job_id):
        db.finish_processing_job(job_id, "failed", error="enqueue failed")
        try:
            _transition_job_attempt(
                reopened, "failed", "manual_retry_delivery",
                error=RuntimeError("enqueue failed"),
            )
        except TakeLifecycleError:
            logger.exception(
                "pipeline_jobs: manual retry failure transition missing "
                "sid=%s", session_id,
            )
        return None
    db.set_session_analysis_state(str(session_id), "processing")
    return db.get_processing_job(job_id) or {**job, "status": "pending"}


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
    try:
        _transition_job_attempt(
            job, "failed", "analysis", error=RuntimeError(error),
        )
    except TakeLifecycleError:
        logger.exception(
            "pipeline_jobs: terminal Attempt transition missing job=%s",
            job_id,
        )
    db.finish_processing_job(job_id, "failed", error=error)
    try:
        _sync_phase1_job(job, "failed", error=error)
    except Exception as sync_error:
        logger.error(
            "pipeline_jobs: Phase-1 terminal sync failed job=%s: %s",
            job_id, sync_error,
        )
    sid = job.get("session_id")
    if sid:
        try:
            db.set_session_analysis_state(str(sid), "failed", error)
        except Exception as e:
            logger.warning("pipeline_jobs: analysis_state failed-write "
                           "sid=%s: %s", sid, e)


def _fail_ideal_text_unconfirmed(
    job: Dict[str, Any], error: Exception,
) -> None:
    """One non-retriable Take 1 boundary; never re-run the full pipeline."""
    job_id = str(job.get("id"))
    try:
        _transition_job_attempt(
            job,
            "failed_ideal_text_unconfirmed",
            "ideal_text_confirmation",
            error=error,
        )
    except TakeLifecycleError:
        logger.exception(
            "pipeline_jobs: Ideal Text Attempt transition missing job=%s",
            job_id,
        )
    db.finish_processing_job(job_id, "failed", error=str(error)[:500])
    payload = dict(job.get("payload") or {})
    mark_ideal_text_unconfirmed(
        db,
        session_id=payload.get("session_id") or job.get("session_id"),
        user_id=payload.get("user_id") or job.get("user_id"),
        arc_id=payload.get("arc_id"),
        take_index=payload.get("take_index"),
        error=error,
    )


def _fail_terminal_for_job(job: Dict[str, Any], error: Exception | str) -> None:
    """Keep document-only retries inside their dedicated failure boundary."""
    if str(job.get("kind") or "") == KIND_IDEAL_TEXT_RETRY:
        exc = error if isinstance(error, Exception) else RuntimeError(str(error))
        _fail_ideal_text_unconfirmed(job, exc)
        return
    _fail_terminal(job, str(error)[:500])


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
    from services.authorized_provider import (
        AuthorizedProviderAdapter,
        ProviderCoordinates,
    )

    job_id = str(job.get("id"))
    payload = dict(job.get("payload") or {})
    if int(job.get("attempts") or 1) > 1:
        _cleanup_before_rerun(payload)

    # Canonical stage provenance is additive during parity. It binds every
    # attempt to database-resolved owner/project/take UUIDs; a legacy or guest
    # row that has not completed canonical ownership binding simply keeps the
    # existing job behavior and is visible to the parity audit as missing.
    from services.processing_stages import recorder_for_take

    _stage_session_getter = getattr(db, "v2_get_session_by_id", None)
    _stage_session = (
        _stage_session_getter(str(payload.get("session_id") or "")) or {}
        if callable(_stage_session_getter) else {}
    )
    _stage_recorder = recorder_for_take(
        database=db,
        session=_stage_session,
        attempt_count=int(job.get("attempts") or 1),
        processing_job_id=job_id,
        input_provenance={
            "kind": job.get("kind"),
            "session_id": payload.get("session_id"),
            "recording_id": payload.get("recording_id"),
            "storage_provider": payload.get("storage_provider"),
            "storage_key": payload.get("storage_key"),
            "recording_kind": payload.get("recording_kind"),
            "take_index": payload.get("take_index"),
        },
    )

    db.update_processing_job(job_id, {
        "stage": "processing_recording", "percent": 5,
        "message": "Loading your recording…",
    })
    # Provider agreement, checked BEFORE the download so the failure names
    # its cause. R2 is gated on THREE secrets (R2_ACCOUNT_ID / ACCESS_KEY_ID
    # / SECRET_ACCESS_KEY); a worker missing them silently resolves to
    # Supabase and hunts every bucket for an object the web service put in
    # R2. Without this the symptom is "not found — tried: a, b, c", which
    # reads like a missing file rather than a missing credential.
    _upload_scope = (
        _stage_recorder.stage("upload")
        if _stage_recorder is not None else nullcontext()
    )
    with _upload_scope:
        wrote = str(payload.get("storage_provider") or "").strip()
        reads = _storage_provider()
        if wrote and wrote != "unknown" and reads != wrote:
            raise ConfigMismatchError(
                f"storage mismatch: the upload wrote to {wrote!r} but this "
                f"worker resolves storage to {reads!r}. Set the R2 "
                f"credentials (R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, "
                f"R2_SECRET_ACCESS_KEY) on the worker service so it reads "
                f"where the web service writes."
            )

        from services.processing_authorization import ProcessingAuthorizationService
        authorization = ProcessingAuthorizationService(db)
        principal_id = authorization.resolve_acquisition_principal(
            str(_stage_session.get("owner_principal_id") or ""),
            user_id=str(_stage_session.get("user_id") or "") or None,
            recording_id=str(payload.get("recording_id") or "") or None,
        )
        adapter = AuthorizedProviderAdapter(
            db,
            ProviderCoordinates(
                acquisition_principal_id=principal_id,
                take_id=str(payload.get("session_id") or ""),
                recording_id=str(payload.get("recording_id") or ""),
            ),
            authorization=authorization,
        )
        # The adapter issues a typed permit immediately before storage access.
        # Its underlying storage helper still handles the lab-bucket cutover.
        audio_bytes = adapter.download_audio(
            storage_provider=str(payload.get("storage_provider") or ""),
            bucket=str(payload.get("bucket") or ""),
            object_key=str(payload.get("storage_key") or ""),
            idempotency_key=f"audio-download:{job_id}:{job.get('attempts') or 1}",
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
        stage_recorder=_stage_recorder,
    )
    # Small mechanical summary only — the readout itself is served by the
    # existing GETs, and job rows never carry scores/verdicts (AC-9).
    result: Dict[str, Any] = {
        "snippet_count": len((readout or {}).get("snippets") or []),
        "sent_to_coach": bool(sent),
    }
    _confidence_manifest = confidence_source_manifest(
        audio_bytes=audio_bytes,
        bucket=str(payload.get("bucket") or ""),
        object_key=str(payload.get("storage_key") or ""),
        filename=str(payload.get("filename") or "lab.webm"),
    )
    if _confidence_manifest is not None:
        result["_confidence_producer_manifest"] = _confidence_manifest
    if (payload.get("recording_kind") == "spoken"
            and payload.get("take_index") == 1
            and not isinstance(payload.get("take_index"), bool)):
        # run_full_analysis cannot reach this return until its database read
        # confirmed the document. Stamp that proof into the durable job row as
        # well, so inspection never has to infer Take 1 success from 100%.
        result["ideal_text_confirmed"] = True
    return result


def _run_ideal_text_retry(job: Dict[str, Any]) -> Dict[str, Any]:
    """Regenerate only Take 1's document from persisted transcript artifacts."""
    job_id = str(job.get("id"))
    payload = dict(job.get("payload") or {})
    session_id = str(payload.get("session_id") or "")
    arc_id = str(payload.get("arc_id") or "")
    take_index = payload.get("take_index")
    if (not session_id or not arc_id or isinstance(take_index, bool)
            or take_index != 1):
        raise ConfigMismatchError(
            "ideal-text retry requires one Take 1 session and project"
        )
    db.update_processing_job(job_id, {
        "stage": "ideal_text", "percent": 90,
        "message": "Building your Ideal Text…",
    })
    from services.authorized_provider import (
        AuthorizedProviderAdapter,
        ProviderCoordinates,
        protected_provider_scope,
    )
    from services.processing_authorization import ProcessingAuthorizationService

    session = db.v2_get_session_by_id(session_id) or {}
    recording_id = str(
        payload.get("recording_id") or session.get("recording_id") or ""
    )
    authorization = ProcessingAuthorizationService(db)
    principal_id = authorization.resolve_acquisition_principal(
        str(session.get("owner_principal_id") or ""),
        user_id=str(session.get("user_id") or "") or None,
        recording_id=recording_id,
    )
    if authorization.enforced and (not principal_id or not recording_id):
        from services.processing_authorization import ProcessingAuthorizationError
        raise ProcessingAuthorizationError(
            "PROCESSING_PRINCIPAL_UNRESOLVED",
            "The stored Take authority could not be resolved.",
            403,
        )
    adapter = AuthorizedProviderAdapter(
        db,
        ProviderCoordinates(principal_id, session_id, recording_id),
        authorization=authorization,
    )
    with protected_provider_scope(
        adapter,
        idempotency_prefix=f"ideal-text-retry:{job_id}:{job.get('attempts') or 1}",
    ):
        row = build_initial_ideal_text_from_stored_artifacts(
            db,
            arc_id,
            source_session_id=session_id,
            include_suggestion_anchors=True,
        )
    user_id = payload.get("user_id") or job.get("user_id")
    if user_id:
        try:
            from services.arc_notifications import fire_ideal_version_ready

            fire_ideal_version_ready(
                db,
                user_id,
                arc_id,
                row.get("version") or 1,
                spoken_take_count=1,
            )
        except Exception as notify_error:
            # Database confirmation is the success gate. The ready card is an
            # idempotent delivery side effect and must not turn a confirmed
            # document back into a failed job.
            logger.warning(
                "pipeline_jobs: ideal retry notification failed sid=%s: %s",
                session_id,
                notify_error,
            )
    return {
        "ideal_text_confirmed": True,
        "version": row.get("version") or 1,
    }


_KIND_RUNNERS = {
    KIND_SESSION_RECORDING: _run_session_recording,
    KIND_IDEAL_TEXT_RETRY: _run_ideal_text_retry,
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
        # A previous delivery may have committed the operational job before a
        # transient failure reached the canonical Phase-1 ledger.  Terminal
        # re-delivery is therefore a reconciliation opportunity, not a pure
        # no-op.  The canonical RPC is idempotent and refuses contradictions.
        try:
            _sync_phase1_job(
                job, status, error=(job.get("error") if status == "failed" else None),
            )
        except Exception as sync_error:
            sentry_sdk.capture_exception(sync_error)
            logger.error(
                "pipeline_jobs: terminal Phase-1 reconciliation failed "
                "job=%s status=%s: %s", job_id, status, sync_error,
            )
        return
    attempts = int(job.get("attempts") or 0)
    max_attempts = int(job.get("max_attempts") or 3)
    if status == "processing" and _heartbeat_is_fresh(job):
        return  # another worker is live on it — let it finish
    if attempts >= max_attempts:
        _fail_terminal_for_job(
            job, str(job.get("error") or "attempt cap reached"))
        return
    runner = _KIND_RUNNERS.get(str(job.get("kind") or ""))
    if runner is None:
        _fail_terminal(job, f"unknown job kind: {job.get('kind')}")
        return

    claimed = db.claim_processing_job(str(job.get("id")), attempts)
    if not claimed:
        return  # lost the claim race — exactly one runner proceeds

    jid = str(claimed.get("id"))
    try:
        _sync_phase1_job(claimed, "processing")
    except Exception as sync_error:
        db.finish_processing_job(
            jid, "failed", error=f"Phase-1 job sync failed: {sync_error}",
        )
        if claimed.get("session_id"):
            db.set_session_analysis_state(
                str(claimed["session_id"]), "failed", str(sync_error),
            )
        return
    try:
        _transition_job_attempt(
            claimed,
            "processing",
            (
                "ideal_text_retry"
                if str(claimed.get("kind") or "") == KIND_IDEAL_TEXT_RETRY
                else "worker"
            ),
        )
    except TakeLifecycleError as lifecycle_error:
        # Never let the compatibility read model claim success when the
        # canonical Attempt history is missing or contradictory.
        sentry_sdk.capture_exception(lifecycle_error)
        _fail_terminal_for_job(claimed, lifecycle_error)
        return
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
        _complete_job_attempt(claimed, result)
        db.finish_processing_job(jid, "completed", result=result)
        try:
            _sync_phase1_job(claimed, "completed")
        except Exception as sync_error:
            # Product work is already durable and must not be run again solely
            # because ledger synchronization had a transient failure.  Queue
            # the terminal row: the early-return path above reconciles it.
            sentry_sdk.capture_exception(sync_error)
            logger.error(
                "pipeline_jobs: completed Phase-1 sync deferred job=%s: %s",
                jid, sync_error,
            )
            if not job_queue.enqueue(TASK_PATH, jid, delay_seconds=5):
                logger.error(
                    "pipeline_jobs: completed Phase-1 reconciliation enqueue "
                    "failed job=%s", jid,
                )
        sid = claimed.get("session_id")
        if sid:
            db.set_session_analysis_state(str(sid), "ready")
        logger.info("pipeline_jobs: job %s completed (attempt %d)",
                    jid, claimed.get("attempts"))
    except IdealTextUnconfirmedError as ideal_err:
        # Its own terminal outcome: transcription/analysis already persisted,
        # and replaying those stages is expressly forbidden. The only retry is
        # the user's idempotent ideal-text-only action.
        sentry_sdk.capture_exception(ideal_err)
        logger.error(
            "pipeline_jobs: Take 1 Ideal Text unconfirmed job=%s: %s",
            jid, ideal_err,
        )
        _fail_ideal_text_unconfirmed(claimed, ideal_err)
        return
    except ConfigMismatchError as cfg_err:
        # No retry can fix an env var. Burning three attempts plus two
        # backoff waits (3+ minutes) on it only buries the cause under a
        # generic "attempt cap reached". Fail once, loudly, with the fix.
        sentry_sdk.capture_exception(cfg_err)
        logger.error("pipeline_jobs: job %s misconfigured, not retrying: %s",
                     jid, cfg_err)
        _fail_terminal_for_job(claimed, cfg_err)
        return
    except Exception as err:
        sentry_sdk.capture_exception(err)
        used = int(claimed.get("attempts") or 1)
        logger.error("pipeline_jobs: job %s attempt %d/%d failed: %s",
                     jid, used, max_attempts, err, exc_info=True)
        if used >= max_attempts:
            _fail_terminal_for_job(claimed, err)
            return
        try:
            _transition_job_attempt(
                claimed, "retryable", "analysis", error=err,
            )
        except TakeLifecycleError as lifecycle_error:
            sentry_sdk.capture_exception(lifecycle_error)
            _fail_terminal_for_job(claimed, lifecycle_error)
            return
        db.release_processing_job_for_retry(jid, str(err)[:500])
        _sync_phase1_job(claimed, "pending", error=err)
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
            _fail_terminal_for_job(
                job,
                str(job.get("error") or "worker lost; attempt cap reached"),
            )
            counts["failed"] += 1
            continue
        if str(job.get("status")) == "processing":
            db.release_processing_job_for_retry(
                jid, "worker lost (stale heartbeat) — requeued")
            _sync_phase1_job(
                job, "pending", error="worker_lost_stale_heartbeat",
            )
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
    try:
        from services.orphan_audio_cleanup import sweep_phase1_orphan_audio

        object_counts = sweep_phase1_orphan_audio(
            database=db, limit=min(max_rows, 25),
        )
        counts.update({
            f"orphan_objects_{key}": value
            for key, value in object_counts.items()
        })
    except Exception as e:
        # Migration/config may intentionally be absent while the Phase-1
        # boundary is off. Job recovery must remain independent.
        logger.warning("pipeline_jobs: Phase-1 object sweep unavailable: %s", e)
        counts["orphan_objects_claimed"] = 0
        counts["orphan_objects_deleted"] = 0
        counts["orphan_objects_failed"] = 0
    try:
        from services.coach_publish_delivery import sweep_pending_deliveries

        counts["coach_deliveries_requeued"] = sweep_pending_deliveries(
            database=db, limit=max_rows,
        )
    except Exception as e:
        logger.warning("pipeline_jobs: coach delivery sweep failed: %s", e)
        counts["coach_deliveries_requeued"] = 0
    try:
        from services.ideal_text_core_snapshot import (
            sweep_pending_publications,
        )
        counts["ideal_text_publications_requeued"] = (
            sweep_pending_publications(db, limit=max_rows))
    except Exception as e:
        logger.warning(
            "pipeline_jobs: Ideal Text publication sweep failed: %s", e)
        counts["ideal_text_publications_requeued"] = 0
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
    # Recovery is intentionally cheap (two bounded indexed reads).  Running
    # it once a minute keeps the two-minute stale boundary meaningful; a
    # five-minute loop made the real worst case twenty minutes.
    return max(60, _int_env("PIPELINE_SWEEP_INTERVAL_SECONDS", 60))


# The chain's lease runs for this many intervals. >1 so a single slow or
# failed sweep cannot drop the lease and let a second chain start; small
# enough that a genuinely dead chain is taken over within ~15 minutes.
SWEEP_LEASE_INTERVALS = 3


def run_sweep_loop(chain_id: Optional[str] = None) -> None:
    """Self-rescheduling sweep, run THROUGH the queue (RQ entrypoint).

    Runs in a forked work horse — deliberately NOT a thread inside the RQ
    worker parent, because a db-touching thread there would share inherited
    httpx sockets with forked job children.

    OWNERSHIP, CHECKED EVERY ITERATION (2026-08-10, handoff §6.5). The first
    lease only gated STARTING chains, and its `finally` renewed a shared
    presence flag and re-enqueued unconditionally — so the chains that had
    already accumulated (one per pre-lease boot, plus one per >TTL deploy
    gap) were immortal: nine of them, phase-locked, sweeping every five
    minutes. The chain now carries its identity, and re-arming is CONDITIONAL
    on still owning the lease:

      * owner → renew + re-enqueue (the singleton stays immortal, including
        through a sweep body that raised — that is what the `finally` is for);
      * not the owner → this iteration is the chain's last. No re-enqueue,
        no cleanup needed; the duplicate drains itself.
      * chain_id None → a LEGACY payload enqueued before ownership existed
        (they call this with no args). Same answer: die here. The boot-time
        acquire claims the legacy key, so a new-style owner exists the moment
        this code ships.

    A Redis wipe kills the chain; the next worker boot recreates it, and the
    web-boot sweep + POST /v2/internal/jobs/sweep remain as backstops."""
    try:
        counts = sweep_stale_jobs()
        if counts.get("requeued") or counts.get("failed"):
            logger.info("pipeline_jobs: sweep loop %s", counts)
        # Saturation shows up in the worker's own logs, so "should I add
        # slots?" is answerable without opening SQL. Best-effort — an ops
        # signal must never break recovery.
        try:
            from services.pipeline_health import log_saturation
            log_saturation()
        except Exception as he:
            logger.warning("pipeline_jobs: health probe failed: %s", he)
    finally:
        if chain_id and job_queue.renew_sweep_lease(
                chain_id,
                ttl_seconds=sweep_interval_seconds() * SWEEP_LEASE_INTERVALS):
            job_queue.enqueue(
                SWEEP_LOOP_PATH, chain_id,
                delay_seconds=sweep_interval_seconds(),
            )
        else:
            # Loud on purpose: each accumulated chain logs exactly one of
            # these and is gone. Nine of them after the deploy IS the fix
            # working, not a new incident.
            logger.info(
                "pipeline_jobs: sweep chain %s drained (not the lease owner)",
                chain_id or "<legacy>")
