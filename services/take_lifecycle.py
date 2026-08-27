"""Strict RecordingAttempt lifecycle and successful Take promotion.

Compatibility rows continue to exist in ``v2_sessions`` during parity. This
module is the only application boundary allowed to call the canonical Attempt
RPCs; a missing canonical write is a hard persistence error, never telemetry.
"""
from __future__ import annotations

from typing import Any, Optional

from services.feedback_data_contract import content_hash


class TakeLifecycleError(RuntimeError):
    """Canonical attempt state could not be persisted safely."""


def confidence_canonical_writes_enabled() -> bool:
    """The single reviewed per-surface cutover switch.

    It is a code constant, not an environment toggle.  Slice 4 integrates
    both branches while keeping the canonical branch unreachable.
    """
    from config import Config

    return Config.MLC2_CONFIDENCE_CANONICAL_WRITES_ENABLED is True


def confidence_source_manifest(
    *, audio_bytes: bytes, bucket: str, object_key: str, filename: str,
) -> Optional[dict]:
    """Build no producer payload while the cutover is disabled."""
    if not confidence_canonical_writes_enabled():
        return None
    from services.coach_video_storage import coach_videos_use_r2
    from services.mlc2_confidence_producer import build_source_manifest

    return build_source_manifest(
        audio_bytes=audio_bytes,
        object_store=(
            "cloudflare_r2" if coach_videos_use_r2() else "supabase"
        ),
        bucket=bucket,
        object_key=object_key,
        filename=filename,
    )


def register_attempt(
    *, database: Any, attempt_id: str, owner_principal_id: str,
    project_id: str, upload_idempotency_key: str, recording_id: str,
    storage_bucket: str, storage_key: str, recording_kind: str,
) -> dict:
    input_hash = content_hash({
        "attempt_id": attempt_id,
        "owner_principal_id": owner_principal_id,
        "project_id": project_id,
        "upload_idempotency_key": upload_idempotency_key,
        "recording_id": recording_id,
        "storage_bucket": storage_bucket,
        "storage_key": storage_key,
        "recording_kind": recording_kind,
    })
    row = database.register_recording_attempt(
        attempt_id=attempt_id,
        owner_principal_id=owner_principal_id,
        project_id=project_id,
        upload_idempotency_key=upload_idempotency_key,
        recording_id=recording_id,
        storage_bucket=storage_bucket,
        storage_key=storage_key,
        recording_kind=recording_kind,
        input_hash=input_hash,
    )
    if not isinstance(row, dict) or not row.get("recording_attempt_id"):
        raise TakeLifecycleError("recording attempt was not durably registered")
    return row


def transition_attempt(
    *, database: Any, attempt_id: str, to_status: str, stage: str,
    attempt_count: int, processing_job_id: Optional[str] = None,
    input_provenance: Any = None, output: Any = None,
    error: Optional[BaseException] = None,
) -> dict:
    input_hash = content_hash(input_provenance or {"attempt_id": attempt_id})
    output_hash = content_hash(output) if output is not None else None
    error_payload = None
    if error is not None:
        error_payload = {
            "type": type(error).__name__,
            "message": str(error)[:500],
        }
    key = content_hash({
        "attempt_id": attempt_id,
        "processing_job_id": processing_job_id,
        "to_status": to_status,
        "stage": stage,
        "attempt_count": attempt_count,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "error": error_payload,
    })
    row = database.record_processing_transition(
        recording_attempt_id=attempt_id,
        processing_job_id=processing_job_id,
        to_status=to_status,
        stage=stage,
        attempt_count=attempt_count,
        input_hash=input_hash,
        output_hash=output_hash,
        error=error_payload,
        idempotency_key=f"attempt-transition:{key}",
    )
    if not isinstance(row, dict) or not row.get("transition_id"):
        raise TakeLifecycleError(
            f"recording attempt transition to {to_status} was not persisted"
        )
    return row


def promote_attempt(
    *, database: Any, attempt_id: str, result: Any,
    attempt_count: int = 1, processing_job_id: Optional[str] = None,
    input_provenance: Any = None,
    confidence_producer_manifest: Optional[dict] = None,
) -> dict:
    input_hash = content_hash(input_provenance or {"attempt_id": attempt_id})
    completion_hash = content_hash({
        "attempt_id": attempt_id,
        "result": result,
    })
    output_hash = content_hash(result)
    promotion_kwargs = {
        "recording_attempt_id": attempt_id,
        "completion_hash": completion_hash,
        "processing_job_id": processing_job_id,
        "attempt_count": attempt_count,
        "input_hash": input_hash,
        "output_hash": output_hash,
        "idempotency_key": (
            f"attempt-promotion:{attempt_id}:{completion_hash}"
        ),
    }
    if confidence_canonical_writes_enabled():
        if not isinstance(confidence_producer_manifest, dict):
            raise TakeLifecycleError(
                "confidence cutover requires an immutable source manifest"
            )
        row = database.promote_recording_attempt_with_confidence_outbox(
            **promotion_kwargs,
            source_manifest=confidence_producer_manifest,
        )
    else:
        row = database.promote_recording_attempt_to_take(**promotion_kwargs)
    if not isinstance(row, dict) or not row.get("take_id"):
        raise TakeLifecycleError("successful recording was not promoted to a Take")
    return row


def complete_attempt(
    *, database: Any, attempt_id: str, recording_kind: str, result: Any,
    attempt_count: int = 1, processing_job_id: Optional[str] = None,
    input_provenance: Any = None,
    confidence_producer_manifest: Optional[dict] = None,
) -> dict:
    """Persist the terminal success boundary for spoken and read recordings.

    A spoken recording becomes a canonical Take. A read recording completes
    its Attempt but deliberately consumes no Take ordinal.
    """
    if recording_kind == "spoken":
        return promote_attempt(
            database=database,
            attempt_id=attempt_id,
            result=result,
            attempt_count=attempt_count,
            processing_job_id=processing_job_id,
            input_provenance=input_provenance,
            confidence_producer_manifest=confidence_producer_manifest,
        )
    if recording_kind == "read":
        return transition_attempt(
            database=database,
            attempt_id=attempt_id,
            to_status="succeeded",
            stage="complete",
            attempt_count=attempt_count,
            processing_job_id=processing_job_id,
            input_provenance=input_provenance,
            output=result,
        )
    raise TakeLifecycleError(f"unsupported recording kind: {recording_kind}")
