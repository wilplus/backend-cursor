from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID

import pytest

from services.mlc2_confidence import (
    ConfidenceSamplingFrame,
    EXPLORATION_PROBABILITY,
    Mlc2ConfidenceStore,
)
from services.mlc2_foundation import CanonicalEnvelope, Mlc2ContractError


def _frame() -> ConfidenceSamplingFrame:
    timestamp = "2026-08-27T10:00:00+00:00"
    classification = {
        "id": "10000000-0000-0000-0000-000000000001",
        "provider": "openai",
        "model_id": "confidence-baseline-v1",
        "adapter_id": None,
        "assignment_origin": "foundation",
        "assignment_version": "assignment-v1",
        "code_version": "commit-abc",
        "configuration": {"temperature": 0},
        "request_sha256": "a" * 64,
        "started_at": timestamp,
        "completed_at": timestamp,
        "feature_schema_version": "features-v1",
        "feature_extractor_version": "extractor-v1",
        "detector_version": "detector-v1",
        "threshold_version": "threshold-v1",
        "taxonomy_version": "confidence-five-state-v1",
        "threshold_snapshot": {"confident": 0.7},
    }
    selection = {
        "id": "10000000-0000-0000-0000-000000000002",
        "provider": "deterministic_policy",
        "model_id": "confidence-selection-v1",
        "adapter_id": None,
        "assignment_origin": "deterministic_policy",
        "assignment_version": "confidence-selection-v1",
        "code_version": "commit-abc",
        "configuration": {"lane": "confident_voice"},
        "request_sha256": "b" * 64,
        "started_at": timestamp,
        "completed_at": timestamp,
        "execution_kind": "deterministic_policy",
        "selection_policy_version": "confidence-selection-v1",
        "eligibility_policy_version": "confidence-eligible-v1",
        "threshold_version": "threshold-v1",
        "exploration_probability": EXPLORATION_PROBABILITY,
        "rng_algorithm": "hmac-sha256-counter-v1",
        "rng_seed": "opaque-seed-reference-1",
        "rng_draws": [{"index": 0, "value": 0.42}],
    }

    def evidence(index: int) -> dict:
        return {
            "id": f"20000000-0000-0000-0000-{index:012d}",
            "coordinates": {"start_ms": index * 1000, "end_ms": index * 1000 + 900},
            "content_sha256": f"{index:x}" * 64,
            "evidence_schema_version": "audio-span-v1",
            "object": {
                "id": f"30000000-0000-0000-0000-{index:012d}",
                "bucket": "mlc2-rehearsal",
                "object_key": f"confidence/audio-{index}.m4a",
                "sha256": f"{index + 2:x}" * 64,
                "byte_size": 1024 + index,
                "content_type": "audio/mp4",
            },
        }

    candidates = [
        {
            "id": "40000000-0000-0000-0000-000000000001",
            "candidate_key": "clip-1",
            "clip_id": "50000000-0000-0000-0000-000000000001",
            "evidence": evidence(1),
            "prediction": {
                "id": "60000000-0000-0000-0000-000000000001",
                "predicted_value": "confident",
                "confidence_score": 0.91,
                "probability_distribution": {
                    "confident": 0.91, "in_between": 0.09,
                },
                "raw_output": {"logit": 2.31},
                "output_schema_version": "confidence-output-v1",
            },
            "eligible": True,
            "exclusion_reason_code": None,
            "score": 0.91,
            "rank": 1,
            "selected": True,
            "selection_mode": "deterministic",
            "selection_reason_code": "highest_ranked_eligible",
            "sampling_probability": 0.8,
            "rng_draw_index": None,
        },
        {
            "id": "40000000-0000-0000-0000-000000000002",
            "candidate_key": "clip-2",
            "clip_id": "50000000-0000-0000-0000-000000000002",
            "evidence": evidence(2),
            "eligible": False,
            "exclusion_reason_code": "audio_too_short",
            "score": None,
            "rank": None,
            "selected": False,
            "selection_mode": "excluded",
            "selection_reason_code": "ineligible_audio_duration",
            "sampling_probability": 0,
            "rng_draw_index": None,
        },
    ]
    return ConfidenceSamplingFrame(
        classification_run=classification,
        selection_run=selection,
        candidate_set_id="70000000-0000-0000-0000-000000000001",
        candidate_set_version="confidence-frame-v1",
        candidates=candidates,
    )


def test_complete_confidence_frame_is_typed_and_preserves_full_pool():
    payload = _frame().as_dict()
    assert payload["selection_run"]["execution_kind"] == "deterministic_policy"
    assert payload["selection_run"]["exploration_probability"] == 0.2
    assert len(payload["candidate_set"]["candidates"]) == 2
    assert payload["candidate_set"]["candidates"][0]["prediction"][
        "confidence_score"
    ] == 0.91
    assert payload["candidate_set"]["candidates"][1][
        "exclusion_reason_code"
    ] == "audio_too_short"


@pytest.mark.parametrize("mutation, message", [
    (
        lambda frame: frame.selection_run.__setitem__(
            "exploration_probability", 0.19
        ),
        "exploration_probability must be 0.20",
    ),
    (
        lambda frame: frame.selection_run.__setitem__(
            "threshold_version", "different-threshold"
        ),
        "threshold versions must match",
    ),
    (
        lambda frame: frame.candidates[1].__setitem__(
            "exclusion_reason_code", None
        ),
        "exclusion_reason_code is required",
    ),
    (
        lambda frame: frame.candidates[0].__setitem__("selected", False),
        "unselected candidate has invalid mode",
    ),
])
def test_invalid_frame_fails_before_rpc(mutation, message):
    frame = _frame()
    mutation(frame)
    with pytest.raises(Mlc2ContractError, match=message):
        frame.as_dict()


class _RpcResponse:
    data = {"candidate_set_id": "70000000-0000-0000-0000-000000000001"}


class _RpcCall:
    def execute(self):
        return _RpcResponse()


class _Client:
    def __init__(self):
        self.calls = []

    def rpc(self, name, payload):
        self.calls.append((name, payload))
        return _RpcCall()


def _envelope() -> CanonicalEnvelope:
    return CanonicalEnvelope(
        event_id="80000000-0000-0000-0000-000000000001",
        idempotency_key="confidence-frame:event-1",
        learning_surface_id="confidence_classification",
        pipeline_stage_id="classify",
        feedback_family_id="confident_voice",
        acquisition_principal_id="80000000-0000-0000-0000-000000000002",
        speaker_id="80000000-0000-0000-0000-000000000003",
        consent_snapshot_id="80000000-0000-0000-0000-000000000004",
        project_id="80000000-0000-0000-0000-000000000005",
        recording_attempt_id="80000000-0000-0000-0000-000000000006",
        take_id="80000000-0000-0000-0000-000000000007",
        source_event_id="recording-attempt:1:analysis",
        occurred_at=datetime(2026, 8, 27, 10, tzinfo=timezone.utc),
        execution_version={"contract": "confidence-frame-v1"},
        payload={"frame_kind": "take_confidence_candidates"},
    )


def test_store_uses_only_atomic_confidence_rpc():
    client = _Client()
    result = Mlc2ConfidenceStore(client).finalize_frame(
        outbox_event_id="90000000-0000-0000-0000-000000000001",
        worker_id="worker-1",
        envelope=_envelope(),
        frame=_frame(),
    )
    assert result["candidate_set_id"].endswith("0001")
    assert [name for name, _ in client.calls] == [
        "finalize_mlc2_confidence_frame_v1"
    ]
    rpc_payload = client.calls[0][1]
    assert rpc_payload["p_canonical_event"]["feedback_family_id"] == (
        "confident_voice"
    )
    assert len(rpc_payload["p_confidence_frame"]["candidate_set"][
        "candidates"
    ]) == 2


def test_store_rejects_wrong_surface_before_rpc():
    client = _Client()
    envelope = deepcopy(_envelope())
    object.__setattr__(envelope, "learning_surface_id", "praise_selection")
    object.__setattr__(envelope, "pipeline_stage_id", "select")
    object.__setattr__(envelope, "feedback_family_id", "great_formulation")
    with pytest.raises(Mlc2ContractError, match="confidence frame requires"):
        Mlc2ConfidenceStore(client).finalize_frame(
            outbox_event_id=UUID("90000000-0000-0000-0000-000000000001"),
            worker_id="worker-1",
            envelope=envelope,
            frame=_frame(),
        )
    assert client.calls == []
