"""The foundation confidence frame (G-6, audit 2026-09-22).

What is pinned: the frame the factory builds passes the contract's own
validator; the clips are the Take's snippets on the Take's own audio object
with exact spans; the foundation prediction agrees with the detector's bands;
the deterministic pick is the clip nearest a class boundary and the 20%
exploration draw is recorded; exactly one clip is selected; the frame is a
pure function of the event and the snippets (a replay is byte-identical);
nothing in it carries transcript text; and the worker boot line starts
nothing while the mode is dark.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from services.mlc2_confidence_frame_factory import (
    MIN_CLIP_MS,
    sweep_confidence_outbox,
)
from services.mlc2_confidence_producer import (
    ConfidenceProducerEvent,
)
from services.voice_confidence import VERSION as DETECTOR_VERSION


def _id(index: int) -> str:
    return str(uuid.UUID(int=index))


def _event(key: str = "confidence-event-1") -> ConfidenceProducerEvent:
    return ConfidenceProducerEvent(outbox_event_id=_id(7), payload={
        "producer_contract_version": "confidence-producer-v1",
        "event_id": _id(1),
        "idempotency_key": key,
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
        "occurred_at": datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc).isoformat(),
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
    })


def _snippet(index: int, score, *, start=None, duration=4000, transcript="spoken words"):
    metrics = None
    if score is not None:
        metrics = {"voice_confidence": {
            "score": score, "band": "x", "baseline": "user", "cues": 5,
            "version": DETECTOR_VERSION,
        }}
    return {
        "id": _id(100 + index),
        "start_offset_ms": (index * 5000) if start is None else start,
        "duration_ms": duration,
        "recording_id": _id(6),
        "transcript": transcript,
        "metrics": metrics,
    }


SNIPPETS = [
    _snippet(1, 0.8),                       # yes, far from a boundary
    _snippet(2, 0.45),                      # in_between, 0.05 from the yes edge
    _snippet(3, -0.7),                      # no, 0.2 from the no edge
    _snippet(4, 0.9, duration=MIN_CLIP_MS - 1),   # too short
    _snippet(5, None),                      # never stamped
    {"id": _id(106), "duration_ms": 3000, "metrics": None},   # no interval
]


class _Rpc:
    def __init__(self, calls, name, payload):
        self.calls, self.name, self.payload = calls, name, payload

    def execute(self):
        self.calls.append((self.name, self.payload))
        return SimpleNamespace(data=[{"id": _id(8), "status": "processed"}])


class _Client:
    def __init__(self):
        self.calls = []

    def rpc(self, name, payload):
        return _Rpc(self.calls, name, payload)


class _FakeRedis:
    def __init__(self, holder=None):
        self.store = {}
        if holder is not None:
            self.store["willab:confidence-producer:chain"] = holder

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    def get(self, key):
        return self.store.get(key)

    def expire(self, key, ttl):
        return True


class TestTheSweepUnderFounderCanary:
    """The chain's ownership rule, with the mode monkeypatched open: the
    real constant stays dark (asserted above), so this is the only place the
    founder_canary branch runs before the founder's own change."""

    def _open(self, monkeypatch, redis, client):
        import services.job_queue as job_queue
        import services.mlc2_confidence_frame_factory as factory

        monkeypatch.setattr(factory, "_mode", lambda: SimpleNamespace(
            mode="founder_canary", canonical_writes_enabled=True))
        monkeypatch.setattr(job_queue, "get_redis", lambda *a, **k: redis)
        enqueued = []
        monkeypatch.setattr(job_queue, "enqueue",
                            lambda path, *args, **kw: enqueued.append((path, args, kw)) or True)
        import services.db as db_module
        monkeypatch.setattr(db_module, "db", SimpleNamespace(
            client=client, get_snippets_by_session=lambda take_id: SNIPPETS))
        return enqueued

    def test_the_owner_claims_finalizes_and_rearms(self, monkeypatch):
        class _ClaimingClient(_Client):
            def rpc(self, name, payload):
                if name == "claim_mlc2_confidence_outbox_v1":
                    self.calls.append((name, payload))
                    return SimpleNamespace(execute=lambda: SimpleNamespace(
                        data=[{"id": _id(7), "payload": _event().payload}]))
                return super().rpc(name, payload)

        client = _ClaimingClient()
        enqueued = self._open(monkeypatch, _FakeRedis(), client)
        result = sweep_confidence_outbox("chain-a")
        assert result == {"claimed": 1, "finalized": 1, "failed": 0, "rearmed": True}
        assert [n for n, _ in client.calls] == [
            "claim_mlc2_confidence_outbox_v1", "finalize_mlc2_confidence_frame_v1"]
        assert enqueued and enqueued[0][1] == ("chain-a",)
