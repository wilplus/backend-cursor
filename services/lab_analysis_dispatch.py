"""Choose queue, daemon, or synchronous execution for Lab analysis."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

import sentry_sdk


@dataclass(frozen=True)
class AnalysisInputs:
    """All request-independent state required by the analysis worker."""

    session_id: str
    user_id: str | None
    recording_id: str
    audio_bytes: bytes
    filename: str
    session_context: dict[str, Any]
    parent_audio_url: str
    recording_kind: str
    paired_session_id: str | None
    arc_id: str | None
    take_index: int | None
    arc_take_count: int | None
    spark_enabled: bool
    bucket: str
    storage_key: str
    duration_seconds: int


@dataclass(frozen=True)
class PendingAnalysis:
    """Analysis was accepted by a background execution mode."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class CompletedAnalysis:
    """Analysis completed synchronously inside the request."""

    readout: dict[str, Any]
    sent_to_coach: bool


def _processing_payload(
    inputs: AnalysisInputs,
    *,
    audit_paid: bool,
    job_id: str | None = None,
) -> dict[str, Any]:
    duration = int(inputs.duration_seconds or 0)
    payload = {
        "status": "processing",
        "state": "processing",
        "session_id": inputs.session_id,
        "recording_id": inputs.recording_id,
        "duration_minutes": round(duration / 60.0, 1),
        "audits_needed": max(1, -(-duration // 600)),
        "session_context": inputs.session_context,
        "readout": None,
        "arc_id": inputs.arc_id,
        "take_index": inputs.take_index,
        "take_count": inputs.arc_take_count,
        "audit_paid": audit_paid,
    }
    if job_id is not None:
        payload["job_id"] = job_id
        payload["job_status_url"] = f"/v2/jobs/{job_id}/status"
    return payload


def dispatch_recording_analysis(
    inputs: AnalysisInputs,
    *,
    database: Any,
    queue_enabled: Callable[[], bool],
    async_enabled: Callable[[], bool],
    audit_paid_for_arc: Callable[[str | None, str | None], bool],
    log: Any,
) -> PendingAnalysis | CompletedAnalysis:
    """Run the canonical worker through exactly one execution mode."""
    from services.analysis_worker import run_full_analysis

    def run_pipeline():
        return run_full_analysis(
            session_id=inputs.session_id,
            user_id=inputs.user_id,
            recording_id=inputs.recording_id,
            audio_bytes=inputs.audio_bytes,
            filename=inputs.filename,
            session_context=inputs.session_context,
            parent_audio_url=inputs.parent_audio_url,
            recording_kind=inputs.recording_kind,
            paired_session_id=inputs.paired_session_id,
            arc_id=inputs.arc_id,
            take_index=inputs.take_index,
            arc_take_count=inputs.arc_take_count,
            spark_enabled=inputs.spark_enabled,
        )

    if queue_enabled():
        from services.pipeline_jobs import enqueue_session_recording_job

        job_row = None
        try:
            job_row = enqueue_session_recording_job(
                session_id=inputs.session_id,
                user_id=inputs.user_id,
                recording_id=inputs.recording_id,
                bucket=inputs.bucket,
                storage_key=inputs.storage_key,
                filename=inputs.filename,
                session_context=inputs.session_context,
                parent_audio_url=inputs.parent_audio_url,
                recording_kind=inputs.recording_kind,
                paired_session_id=inputs.paired_session_id,
                arc_id=inputs.arc_id,
                take_index=inputs.take_index,
                arc_take_count=inputs.arc_take_count,
                spark_enabled=inputs.spark_enabled,
            )
        except Exception as exc:
            log.warning(
                "lab: queue enqueue raised sid=%s: %s (falling back)",
                inputs.session_id,
                exc,
            )
        if job_row:
            database.set_session_analysis_state(inputs.session_id, "processing")
            job_id = str(job_row.get("id"))
            return PendingAnalysis(_processing_payload(
                inputs,
                job_id=job_id,
                audit_paid=audit_paid_for_arc(inputs.arc_id, inputs.user_id),
            ))
        log.warning(
            "lab: queue unavailable sid=%s — falling back to %s path",
            inputs.session_id,
            "daemon" if async_enabled() else "sync",
        )

    if async_enabled():
        database.set_session_analysis_state(inputs.session_id, "processing")

        def analysis_daemon():
            try:
                run_pipeline()
                database.set_session_analysis_state(inputs.session_id, "ready")
            except Exception as exc:
                log.error(
                    "lab: ASYNC analysis failed sid=%s: %s",
                    inputs.session_id,
                    exc,
                    exc_info=True,
                )
                sentry_sdk.capture_exception(exc)
                database.set_session_analysis_state(
                    inputs.session_id,
                    "failed",
                    str(exc),
                )

        threading.Thread(target=analysis_daemon, daemon=True).start()
        return PendingAnalysis(_processing_payload(
            inputs,
            audit_paid=audit_paid_for_arc(inputs.arc_id, inputs.user_id),
        ))

    readout, sent_to_coach = run_pipeline()
    return CompletedAnalysis(readout, sent_to_coach)
