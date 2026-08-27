"""Dark-by-default MLC-2 foundation contracts.

This module is deliberately not imported by any product route yet.  Surface
cutovers happen in later, separately reviewed slices.  It centralises the
seven-system registry, semantic namespaces, canonical envelope validation and
the service-role RPC seam so future writers cannot invent a parallel contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Optional
from uuid import UUID, uuid4


LEARNING_CONTRACT_VERSION = "MLC-2"
DATA_EPOCH = 1

LEARNING_SURFACES = frozenset({
    "confidence_classification",
    "correction_generation",
    "coach_comment_generation",
    "praise_generation",
    "praise_selection",
    "correction_selection",
    "ideal_text_generation",
})

LEARNING_SURFACE_ALIASES: dict[str, str] = {
    "say_it_stronger": "correction_generation",
    "coach_comment_draft": "coach_comment_generation",
    "ideal_text": "ideal_text_generation",
}

REJECTED_LEARNING_ALIASES = frozenset({"moment_suggestion"})

FEEDBACK_FAMILIES = frozenset({
    "confident_voice",
    "great_formulation",
    "rewrite_clarity",
})
PIPELINE_STAGES = frozenset({"classify", "generate", "select"})
PRODUCT_OPERATIONS = frozenset({
    "replace",
    "lock",
    "unlock",
    "style_orange",
    "remove_orange",
    "none",
})

PAYLOAD_TYPES: dict[str, str] = {
    "confidence_classification": "confidence_event",
    "correction_generation": "correction_generation_event",
    "coach_comment_generation": "coach_comment_event",
    "praise_generation": "praise_generation_event",
    "praise_selection": "praise_selection_event",
    "correction_selection": "correction_selection_event",
    "ideal_text_generation": "ideal_text_event",
}

FEEDBACK_SURFACES = frozenset({
    "confidence_classification",
    "correction_generation",
    "praise_generation",
    "praise_selection",
    "correction_selection",
})

DECISION_NAMESPACES = {
    "confidence_self_report": frozenset({
        "confident_yes",
        "confident_in_between",
        "confident_no",
        "confident_not_sure",
        "confident_audio_unclear",
    }),
    "rewrite": frozenset({
        "rewrite_accept", "rewrite_reject", "rewrite_not_sure",
    }),
    "praise": frozenset({
        "praise_useful", "praise_not_useful", "praise_not_sure",
    }),
    "blind_rating": frozenset({
        "rating_yes",
        "rating_in_between",
        "rating_no",
        "rating_not_sure",
        "rating_audio_unclear",
    }),
    "professional_evaluation": frozenset({
        "professional_yes", "professional_no", "professional_refine",
    }),
    "paragraph_product_action": frozenset({
        "paragraph_lock", "paragraph_leave_unlocked", "paragraph_unlock",
    }),
    "orange_product_action": frozenset({
        "orange_apply", "orange_decline", "orange_remove",
    }),
}


class Mlc2ContractError(ValueError):
    """Raised before an invalid event can reach the canonical ledger."""


def canonical_surface_id(value: str) -> str:
    """Resolve an explicit alias or reject ambiguous/unknown vocabulary."""
    surface = str(value or "").strip()
    if surface in REJECTED_LEARNING_ALIASES:
        raise Mlc2ContractError(
            f"{surface!r} is ambiguous legacy vocabulary and cannot be "
            "used for canonical writes"
        )
    surface = LEARNING_SURFACE_ALIASES.get(surface, surface)
    if surface not in LEARNING_SURFACES:
        raise Mlc2ContractError(f"unknown canonical learning surface: {value!r}")
    return surface


def _uuid_text(value: UUID | str, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise Mlc2ContractError(f"{field} must be a UUID") from exc


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise Mlc2ContractError("occurred_at must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def stable_json_sha256(value: Mapping[str, Any]) -> str:
    """Canonical JSON checksum used for immutable envelopes and manifests."""
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_object_bytes(
    content: bytes,
    *,
    expected_sha256: str,
    expected_byte_size: int,
) -> dict[str, Any]:
    """Verify downloaded R2 bytes without trusting object metadata alone."""
    observed_sha256 = hashlib.sha256(content).hexdigest()
    observed_byte_size = len(content)
    return {
        "observed_sha256": observed_sha256,
        "observed_byte_size": observed_byte_size,
        "verified": (
            observed_sha256 == expected_sha256
            and observed_byte_size == expected_byte_size
        ),
        "verification_method": "downloaded_bytes_sha256_v1",
    }


@dataclass(frozen=True)
class CanonicalEnvelope:
    """Validated shared envelope; the payload remains surface-specific."""

    event_id: UUID | str
    idempotency_key: str
    learning_surface_id: str
    pipeline_stage_id: str
    acquisition_principal_id: UUID | str
    speaker_id: UUID | str
    consent_snapshot_id: UUID | str
    source_event_id: str
    occurred_at: datetime
    execution_version: Mapping[str, Any]
    payload: Mapping[str, Any]
    feedback_family_id: Optional[str] = None
    project_id: Optional[UUID | str] = None
    recording_attempt_id: Optional[UUID | str] = None
    take_id: Optional[UUID | str] = None
    clip_id: Optional[UUID | str] = None
    evidence_locator: Optional[Mapping[str, Any]] = None

    def as_dict(self) -> dict[str, Any]:
        surface = canonical_surface_id(self.learning_surface_id)
        stage = str(self.pipeline_stage_id or "").strip()
        if stage not in PIPELINE_STAGES:
            raise Mlc2ContractError(f"invalid pipeline stage: {stage!r}")

        family = (
            str(self.feedback_family_id).strip()
            if self.feedback_family_id is not None
            else None
        )
        if surface in FEEDBACK_SURFACES:
            if family not in FEEDBACK_FAMILIES:
                raise Mlc2ContractError(
                    f"{surface} requires an explicit feedback_family"
                )
        elif family is not None:
            raise Mlc2ContractError(
                f"{surface} is not a feedback artifact and requires null "
                "feedback_family"
            )

        idempotency_key = str(self.idempotency_key or "").strip()
        source_event_id = str(self.source_event_id or "").strip()
        if not idempotency_key or not source_event_id:
            raise Mlc2ContractError(
                "idempotency_key and source_event_id are required"
            )
        if not isinstance(self.execution_version, Mapping) \
                or not self.execution_version:
            raise Mlc2ContractError("execution_version must be a non-empty object")
        if not isinstance(self.payload, Mapping):
            raise Mlc2ContractError("typed payload must be an object")

        result: dict[str, Any] = {
            "event_id": _uuid_text(self.event_id, "event_id"),
            "idempotency_key": idempotency_key,
            "learning_contract_version": LEARNING_CONTRACT_VERSION,
            "data_epoch": DATA_EPOCH,
            "learning_surface_id": surface,
            "pipeline_stage_id": stage,
            "feedback_family_id": family,
            "acquisition_principal_id": _uuid_text(
                self.acquisition_principal_id, "acquisition_principal_id"
            ),
            "speaker_id": _uuid_text(self.speaker_id, "speaker_id"),
            "consent_snapshot_id": _uuid_text(
                self.consent_snapshot_id, "consent_snapshot_id"
            ),
            "project_id": None,
            "recording_attempt_id": None,
            "take_id": None,
            "clip_id": None,
            "evidence_locator": dict(self.evidence_locator or {}),
            "execution_version": dict(self.execution_version),
            "payload_type": PAYLOAD_TYPES[surface],
            "payload": dict(self.payload),
            "source_event_id": source_event_id,
            "occurred_at": _utc_iso(self.occurred_at),
        }
        for field in (
            "project_id", "recording_attempt_id", "take_id", "clip_id"
        ):
            raw = getattr(self, field)
            if raw is not None:
                result[field] = _uuid_text(raw, field)
        return result


def new_event_id() -> UUID:
    return uuid4()


class Mlc2FoundationStore:
    """Service-role RPC adapter; no product route uses it before cutover."""

    def __init__(self, client: Any):
        self.client = client

    @staticmethod
    def _one(result: Any) -> dict[str, Any]:
        data = getattr(result, "data", None)
        if isinstance(data, list):
            return dict(data[0]) if data else {}
        return dict(data) if isinstance(data, dict) else {}

    def enqueue(
        self,
        *,
        idempotency_key: str,
        event_type: str,
        learning_surface_id: str,
        aggregate_type: str,
        aggregate_id: UUID | str,
        payload: Mapping[str, Any],
        occurred_at: datetime,
    ) -> dict[str, Any]:
        surface = canonical_surface_id(learning_surface_id)
        response = self.client.rpc("enqueue_mlc2_outbox_event_v1", {
            "p_idempotency_key": idempotency_key,
            "p_event_type": event_type,
            "p_learning_surface_id": surface,
            "p_aggregate_type": aggregate_type,
            "p_aggregate_id": _uuid_text(aggregate_id, "aggregate_id"),
            "p_payload": dict(payload),
            "p_occurred_at": _utc_iso(occurred_at),
        }).execute()
        return self._one(response)

    def claim(
        self, *, worker_id: str, limit: int = 25, lease_seconds: int = 60
    ) -> list[dict[str, Any]]:
        response = self.client.rpc("claim_mlc2_outbox_events_v1", {
            "p_worker_id": worker_id,
            "p_limit": limit,
            "p_lease_seconds": lease_seconds,
        }).execute()
        data = getattr(response, "data", None)
        return [dict(row) for row in data] if isinstance(data, list) else []

    def finalize(
        self,
        *,
        outbox_event_id: UUID | str,
        worker_id: str,
        envelope: CanonicalEnvelope,
    ) -> dict[str, Any]:
        response = self.client.rpc("finalize_mlc2_outbox_event_v1", {
            "p_outbox_event_id": _uuid_text(
                outbox_event_id, "outbox_event_id"
            ),
            "p_worker_id": worker_id,
            "p_canonical_event": envelope.as_dict(),
        }).execute()
        return self._one(response)

    def fail(
        self,
        *,
        outbox_event_id: UUID | str,
        worker_id: str,
        error_code: str,
        retry_after_seconds: int = 30,
    ) -> dict[str, Any]:
        response = self.client.rpc("fail_mlc2_outbox_event_v1", {
            "p_outbox_event_id": _uuid_text(
                outbox_event_id, "outbox_event_id"
            ),
            "p_worker_id": worker_id,
            "p_error_code": error_code,
            "p_retry_after_seconds": retry_after_seconds,
        }).execute()
        return self._one(response)

    def health(self) -> dict[str, Any]:
        return self._one(
            self.client.rpc("get_mlc2_foundation_health_v1", {}).execute()
        )
