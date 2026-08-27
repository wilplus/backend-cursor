from datetime import datetime, timezone
from types import SimpleNamespace
import uuid

import pytest

from services.mlc2_confidence_producer import (
    ConfidenceProducerEvent,
    Mlc2ConfidenceProducerStore,
    build_source_manifest,
)
from services.mlc2_foundation import Mlc2ContractError


def _id(index: int) -> str:
    return str(uuid.UUID(int=index))


def _event_payload() -> dict:
    return {
        "producer_contract_version": "confidence-producer-v1",
        "event_id": _id(1),
        "idempotency_key": "confidence-event-1",
        "learning_surface_id": "confidence_classification",
        "pipeline_stage_id": "classify",
        "feedback_family_id": "confident_voice",
        "payload_type": "confidence_event",
        "acquisition_principal_id": _id(2),
        "speaker_id": _id(3),
        "consent_snapshot_id": _id(4),
        "project_id": _id(5),
        "recording_attempt_id": _id(6),
        "take_id": _id(6),
        "source_event_id": "recording-attempt:6:successful-take",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "source_manifest": {
            "source_schema_version": "confidence-source-audio-v1",
            "audio": {
                "object_store": "cloudflare_r2",
                "bucket": "lab-audio",
                "object_key": "takes/one.webm",
                "sha256": "b" * 64,
                "byte_size": 1024,
                "content_type": "audio/webm",
            },
        },
        "source_manifest_sha256": "a" * 64,
        "payload": {
            "frame_kind": "take_confidence_candidates",
            "source_manifest_sha256": "a" * 64,
        },
    }


def test_source_manifest_is_exact_audio_identity():
    manifest = build_source_manifest(
        audio_bytes=b"voice-bytes",
        object_store="cloudflare_r2",
        bucket="lab-audio",
        object_key="/takes/one.webm",
        filename="one.webm",
    )
    assert manifest["source_schema_version"] == "confidence-source-audio-v1"
    assert manifest["audio"]["object_key"] == "takes/one.webm"
    assert manifest["audio"]["content_type"] == "audio/webm"
    assert manifest["audio"]["byte_size"] == 11
    assert len(manifest["audio"]["sha256"]) == 64


def test_source_manifest_rejects_non_r2_and_empty_audio():
    with pytest.raises(Mlc2ContractError, match="Cloudflare R2"):
        build_source_manifest(
            audio_bytes=b"voice", object_store="supabase", bucket="b",
            object_key="k", filename="a.webm",
        )
    with pytest.raises(Mlc2ContractError, match="non-empty"):
        build_source_manifest(
            audio_bytes=b"", object_store="cloudflare_r2", bucket="b",
            object_key="k", filename="a.webm",
        )


def test_outbox_event_builds_the_only_valid_confidence_envelope():
    envelope = ConfidenceProducerEvent(
        outbox_event_id=_id(7), payload=_event_payload()
    ).envelope().as_dict()
    assert envelope["learning_surface_id"] == "confidence_classification"
    assert envelope["pipeline_stage_id"] == "classify"
    assert envelope["feedback_family_id"] == "confident_voice"
    assert envelope["take_id"] == _id(6)


@pytest.mark.parametrize("field,value", [
    ("learning_surface_id", "praise_generation"),
    ("pipeline_stage_id", "select"),
    ("feedback_family_id", "great_formulation"),
    ("payload_type", "praise_generation_event"),
])
def test_outbox_event_rejects_cross_surface_semantics(field, value):
    payload = _event_payload()
    payload[field] = value
    with pytest.raises(Mlc2ContractError, match="semantics"):
        ConfidenceProducerEvent(_id(7), payload).envelope()


class _Rpc:
    def __init__(self, calls, name, payload):
        self.calls = calls
        self.name = name
        self.payload = payload

    def execute(self):
        self.calls.append((self.name, self.payload))
        return SimpleNamespace(data=[{"id": _id(8)}])


class _Client:
    def __init__(self):
        self.calls = []

    def rpc(self, name, payload):
        return _Rpc(self.calls, name, payload)


def test_worker_store_claims_only_the_typed_confidence_rpc():
    client = _Client()
    rows = Mlc2ConfidenceProducerStore(client).claim(
        worker_id="slice4-worker", limit=3, lease_seconds=90
    )
    assert rows == [{"id": _id(8)}]
    assert client.calls == [(
        "claim_mlc2_confidence_outbox_v1",
        {
            "p_worker_id": "slice4-worker",
            "p_limit": 3,
            "p_lease_seconds": 90,
        },
    )]
