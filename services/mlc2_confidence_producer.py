"""Dark Slice-4 Confidence Classification producer and worker seams.

The application integration calls the atomic promotion/outbox RPC only when
the reviewed code-level cutover flag is true.  Slice 4 keeps it false.  The
worker is dependency-injected and is not registered with RQ or any sweeper;
it exists so retry, leasing and finalization can be rehearsed without a model
call or a production producer.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import mimetypes
from pathlib import PurePath
from typing import Any, Callable, Mapping
from uuid import UUID

from services.mlc2_confidence import (
    ConfidenceSamplingFrame,
    Mlc2ConfidenceStore,
)
from services.mlc2_foundation import CanonicalEnvelope, Mlc2ContractError


PRODUCER_CONTRACT_VERSION = "confidence-producer-v1"
SOURCE_SCHEMA_VERSION = "confidence-source-audio-v1"
EVENT_TYPE = "confidence_take_ready"


def _uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise Mlc2ContractError(f"{field} must be a UUID") from exc


def _text(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise Mlc2ContractError(f"{field} is required")
    return result


def _sha256(value: Any, field: str) -> str:
    result = _text(value, field).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise Mlc2ContractError(f"{field} must be lowercase SHA-256 hex")
    return result


def _content_type(filename: str) -> str:
    suffix = PurePath(filename or "recording.webm").suffix.lower()
    known = {
        ".webm": "audio/webm",
        ".m4a": "audio/mp4",
        ".mp4": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
    }
    guessed = known.get(suffix) or mimetypes.guess_type(filename)[0]
    return guessed if guessed and guessed.startswith("audio/") else "audio/webm"


def build_source_manifest(
    *, audio_bytes: bytes, object_store: str, bucket: str,
    object_key: str, filename: str,
) -> dict[str, Any]:
    """Snapshot the immutable parent audio before Take promotion.

    The final candidate frame later stores exact clip spans.  This source
    manifest proves which complete recording the classifier worker received.
    """
    if not isinstance(audio_bytes, bytes) or not audio_bytes:
        raise Mlc2ContractError("confidence source audio must be non-empty bytes")
    if object_store != "cloudflare_r2":
        raise Mlc2ContractError("confidence source audio must be in Cloudflare R2")
    return {
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "audio": {
            "object_store": object_store,
            "bucket": _text(bucket, "bucket"),
            "object_key": _text(object_key, "object_key").lstrip("/"),
            "sha256": hashlib.sha256(audio_bytes).hexdigest(),
            "byte_size": len(audio_bytes),
            "content_type": _content_type(filename),
        },
    }


def _validate_source_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get(
            "source_schema_version") != SOURCE_SCHEMA_VERSION:
        raise Mlc2ContractError("confidence source manifest is invalid")
    audio = value.get("audio")
    if not isinstance(audio, Mapping) \
            or audio.get("object_store") != "cloudflare_r2":
        raise Mlc2ContractError("confidence source manifest requires R2 audio")
    byte_size = audio.get("byte_size")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) \
            or byte_size <= 0:
        raise Mlc2ContractError("confidence source audio size is invalid")
    content_type = _text(audio.get("content_type"), "audio.content_type")
    if not content_type.startswith("audio/"):
        raise Mlc2ContractError("confidence source content type must be audio")
    return {
        "source_schema_version": SOURCE_SCHEMA_VERSION,
        "audio": {
            "object_store": "cloudflare_r2",
            "bucket": _text(audio.get("bucket"), "audio.bucket"),
            "object_key": _text(audio.get("object_key"), "audio.object_key"),
            "sha256": _sha256(audio.get("sha256"), "audio.sha256"),
            "byte_size": byte_size,
            "content_type": content_type,
        },
    }


@dataclass(frozen=True)
class ConfidenceProducerEvent:
    """Validated payload from one surface-filtered outbox lease."""

    outbox_event_id: UUID | str
    payload: Mapping[str, Any]

    def envelope(self) -> CanonicalEnvelope:
        raw = dict(self.payload)
        if raw.get("producer_contract_version") != PRODUCER_CONTRACT_VERSION:
            raise Mlc2ContractError("unknown confidence producer contract")
        if raw.get("learning_surface_id") != "confidence_classification" \
                or raw.get("pipeline_stage_id") != "classify" \
                or raw.get("feedback_family_id") != "confident_voice" \
                or raw.get("payload_type") != "confidence_event":
            raise Mlc2ContractError("confidence producer semantics are invalid")
        _validate_source_manifest(raw.get("source_manifest"))
        expected_hash = _sha256(
            raw.get("source_manifest_sha256"), "source_manifest_sha256"
        )
        # PostgreSQL owns the canonical JSON checksum.  The worker carries it
        # through rather than recomputing with language-specific whitespace.
        payload = raw.get("payload")
        if not isinstance(payload, Mapping) or payload.get(
                "source_manifest_sha256") != expected_hash:
            raise Mlc2ContractError("confidence source hash lineage is broken")
        occurred = datetime.fromisoformat(
            _text(raw.get("occurred_at"), "occurred_at").replace("Z", "+00:00")
        )
        return CanonicalEnvelope(
            event_id=_uuid(raw.get("event_id"), "event_id"),
            idempotency_key=_text(raw.get("idempotency_key"), "idempotency_key"),
            learning_surface_id="confidence_classification",
            pipeline_stage_id="classify",
            feedback_family_id="confident_voice",
            acquisition_principal_id=_uuid(
                raw.get("acquisition_principal_id"), "acquisition_principal_id"
            ),
            speaker_id=_uuid(raw.get("speaker_id"), "speaker_id"),
            consent_snapshot_id=_uuid(
                raw.get("consent_snapshot_id"), "consent_snapshot_id"
            ),
            project_id=_uuid(raw.get("project_id"), "project_id"),
            recording_attempt_id=_uuid(
                raw.get("recording_attempt_id"), "recording_attempt_id"
            ),
            take_id=_uuid(raw.get("take_id"), "take_id"),
            source_event_id=_text(raw.get("source_event_id"), "source_event_id"),
            occurred_at=occurred,
            evidence_locator={
                "scope": "complete_take_pool",
                "source_manifest_sha256": expected_hash,
            },
            execution_version={
                "producer_contract_version": PRODUCER_CONTRACT_VERSION,
                "source_schema_version": SOURCE_SCHEMA_VERSION,
            },
            payload=dict(payload),
        )


class Mlc2ConfidenceProducerStore:
    """RPC adapter used by a future separately-authorized worker."""

    def __init__(self, client: Any):
        self.client = client

    @staticmethod
    def _one(result: Any) -> dict[str, Any]:
        data = getattr(result, "data", None)
        if isinstance(data, list):
            return dict(data[0]) if data else {}
        return dict(data) if isinstance(data, Mapping) else {}

    def claim(
        self, *, worker_id: str, limit: int = 25, lease_seconds: int = 60
    ) -> list[dict[str, Any]]:
        result = self.client.rpc("claim_mlc2_confidence_outbox_v1", {
            "p_worker_id": _text(worker_id, "worker_id"),
            "p_limit": limit,
            "p_lease_seconds": lease_seconds,
        }).execute()
        data = getattr(result, "data", None)
        return [dict(row) for row in data] if isinstance(data, list) else []

    def fail(
        self, *, outbox_event_id: UUID | str, worker_id: str,
        error_code: str, retry_after_seconds: int = 30,
    ) -> dict[str, Any]:
        return self._one(self.client.rpc("fail_mlc2_outbox_event_v1", {
            "p_outbox_event_id": _uuid(outbox_event_id, "outbox_event_id"),
            "p_worker_id": _text(worker_id, "worker_id"),
            "p_error_code": _text(error_code, "error_code")[:120],
            "p_retry_after_seconds": max(1, int(retry_after_seconds)),
        }).execute())

    def health(self) -> dict[str, Any]:
        return self._one(
            self.client.rpc("get_mlc2_confidence_slice4_health_v1", {}).execute()
        )


class DarkConfidenceWorker:
    """Rehearsable worker with no queue registration and no model adapter.

    A future activation supplies a reviewed ``frame_factory``.  Exceptions are
    returned to the outbox with a retry code; product state is never reversed.
    """

    def __init__(
        self, *, producer_store: Mlc2ConfidenceProducerStore,
        frame_store: Mlc2ConfidenceStore,
        frame_factory: Callable[
            [ConfidenceProducerEvent], ConfidenceSamplingFrame
        ],
    ) -> None:
        self.producer_store = producer_store
        self.frame_store = frame_store
        self.frame_factory = frame_factory

    def process_claimed(self, row: Mapping[str, Any], *, worker_id: str) -> dict:
        raw_payload = row.get("payload")
        if not isinstance(raw_payload, Mapping):
            raise Mlc2ContractError("claimed confidence event has no payload")
        event = ConfidenceProducerEvent(
            outbox_event_id=_uuid(row.get("id"), "outbox_event_id"),
            payload=raw_payload,
        )
        try:
            envelope = event.envelope()
            frame = self.frame_factory(event)
            return self.frame_store.finalize_frame(
                outbox_event_id=event.outbox_event_id,
                worker_id=worker_id,
                envelope=envelope,
                frame=frame,
            )
        except Exception as error:
            self.producer_store.fail(
                outbox_event_id=event.outbox_event_id,
                worker_id=worker_id,
                error_code=f"{type(error).__name__}:confidence_frame_failed",
            )
            raise
