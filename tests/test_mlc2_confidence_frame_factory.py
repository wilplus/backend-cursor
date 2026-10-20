"""
STORY    As the founder, I want the confidence frame built from a Take's
         snippets to be exact, deterministic, free of transcript text and
         off unless the mode is open, so that blind labels are reproducible
         and nothing runs before I switch it on.
OUTCOME
  O1  The frame passes the contract's validator: every clip is on the Take's
      own audio object with its exact span, and exactly one clip is selected.
  O2  A replay (rows in any order) is byte-identical.
  O3  Nothing in the frame carries transcript text.
  O4  While the mode is dark, the worker boot line starts nothing.
  O5  Under founder_canary the sweep owner claims, finalizes and re-arms.
  O6  A Take with no clip a rater could judge is promoted plainly and opens
      no outbox event, because its frame could never be finalized.
  O7  A failed event is not offered again in 30 seconds: a contract failure
      waits a week, any other failure waits longer after each attempt
      (founder's pg_stat_statements, 2026-10-20: 976 failures, 540 claims).
PROVES   O1 -> test_the_frame_is_valid_exact_and_selects_one_clip
         O2 -> test_a_replay_is_byte_identical
         O3 -> test_no_transcript_text_reaches_the_frame
         O4 -> test_the_boot_line_starts_nothing_while_dark
         O5 -> test_the_owner_claims_finalizes_and_rearms
         O6 -> test_a_take_without_a_clip_opens_no_outbox_event
         O7 -> test_a_failure_is_not_offered_again_in_thirty_seconds
WHY      G-6, audit 2026-09-22.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import json

from services.mlc2_confidence_cutover import DARK, resolve_confidence_cutover
from services.mlc2_confidence_frame_factory import (
    MIN_CLIP_MS,
    foundation_frame_factory,
    start_confidence_producer_chain,
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


def _frame(snippets=None):
    rows = SNIPPETS if snippets is None else snippets
    database = SimpleNamespace(get_snippets_by_session=lambda take_id, **_: rows)
    return foundation_frame_factory(database)(_event()).as_dict()


def _bytes(frame) -> str:
    return json.dumps(frame, sort_keys=True, default=str)


class TestTheFrame:
    def test_the_frame_is_valid_exact_and_selects_one_clip(self):
        # as_dict() runs the contract's validator and raises on a bad frame.
        candidates = _frame()["candidate_set"]["candidates"]
        # The five rows with an interval are clips; the one without is not.
        assert len(candidates) == 5
        for c in candidates:
            assert c["evidence"]["object"]["object_key"] == "takes/one.webm"
        spans = {c["clip_id"]: c["evidence"]["coordinates"] for c in candidates}
        assert spans[_id(101)] == {"start_ms": 5000, "end_ms": 9000}
        assert [c["clip_id"] for c in candidates if c["selected"]] == [_id(102)]
        assert [c["clip_id"] for c in candidates if not c["eligible"]] == [
            _id(104), _id(105)]

    def test_a_replay_is_byte_identical(self):
        assert _bytes(_frame()) == _bytes(_frame(list(reversed(SNIPPETS))))

    def test_no_transcript_text_reaches_the_frame(self):
        frame = _bytes(_frame())
        assert "takes/one.webm" in frame
        assert "spoken words" not in frame
        assert "transcript" not in frame


def test_the_boot_line_starts_nothing_while_dark(monkeypatch):
    import services.job_queue as job_queue
    import services.mlc2_confidence_frame_factory as factory

    def _must_not_run(*a, **k):
        raise AssertionError("dark mode touched the broker")

    monkeypatch.setattr(factory, "_mode",
                        lambda: resolve_confidence_cutover(DARK))
    monkeypatch.setattr(job_queue, "get_redis", _must_not_run)
    monkeypatch.setattr(job_queue, "enqueue", _must_not_run)
    line = start_confidence_producer_chain()
    assert line.startswith("dark: not started")


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
    """The chain's ownership rule, with the mode monkeypatched to
    founder_canary and the broker, queue and database faked."""

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
            client=client, get_snippets_by_session=lambda take_id, **_: SNIPPETS))
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


def test_a_take_without_a_clip_opens_no_outbox_event(monkeypatch):
    import services.take_lifecycle as lifecycle

    monkeypatch.setattr(lifecycle, "confidence_canonical_writes_enabled_for",
                        lambda database, attempt_id: True)

    def promoted_through(rows):
        calls = []
        database = SimpleNamespace(
            get_snippets_by_session=lambda sid, **_: rows,
            promote_recording_attempt_with_confidence_outbox=(
                lambda **kw: calls.append("canonical") or {"take_id": _id(6)}),
            promote_recording_attempt_to_take=(
                lambda **kw: calls.append("plain") or {"take_id": _id(6)}),
        )
        lifecycle.promote_attempt(
            database=database, attempt_id=_id(6), result={"snippet_count": 1},
            confidence_producer_manifest={"source_schema_version": "x"})
        return calls

    unjudgeable = [_snippet(1, None), _snippet(2, 0.8, duration=MIN_CLIP_MS - 1)]
    assert promoted_through(unjudgeable) == ["plain"]
    assert promoted_through(SNIPPETS) == ["canonical"]


def test_a_failure_is_not_offered_again_in_thirty_seconds(monkeypatch):
    from services.mlc2_confidence_producer import (
        CONTRACT_RETRY_SECONDS,
        RETRY_BASE_SECONDS,
    )

    class _FailingClient(_Client):
        def rpc(self, name, payload):
            if name == "claim_mlc2_confidence_outbox_v1":
                return SimpleNamespace(execute=lambda: SimpleNamespace(data=[
                    {"id": _id(7), "attempt_count": 3, "payload": _event().payload},
                ]))
            return super().rpc(name, payload)

    def waits_after(read):
        client = _FailingClient()
        TestTheSweepUnderFounderCanary()._open(monkeypatch, _FakeRedis(), client)
        import services.db as db_module
        db_module.db.get_snippets_by_session = read
        result = sweep_confidence_outbox("chain-a")
        assert result["failed"] == 1
        [(name, payload)] = client.calls
        assert name == "fail_mlc2_outbox_event_v1"
        return payload["p_error_code"], payload["p_retry_after_seconds"]

    def unreadable(take_id, **_):
        raise ConnectionError("database hiccup")

    assert waits_after(lambda take_id, **_: [_snippet(1, None)]) == (
        "NoEligibleConfidenceClip:confidence_frame_failed", CONTRACT_RETRY_SECONDS)
    assert waits_after(unreadable) == (
        "ConnectionError:confidence_frame_failed", RETRY_BASE_SECONDS * 4)
