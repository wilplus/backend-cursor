"""Choose queue, daemon, or synchronous execution for Lab analysis."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

import sentry_sdk

from services.take_lifecycle import complete_attempt, transition_attempt


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
    canonical_attempt_registered: bool = False


@dataclass(frozen=True)
class PendingAnalysis:
    """Analysis was accepted by a background execution mode."""

    payload: dict[str, Any]


@dataclass(frozen=True)
class CompletedAnalysis:
    """Analysis completed synchronously inside the request."""

    readout: dict[str, Any]
    sent_to_coach: bool


@dataclass(frozen=True)
class FailedIdealTextAnalysis:
    """Take 1 analysis persisted, but its canonical document was unconfirmed."""

    payload: dict[str, Any]


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
) -> PendingAnalysis | CompletedAnalysis | FailedIdealTextAnalysis:
    """Run the canonical worker through exactly one execution mode."""
    from services.analysis_worker import run_full_analysis
    from services.ideal_text_confirmation import (
        FAILED_IDEAL_TEXT_UNCONFIRMED,
        IdealTextUnconfirmedError,
        mark_ideal_text_unconfirmed,
    )

    lifecycle_input = {
        "session_id": inputs.session_id,
        "recording_id": inputs.recording_id,
        "recording_kind": inputs.recording_kind,
        "project_id": inputs.arc_id,
        "storage_bucket": inputs.bucket,
        "storage_key": inputs.storage_key,
    }

    def record_transition(**kwargs: Any) -> dict | None:
        if not inputs.canonical_attempt_registered:
            return None
        return transition_attempt(database=database, **kwargs)

    def record_completion(**kwargs: Any) -> dict | None:
        if not inputs.canonical_attempt_registered:
            return None
        return complete_attempt(database=database, **kwargs)

    def ideal_text_failure(exc: IdealTextUnconfirmedError) \
            -> FailedIdealTextAnalysis:
        try:
            record_transition(
                attempt_id=inputs.session_id,
                to_status="failed_ideal_text_unconfirmed",
                stage="ideal_text_confirmation",
                attempt_count=1,
                input_provenance=lifecycle_input,
                error=exc,
            )
        finally:
            # The user-facing failure boundary must close even if the new
            # canonical audit write is temporarily unavailable.
            mark_ideal_text_unconfirmed(
                database,
                session_id=inputs.session_id,
                user_id=inputs.user_id,
                arc_id=inputs.arc_id,
                take_index=inputs.take_index,
                error=exc,
            )
        return FailedIdealTextAnalysis({
            "status": FAILED_IDEAL_TEXT_UNCONFIRMED,
            "state": FAILED_IDEAL_TEXT_UNCONFIRMED,
            "analysis_state": FAILED_IDEAL_TEXT_UNCONFIRMED,
            "session_id": inputs.session_id,
            "recording_id": inputs.recording_id,
            "arc_id": inputs.arc_id,
            "take_index": inputs.take_index,
            "take_count": inputs.arc_take_count,
            "readout": None,
        })

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
            job_id = str(job_row.get("id"))
            record_transition(
                attempt_id=inputs.session_id,
                to_status="processing",
                stage="queue",
                attempt_count=1,
                processing_job_id=job_id,
                input_provenance=lifecycle_input,
            )
            database.set_session_analysis_state(inputs.session_id, "processing")
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
        record_transition(
            attempt_id=inputs.session_id,
            to_status="processing",
            stage="daemon",
            attempt_count=1,
            input_provenance=lifecycle_input,
        )
        database.set_session_analysis_state(inputs.session_id, "processing")

        def analysis_daemon():
            try:
                result = run_pipeline()
                record_completion(
                    attempt_id=inputs.session_id,
                    recording_kind=inputs.recording_kind,
                    result=result,
                    input_provenance=lifecycle_input,
                )
                database.set_session_analysis_state(inputs.session_id, "ready")
            except IdealTextUnconfirmedError as exc:
                log.error(
                    "lab: Take 1 Ideal Text unconfirmed sid=%s: %s",
                    inputs.session_id,
                    exc,
                )
                sentry_sdk.capture_exception(exc)
                ideal_text_failure(exc)
            except Exception as exc:
                log.error(
                    "lab: ASYNC analysis failed sid=%s: %s",
                    inputs.session_id,
                    exc,
                    exc_info=True,
                )
                sentry_sdk.capture_exception(exc)
                try:
                    record_transition(
                        attempt_id=inputs.session_id,
                        to_status="failed",
                        stage="analysis",
                        attempt_count=1,
                        input_provenance=lifecycle_input,
                        error=exc,
                    )
                finally:
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

    record_transition(
        attempt_id=inputs.session_id,
        to_status="processing",
        stage="sync",
        attempt_count=1,
        input_provenance=lifecycle_input,
    )
    try:
        readout, sent_to_coach = run_pipeline()
        record_completion(
            attempt_id=inputs.session_id,
            recording_kind=inputs.recording_kind,
            result={"readout": readout, "sent_to_coach": sent_to_coach},
            input_provenance=lifecycle_input,
        )
        return CompletedAnalysis(readout, sent_to_coach)
    except IdealTextUnconfirmedError as exc:
        sentry_sdk.capture_exception(exc)
        return ideal_text_failure(exc)
    except Exception as exc:
        try:
            record_transition(
                attempt_id=inputs.session_id,
                to_status="failed",
                stage="analysis",
                attempt_count=1,
                input_provenance=lifecycle_input,
                error=exc,
            )
        finally:
            database.set_session_analysis_state(
                inputs.session_id,
                "failed",
                str(exc),
            )
        raise
