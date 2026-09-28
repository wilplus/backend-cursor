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

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services.mlc2_confidence_frame_factory import (
    EXPLORATION_PROBABILITY,
    MIN_CLIP_MS,
    NoEligibleConfidenceClip,
    boundary_distance,
    build_foundation_frame,
    foundation_frame_factory,
    foundation_prediction,
    start_confidence_producer_chain,
    sweep_confidence_outbox,
)
from services.mlc2_confidence_producer import (
    ConfidenceProducerEvent,
    DarkConfidenceWorker,
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


class TestThePrediction:
    @pytest.mark.parametrize("score,expected", [
        (1.0, "yes"), (0.5, "yes"), (0.49, "in_between"), (0.0, "in_between"),
        (-0.49, "in_between"), (-0.5, "no"), (-1.0, "no"),
    ])
    def test_the_class_is_the_detectors_band(self, score, expected):
        read = foundation_prediction(score)
        assert read["predicted_value"] == expected
        distribution = read["probability_distribution"]
        assert max(distribution, key=distribution.get) == expected
        assert abs(sum(distribution.values()) - 1.0) < 1e-6
        assert read["confidence_score"] >= 0.5

    def test_boundary_distance_is_symmetric_and_zero_on_an_edge(self):
        assert boundary_distance(0.5) == 0
        assert boundary_distance(-0.5) == 0
        assert boundary_distance(0.0) == 0.5
        assert boundary_distance(0.8) == boundary_distance(-0.8)


class TestTheFrame:
    def test_the_frame_passes_the_contract_validator(self):
        payload = build_foundation_frame(_event(), snippets=SNIPPETS).as_dict()
        assert payload["selection_run"]["exploration_probability"] == EXPLORATION_PROBABILITY
        assert payload["classification_run"]["assignment_origin"] == "foundation"
        assert payload["classification_run"]["detector_version"] == DETECTOR_VERSION
        assert payload["classification_run"]["configuration"]["snippets_without_interval"] == 1

    def test_every_clip_is_an_exact_span_on_the_takes_own_object(self):
        payload = build_foundation_frame(_event(), snippets=SNIPPETS).as_dict()
        candidates = payload["candidate_set"]["candidates"]
        assert len(candidates) == 5
        by_clip = {c["clip_id"]: c for c in candidates}
        two = by_clip[_id(102)]
        assert two["evidence"]["coordinates"] == {"start_ms": 10000, "end_ms": 14000}
        assert two["evidence"]["object"]["object_key"] == "takes/one.webm"
        assert two["evidence"]["object"]["sha256"] == "b" * 64
        assert two["evidence"]["object"]["content_type"] == "audio/webm"
        assert len({c["evidence"]["object"]["id"] for c in candidates}) == 1

    def test_eligibility_and_ranking(self):
        payload = build_foundation_frame(_event(), snippets=SNIPPETS).as_dict()
        by_clip = {c["clip_id"]: c for c in payload["candidate_set"]["candidates"]}
        assert by_clip[_id(104)]["exclusion_reason_code"] == "audio_too_short"
        assert by_clip[_id(105)]["exclusion_reason_code"] == "no_confidence_read"
        assert "prediction" not in by_clip[_id(105)]
        ranks = {c: by_clip[c]["rank"] for c in (_id(101), _id(102), _id(103))}
        assert ranks == {_id(102): 1, _id(103): 2, _id(101): 3}
        assert by_clip[_id(101)]["prediction"]["predicted_value"] == "yes"
        assert by_clip[_id(102)]["prediction"]["predicted_value"] == "in_between"
        assert by_clip[_id(103)]["prediction"]["predicted_value"] == "no"

    def test_exactly_one_clip_is_selected_and_probabilities_are_recorded(self):
        payload = build_foundation_frame(_event(), snippets=SNIPPETS).as_dict()
        candidates = payload["candidate_set"]["candidates"]
        selected = [c for c in candidates if c["selected"]]
        assert len(selected) == 1
        eligible = [c for c in candidates if c["eligible"]]
        assert abs(sum(c["sampling_probability"] for c in eligible) - 1.0) < 1e-6
        assert all(c["sampling_probability"] == 0 for c in candidates if not c["eligible"])
        draws = payload["selection_run"]["rng_draws"]
        assert draws and draws[0]["index"] == 0
        assert selected[0]["selection_mode"] in {"deterministic", "exploration"}
        if selected[0]["selection_mode"] == "deterministic":
            assert selected[0]["rank"] == 1
        else:
            assert selected[0]["rng_draw_index"] == 1

    def test_both_selection_modes_occur_and_are_reproducible(self):
        modes = {}
        for i in range(40):
            payload = build_foundation_frame(_event(f"key-{i}"), snippets=SNIPPETS).as_dict()
            chosen = next(c for c in payload["candidate_set"]["candidates"] if c["selected"])
            modes.setdefault(chosen["selection_mode"], 0)
            modes[chosen["selection_mode"]] += 1
        assert set(modes) == {"deterministic", "exploration"}
        assert modes["deterministic"] > modes["exploration"]

    def test_a_replay_is_byte_identical(self):
        first = build_foundation_frame(_event(), snippets=SNIPPETS).as_dict()
        second = build_foundation_frame(_event(), snippets=list(reversed(SNIPPETS))).as_dict()
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)

    def test_a_different_event_is_a_different_frame(self):
        first = build_foundation_frame(_event("a"), snippets=SNIPPETS).as_dict()
        second = build_foundation_frame(_event("b"), snippets=SNIPPETS).as_dict()
        assert first["candidate_set"]["id"] != second["candidate_set"]["id"]

    def test_nothing_in_the_frame_carries_the_words(self):
        text = json.dumps(build_foundation_frame(_event(), snippets=SNIPPETS).as_dict())
        assert "spoken words" not in text
        assert "transcript" not in text

    def test_a_take_with_no_eligible_clip_is_refused_by_name(self):
        with pytest.raises(NoEligibleConfidenceClip):
            build_foundation_frame(_event(), snippets=[_snippet(1, None)])
        with pytest.raises(NoEligibleConfidenceClip):
            build_foundation_frame(_event(), snippets=[])


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


class TestTheWorkerUsesTheFactory:
    def test_the_worker_finalizes_the_foundation_frame(self):
        from services.mlc2_confidence import Mlc2ConfidenceStore
        from services.mlc2_confidence_producer import Mlc2ConfidenceProducerStore

        client = _Client()
        database = SimpleNamespace(get_snippets_by_session=lambda take_id: SNIPPETS)
        worker = DarkConfidenceWorker(
            producer_store=Mlc2ConfidenceProducerStore(client),
            frame_store=Mlc2ConfidenceStore(client),
            frame_factory=foundation_frame_factory(database),
        )
        worker.process_claimed({"id": _id(7), "payload": _event().payload}, worker_id="t")
        assert [name for name, _ in client.calls] == ["finalize_mlc2_confidence_frame_v1"]
        frame = client.calls[0][1]["p_confidence_frame"]
        assert len(frame["candidate_set"]["candidates"]) == 5

    def test_a_take_without_clips_fails_the_event_back_to_the_outbox(self):
        from services.mlc2_confidence import Mlc2ConfidenceStore
        from services.mlc2_confidence_producer import Mlc2ConfidenceProducerStore

        client = _Client()
        database = SimpleNamespace(get_snippets_by_session=lambda take_id: [])
        worker = DarkConfidenceWorker(
            producer_store=Mlc2ConfidenceProducerStore(client),
            frame_store=Mlc2ConfidenceStore(client),
            frame_factory=foundation_frame_factory(database),
        )
        with pytest.raises(NoEligibleConfidenceClip):
            worker.process_claimed({"id": _id(7), "payload": _event().payload}, worker_id="t")
        assert [name for name, _ in client.calls] == ["fail_mlc2_outbox_event_v1"]


class TestTheModeStaysDark:
    def test_boot_starts_nothing_while_dark(self, monkeypatch):
        import services.job_queue as job_queue

        def boom(*a, **k):
            raise AssertionError("dark mode must not touch the broker")

        monkeypatch.setattr(job_queue, "get_redis", boom)
        monkeypatch.setattr(job_queue, "enqueue", boom)
        line = start_confidence_producer_chain()
        assert line.startswith("dark: not started")

    def test_a_sweep_tick_claims_nothing_while_dark(self, monkeypatch):
        import services.job_queue as job_queue

        def boom(*a, **k):
            raise AssertionError("dark mode must not touch the broker")

        monkeypatch.setattr(job_queue, "get_redis", boom)
        assert sweep_confidence_outbox("chain") == {"skipped": "dark", "claimed": 0}

    def test_the_constant_is_still_dark(self):
        from config import Config

        assert Config.MLC2_CONFIDENCE_CUTOVER_MODE == "dark"


class TestReplayInputsAreBound:
    def test_a_changed_stamp_between_deliveries_is_a_different_frame(self):
        """The finalizer refuses a replay whose pool hash differs; the run's
        request hash binds the rows the frame was built from, so the refusal
        can be attributed to changed inputs rather than to the worker."""
        first = build_foundation_frame(_event(), snippets=SNIPPETS).as_dict()
        changed = [dict(s) for s in SNIPPETS]
        changed[1] = _snippet(2, 0.30)   # re-stamped between two deliveries
        second = build_foundation_frame(_event(), snippets=changed).as_dict()
        assert json.dumps(first, sort_keys=True) != json.dumps(second, sort_keys=True)
        assert (first["classification_run"]["request_sha256"]
                != second["classification_run"]["request_sha256"])
        assert (first["classification_run"]["configuration"]["inputs_sha256"]
                != second["classification_run"]["configuration"]["inputs_sha256"])

    def test_the_served_lean_is_recorded_beside_the_foundation_class(self):
        payload = build_foundation_frame(_event(), snippets=SNIPPETS).as_dict()
        by_clip = {c["clip_id"]: c for c in payload["candidate_set"]["candidates"]}
        # 0.45 is `in_between` at the band edges but leans `confident` by sign.
        assert by_clip[_id(102)]["prediction"]["predicted_value"] == "in_between"
        assert by_clip[_id(102)]["prediction"]["raw_output"]["served_lean"] == "confident"
        assert by_clip[_id(103)]["prediction"]["raw_output"]["served_lean"] == "unconfident"

    def test_a_refused_finalize_fails_the_event_back_to_the_outbox(self):
        from services.mlc2_confidence import Mlc2ConfidenceStore
        from services.mlc2_confidence_producer import Mlc2ConfidenceProducerStore

        class _RefusingClient(_Client):
            def rpc(self, name, payload):
                if name == "finalize_mlc2_confidence_frame_v1":
                    raise RuntimeError("idempotent confidence replay changed immutable frame")
                return super().rpc(name, payload)

        client = _RefusingClient()
        database = SimpleNamespace(get_snippets_by_session=lambda take_id: SNIPPETS)
        worker = DarkConfidenceWorker(
            producer_store=Mlc2ConfidenceProducerStore(client),
            frame_store=Mlc2ConfidenceStore(client),
            frame_factory=foundation_frame_factory(database),
        )
        with pytest.raises(RuntimeError):
            worker.process_claimed({"id": _id(7), "payload": _event().payload}, worker_id="t")
        assert [name for name, _ in client.calls] == ["fail_mlc2_outbox_event_v1"]
        assert client.calls[0][1]["p_error_code"].startswith("RuntimeError:")


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

    def test_a_chain_that_does_not_own_the_lease_claims_nothing(self, monkeypatch):
        client = _Client()
        enqueued = self._open(monkeypatch, _FakeRedis(holder="chain-a"), client)
        result = sweep_confidence_outbox("chain-b")
        assert result == {"skipped": "not_lease_owner", "claimed": 0, "rearmed": False}
        assert client.calls == []
        assert enqueued == []
