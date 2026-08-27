"""Dark MLC-2 Confidence Classification runtime contracts.

Nothing in the live product imports this module in Slice 3.  It validates the
complete classifier + deterministic-selection frame before the service-role
RPC can atomically persist it.  Confidence selection remains part of
``confidence_classification`` and never becomes an eighth learning surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import math
from typing import Any, Mapping, Sequence
from uuid import UUID

from services.mlc2_foundation import (
    CanonicalEnvelope,
    Mlc2ContractError,
)


CONFIDENCE_SURFACE = "confidence_classification"
CONFIDENCE_FAMILY = "confident_voice"
CONFIDENCE_STAGE = "classify"
SELECTION_EXECUTION_KIND = "deterministic_policy"
EXPLORATION_PROBABILITY = 0.20


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
        raise Mlc2ContractError(f"{field} must be a lowercase SHA-256 hex value")
    return result


def _number(value: Any, field: str, *, minimum: float = 0.0,
            maximum: float = 1.0) -> float:
    if isinstance(value, bool):
        raise Mlc2ContractError(f"{field} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise Mlc2ContractError(f"{field} must be numeric") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise Mlc2ContractError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return result


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise Mlc2ContractError(f"{field} must be an object")
    return dict(value)


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise Mlc2ContractError(f"{field} must be an array")
    return list(value)


def _timestamp(value: Any, field: str) -> str:
    text = _text(value, field)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Mlc2ContractError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise Mlc2ContractError(f"{field} must include a timezone")
    return text


def _validate_model_run(run: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    result = dict(run)
    result["id"] = _uuid(result.get("id"), f"{field}.id")
    for name in (
        "provider", "model_id", "assignment_origin", "assignment_version",
        "code_version", "request_sha256",
    ):
        if name == "request_sha256":
            result[name] = _sha256(result.get(name), f"{field}.{name}")
        else:
            result[name] = _text(result.get(name), f"{field}.{name}")
    result["configuration"] = _mapping(
        result.get("configuration", {}), f"{field}.configuration"
    )
    result["started_at"] = _timestamp(
        result.get("started_at"), f"{field}.started_at"
    )
    result["completed_at"] = _timestamp(
        result.get("completed_at"), f"{field}.completed_at"
    )
    return result


def _validate_evidence(value: Any, candidate_field: str) -> dict[str, Any]:
    evidence = _mapping(value, f"{candidate_field}.evidence")
    evidence["id"] = _uuid(evidence.get("id"), f"{candidate_field}.evidence.id")
    evidence["coordinates"] = _mapping(
        evidence.get("coordinates"), f"{candidate_field}.evidence.coordinates"
    )
    start_ms = evidence["coordinates"].get("start_ms")
    end_ms = evidence["coordinates"].get("end_ms")
    if isinstance(start_ms, bool) or not isinstance(start_ms, int) \
            or isinstance(end_ms, bool) or not isinstance(end_ms, int):
        raise Mlc2ContractError(
            f"{candidate_field}.evidence.coordinates requires "
            "integer start_ms >= 0 and end_ms > start_ms"
        )
    if start_ms < 0 or end_ms <= start_ms:
        raise Mlc2ContractError(
            f"{candidate_field}.evidence.coordinates requires "
            "integer start_ms >= 0 and end_ms > start_ms"
        )
    evidence["content_sha256"] = _sha256(
        evidence.get("content_sha256"),
        f"{candidate_field}.evidence.content_sha256",
    )
    evidence["evidence_schema_version"] = _text(
        evidence.get("evidence_schema_version"),
        f"{candidate_field}.evidence.evidence_schema_version",
    )
    object_metadata = _mapping(
        evidence.get("object"), f"{candidate_field}.evidence.object"
    )
    object_metadata["id"] = _uuid(
        object_metadata.get("id"), f"{candidate_field}.evidence.object.id"
    )
    for name in ("bucket", "object_key", "content_type"):
        object_metadata[name] = _text(
            object_metadata.get(name),
            f"{candidate_field}.evidence.object.{name}",
        )
    if not object_metadata["content_type"].startswith("audio/"):
        raise Mlc2ContractError(
            f"{candidate_field}.evidence.object.content_type must be audio"
        )
    object_metadata["sha256"] = _sha256(
        object_metadata.get("sha256"),
        f"{candidate_field}.evidence.object.sha256",
    )
    byte_size = object_metadata.get("byte_size")
    if isinstance(byte_size, bool) or not isinstance(byte_size, int) \
            or byte_size <= 0:
        raise Mlc2ContractError(
            f"{candidate_field}.evidence.object.byte_size must be positive"
        )
    evidence["object"] = object_metadata
    return evidence


def _validate_prediction(value: Any, candidate_field: str) -> dict[str, Any]:
    prediction = _mapping(value, f"{candidate_field}.prediction")
    prediction["id"] = _uuid(
        prediction.get("id"), f"{candidate_field}.prediction.id"
    )
    prediction["predicted_value"] = _text(
        prediction.get("predicted_value"),
        f"{candidate_field}.prediction.predicted_value",
    )
    prediction["confidence_score"] = _number(
        prediction.get("confidence_score"),
        f"{candidate_field}.prediction.confidence_score",
    )
    prediction["probability_distribution"] = _mapping(
        prediction.get("probability_distribution"),
        f"{candidate_field}.prediction.probability_distribution",
    )
    prediction["raw_output"] = _mapping(
        prediction.get("raw_output"),
        f"{candidate_field}.prediction.raw_output",
    )
    prediction["output_schema_version"] = _text(
        prediction.get("output_schema_version"),
        f"{candidate_field}.prediction.output_schema_version",
    )
    return prediction


def _validate_candidate(value: Any, index: int) -> dict[str, Any]:
    field = f"candidate_set.candidates[{index}]"
    candidate = _mapping(value, field)
    candidate["id"] = _uuid(candidate.get("id"), f"{field}.id")
    candidate["clip_id"] = _uuid(candidate.get("clip_id"), f"{field}.clip_id")
    candidate["candidate_key"] = _text(
        candidate.get("candidate_key"), f"{field}.candidate_key"
    )
    candidate["evidence"] = _validate_evidence(candidate.get("evidence"), field)

    eligible = candidate.get("eligible")
    selected = candidate.get("selected")
    if not isinstance(eligible, bool) or not isinstance(selected, bool):
        raise Mlc2ContractError(f"{field}.eligible and selected must be booleans")
    mode = _text(candidate.get("selection_mode"), f"{field}.selection_mode")
    if mode not in {"deterministic", "exploration", "not_selected", "excluded"}:
        raise Mlc2ContractError(f"{field}.selection_mode is invalid")
    candidate["selection_reason_code"] = _text(
        candidate.get("selection_reason_code"),
        f"{field}.selection_reason_code",
    )
    candidate["sampling_probability"] = _number(
        candidate.get("sampling_probability"),
        f"{field}.sampling_probability",
    )

    if eligible:
        if candidate.get("exclusion_reason_code") not in (None, ""):
            raise Mlc2ContractError(f"{field} cannot be eligible and excluded")
        candidate["exclusion_reason_code"] = None
        candidate["prediction"] = _validate_prediction(
            candidate.get("prediction"), field
        )
        candidate["score"] = _number(candidate.get("score"), f"{field}.score")
        rank = candidate.get("rank")
        if isinstance(rank, bool) or not isinstance(rank, int) or rank <= 0:
            raise Mlc2ContractError(f"{field}.rank must be a positive integer")
        if selected and mode not in {"deterministic", "exploration"}:
            raise Mlc2ContractError(f"{field} selected candidate has invalid mode")
        if not selected and mode != "not_selected":
            raise Mlc2ContractError(f"{field} unselected candidate has invalid mode")
    else:
        if candidate.get("prediction") is not None:
            candidate["prediction"] = _validate_prediction(
                candidate.get("prediction"), field
            )
        else:
            candidate.pop("prediction", None)
        candidate["exclusion_reason_code"] = _text(
            candidate.get("exclusion_reason_code"),
            f"{field}.exclusion_reason_code",
        )
        if selected or mode != "excluded":
            raise Mlc2ContractError(f"{field} excluded candidate cannot be selected")
        if candidate["sampling_probability"] != 0:
            raise Mlc2ContractError(
                f"{field} excluded candidate probability must be zero"
            )
        if candidate.get("score") is not None:
            candidate["score"] = _number(
                candidate.get("score"), f"{field}.score"
            )
        else:
            candidate["score"] = None
        candidate["rank"] = None

    draw_index = candidate.get("rng_draw_index")
    if mode == "exploration":
        if isinstance(draw_index, bool) or not isinstance(draw_index, int) \
                or draw_index < 0:
            raise Mlc2ContractError(
                f"{field}.rng_draw_index is required for exploration"
            )
    elif draw_index is not None:
        if isinstance(draw_index, bool) or not isinstance(draw_index, int) \
                or draw_index < 0:
            raise Mlc2ContractError(f"{field}.rng_draw_index is invalid")
    return candidate


@dataclass(frozen=True)
class ConfidenceSamplingFrame:
    """Complete immutable candidate pool plus both execution records."""

    classification_run: Mapping[str, Any]
    selection_run: Mapping[str, Any]
    candidate_set_id: UUID | str
    candidate_set_version: str
    candidates: Sequence[Mapping[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        classification = _validate_model_run(
            self.classification_run, field="classification_run"
        )
        if classification["assignment_origin"] not in {"foundation", "trained"}:
            raise Mlc2ContractError(
                "classification_run.assignment_origin must be foundation or trained"
            )
        for name in (
            "feature_schema_version", "feature_extractor_version",
            "detector_version", "threshold_version", "taxonomy_version",
        ):
            classification[name] = _text(
                classification.get(name), f"classification_run.{name}"
            )
        classification["threshold_snapshot"] = _mapping(
            classification.get("threshold_snapshot", {}),
            "classification_run.threshold_snapshot",
        )

        selection = _validate_model_run(
            self.selection_run, field="selection_run"
        )
        if selection["provider"] != "deterministic_policy" \
                or selection["assignment_origin"] != "deterministic_policy":
            raise Mlc2ContractError(
                "confidence selection must be a deterministic policy run"
            )
        if selection.get("execution_kind") != SELECTION_EXECUTION_KIND:
            raise Mlc2ContractError(
                "selection_run.execution_kind must be deterministic_policy"
            )
        for name in (
            "selection_policy_version", "eligibility_policy_version",
            "threshold_version", "rng_algorithm", "rng_seed",
        ):
            selection[name] = _text(selection.get(name), f"selection_run.{name}")
        if selection["model_id"] != selection["selection_policy_version"] \
                or selection["assignment_version"] != (
                    selection["selection_policy_version"]
                ):
            raise Mlc2ContractError(
                "deterministic selection model and assignment versions must "
                "equal selection_policy_version"
            )
        probability = _number(
            selection.get("exploration_probability"),
            "selection_run.exploration_probability",
        )
        if probability != EXPLORATION_PROBABILITY:
            raise Mlc2ContractError(
                "confidence selection exploration_probability must be 0.20"
            )
        selection["exploration_probability"] = probability
        selection["rng_draws"] = _array(
            selection.get("rng_draws"), "selection_run.rng_draws"
        )
        if selection["threshold_version"] != classification["threshold_version"]:
            raise Mlc2ContractError(
                "classification and selection threshold versions must match"
            )

        candidates = [
            _validate_candidate(value, index)
            for index, value in enumerate(_array(self.candidates, "candidates"))
        ]
        if not candidates:
            raise Mlc2ContractError("confidence candidate pool cannot be empty")
        keys = [candidate["candidate_key"] for candidate in candidates]
        ids = [candidate["id"] for candidate in candidates]
        ranks = [candidate["rank"] for candidate in candidates if candidate["eligible"]]
        if len(keys) != len(set(keys)) or len(ids) != len(set(ids)):
            raise Mlc2ContractError("candidate ids and keys must be unique")
        if len(ranks) != len(set(ranks)):
            raise Mlc2ContractError("eligible candidate ranks must be unique")
        if not any(candidate["selected"] for candidate in candidates):
            raise Mlc2ContractError("confidence frame must select at least one candidate")

        # Deep-copy through JSON so the returned RPC payload cannot be changed
        # by mutating a caller-owned nested mapping after validation.
        result = {
            "classification_run": classification,
            "selection_run": selection,
            "candidate_set": {
                "id": _uuid(self.candidate_set_id, "candidate_set.id"),
                "candidate_set_version": _text(
                    self.candidate_set_version,
                    "candidate_set.candidate_set_version",
                ),
                "candidates": candidates,
            },
        }
        return json.loads(json.dumps(result, sort_keys=True, separators=(",", ":")))


class Mlc2ConfidenceStore:
    """Service-role seam; intentionally unused until a reviewed cutover."""

    def __init__(self, client: Any):
        self.client = client

    def finalize_frame(
        self,
        *,
        outbox_event_id: UUID | str,
        worker_id: str,
        envelope: CanonicalEnvelope,
        frame: ConfidenceSamplingFrame,
    ) -> dict[str, Any]:
        envelope_payload = envelope.as_dict()
        if envelope_payload["learning_surface_id"] != CONFIDENCE_SURFACE \
                or envelope_payload["pipeline_stage_id"] != CONFIDENCE_STAGE \
                or envelope_payload["feedback_family_id"] != CONFIDENCE_FAMILY:
            raise Mlc2ContractError(
                "confidence frame requires confidence_classification / classify / confident_voice"
            )
        response = self.client.rpc("finalize_mlc2_confidence_frame_v1", {
            "p_outbox_event_id": _uuid(outbox_event_id, "outbox_event_id"),
            "p_worker_id": _text(worker_id, "worker_id"),
            "p_canonical_event": envelope_payload,
            "p_confidence_frame": frame.as_dict(),
        }).execute()
        data = getattr(response, "data", None)
        if isinstance(data, list):
            return dict(data[0]) if data else {}
        return dict(data) if isinstance(data, Mapping) else {}
