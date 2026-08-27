from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from services.mlc2_foundation import (
    CanonicalEnvelope,
    DATA_EPOCH,
    LEARNING_CONTRACT_VERSION,
    LEARNING_SURFACES,
    Mlc2ContractError,
    Mlc2FoundationStore,
    canonical_surface_id,
    stable_json_sha256,
    verify_object_bytes,
)


def _ids(count: int):
    return [uuid4() for _ in range(count)]


def _envelope(**overrides):
    event_id, principal_id, speaker_id, consent_id, take_id = _ids(5)
    values = {
        "event_id": event_id,
        "idempotency_key": "confidence:take:event-v1",
        "learning_surface_id": "confidence_classification",
        "pipeline_stage_id": "classify",
        "feedback_family_id": "confident_voice",
        "acquisition_principal_id": principal_id,
        "speaker_id": speaker_id,
        "consent_snapshot_id": consent_id,
        "take_id": take_id,
        "source_event_id": "product-action-1",
        "occurred_at": datetime(2026, 8, 27, tzinfo=timezone.utc),
        "execution_version": {"classifier": "confidence-v1"},
        "payload": {"prediction_ref": "prediction-1"},
    }
    values.update(overrides)
    return CanonicalEnvelope(**values)


def test_registry_has_exactly_seven_surfaces():
    assert len(LEARNING_SURFACES) == 7
    assert "moment_suggestion" not in LEARNING_SURFACES


def test_alias_resolution_is_explicit_and_ambiguous_legacy_name_fails_closed():
    assert canonical_surface_id("say_it_stronger") == "correction_generation"
    assert canonical_surface_id("ideal_text") == "ideal_text_generation"
    with pytest.raises(Mlc2ContractError, match="ambiguous legacy vocabulary"):
        canonical_surface_id("moment_suggestion")
    with pytest.raises(Mlc2ContractError, match="unknown canonical"):
        canonical_surface_id("new_magic_ranker")


def test_envelope_stamps_contract_epoch_and_surface_payload_type():
    result = _envelope().as_dict()
    assert result["learning_contract_version"] == LEARNING_CONTRACT_VERSION
    assert result["data_epoch"] == DATA_EPOCH
    assert result["payload_type"] == "confidence_event"
    assert result["feedback_family_id"] == "confident_voice"


def test_feedback_surface_requires_family_and_nonfeedback_surface_rejects_it():
    with pytest.raises(Mlc2ContractError, match="requires an explicit"):
        _envelope(feedback_family_id=None).as_dict()
    with pytest.raises(Mlc2ContractError, match="requires null"):
        _envelope(
            learning_surface_id="ideal_text_generation",
            pipeline_stage_id="generate",
            feedback_family_id="great_formulation",
        ).as_dict()


def test_envelope_rejects_naive_timestamp_and_empty_execution_version():
    with pytest.raises(Mlc2ContractError, match="timezone-aware"):
        _envelope(occurred_at=datetime(2026, 8, 27)).as_dict()
    with pytest.raises(Mlc2ContractError, match="non-empty"):
        _envelope(execution_version={}).as_dict()


def test_json_and_r2_checksums_are_deterministic_and_verify_bytes():
    assert stable_json_sha256({"b": 2, "a": 1}) == stable_json_sha256({
        "a": 1, "b": 2,
    })
    content = b"immutable-r2-object"
    digest = __import__("hashlib").sha256(content).hexdigest()
    assert verify_object_bytes(
        content, expected_sha256=digest, expected_byte_size=len(content)
    )["verified"] is True
    assert verify_object_bytes(
        content, expected_sha256="0" * 64, expected_byte_size=len(content)
    )["verified"] is False


class _Rpc:
    def __init__(self, calls, name, payload):
        self.calls = calls
        self.name = name
        self.payload = payload

    def execute(self):
        self.calls.append((self.name, self.payload))
        if self.name == "claim_mlc2_outbox_events_v1":
            return SimpleNamespace(data=[{"id": "outbox-1"}])
        return SimpleNamespace(data={"id": "stored-1"})


class _Client:
    def __init__(self):
        self.calls = []

    def rpc(self, name, payload):
        return _Rpc(self.calls, name, payload)


def test_store_uses_only_canonical_rpcs_and_validated_surface_ids():
    client = _Client()
    store = Mlc2FoundationStore(client)
    aggregate_id = uuid4()
    row = store.enqueue(
        idempotency_key="correction:1",
        event_type="feedback_decided",
        learning_surface_id="say_it_stronger",
        aggregate_type="take",
        aggregate_id=aggregate_id,
        payload={"decision": "rewrite_accept"},
        occurred_at=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )
    assert row == {"id": "stored-1"}
    name, payload = client.calls[-1]
    assert name == "enqueue_mlc2_outbox_event_v1"
    assert payload["p_learning_surface_id"] == "correction_generation"


def test_store_claim_and_failure_keep_retry_contract_explicit():
    client = _Client()
    store = Mlc2FoundationStore(client)
    assert store.claim(worker_id="mlc2-worker", limit=3) == [{"id": "outbox-1"}]
    store.fail(
        outbox_event_id=uuid4(),
        worker_id="mlc2-worker",
        error_code="TRANSIENT_PROVIDER_FAILURE",
        retry_after_seconds=45,
    )
    assert client.calls[-1][0] == "fail_mlc2_outbox_event_v1"
    assert client.calls[-1][1]["p_retry_after_seconds"] == 45


def test_config_keeps_release_training_and_promotion_hard_disabled():
    from config import Config

    assert Config.MLC2_DATASET_RELEASES_ENABLED is False
    assert Config.MLC2_TRAINING_ENABLED is False
    assert Config.MLC2_PROMOTION_ENABLED is False
