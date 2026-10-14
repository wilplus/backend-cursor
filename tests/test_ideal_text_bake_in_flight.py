"""One Manager per document (founder 2026-10-14, the blank lens screen).

The bake is enqueued the moment a Take flips ready and the speaker's screen
asks for the marks within the same second. The reader used to run the whole
Manager live beside the bake worker's identical run. These pin the contract:
a reader that finds a bake in flight waits for its row and never computes a
second copy; still in flight at the deadline, it answers "ask me again".
"""
from __future__ import annotations

import pytest

from services import ideal_text_feedback_bake as bake
from services import job_queue
from services.ideal_text_enrichment import SectionPending

ARC, ACTOR, SNAPSHOT = "arc-1", "actor-1", "snap-1"
BLOCK = {"changes": [{"id": "cand-1", "source": "confident_voice"}],
         "style_changes": []}
CORE = {"text": "Hello.", "latest_take_session_id": "take-1", "version": 1}
HEAD = {"id": SNAPSHOT,
        "payload": {"text": "Hello.", "latest_take_session_id": "take-1",
                    "version": 1}}


class _FakeRedis:
    def __init__(self):
        self.keys: dict[str, str] = {}

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True

    def delete(self, *keys):
        return sum(self.keys.pop(k, None) is not None for k in keys)

    def exists(self, *keys):
        return sum(k in self.keys for k in keys)


class _FakeDb:
    def __init__(self):
        self.stored: dict | None = None

    def read_ideal_text_feedback_bake(self, arc_id, actor_id, snapshot_id):
        return self.stored

    def write_ideal_text_feedback_bake(self, arc_id, actor_id, snapshot_id,
                                       block, computed_over_ms):
        self.stored = block
        return True


@pytest.fixture
def world(monkeypatch):
    redis = _FakeRedis()
    monkeypatch.setattr(bake, "_bake_enabled", lambda: True)
    monkeypatch.setattr(job_queue, "queue_configured", lambda: True)
    monkeypatch.setattr(job_queue, "get_redis", lambda **_k: redis)
    monkeypatch.setattr(job_queue, "bake_queue_name", lambda: "bakes")
    monkeypatch.setattr(job_queue, "enqueue", lambda *_a, **_k: True)
    # The reader's live path and the bake's compute are the same Manager;
    # the test counts how many times it runs.
    runs: list[str] = []
    from routes.v2 import explore_ideal_text as route

    def _manager(arc_id, *_a, **_k):
        runs.append("live")
        return BLOCK
    monkeypatch.setattr(route, "_tracked_changes_block", _manager)

    def _compute(arc_id, *_a, **_k):
        runs.append("bake")
        return BLOCK, 10
    monkeypatch.setattr(bake, "_compute_block", _compute)
    # No real sleeping: the clock is the number of waits taken.
    waited: list[float] = []
    monkeypatch.setattr(bake, "sleep", lambda s: waited.append(s))
    monkeypatch.setattr(bake, "monotonic", lambda: float(len(waited)))
    return redis, runs, waited


def test_a_reader_waits_for_the_bake_in_flight_instead_of_recomputing(
        world, monkeypatch):
    redis, runs, waited = world
    db = _FakeDb()
    assert bake.enqueue_bake(ARC, ACTOR, "spoken") is True
    assert bake.bake_in_flight(ARC, ACTOR, SNAPSHOT) is True

    # The worker picks the job up during the reader's third wait.
    def _sleep(seconds):
        waited.append(seconds)
        if len(waited) == 3:
            assert bake.bake_for_snapshot(db, ARC, ACTOR, HEAD) is True
    monkeypatch.setattr(bake, "sleep", _sleep)

    block = bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    assert [row["id"] for row in block["changes"]] == ["cand-1"]
    assert runs == ["bake"]
    # The bake released its marks on the way out.
    assert bake.bake_in_flight(ARC, ACTOR, SNAPSHOT) is False


def test_a_bake_still_in_flight_at_the_deadline_answers_ask_again(world):
    redis, runs, waited = world
    db = _FakeDb()
    bake.enqueue_bake(ARC, ACTOR, "spoken")
    with pytest.raises(SectionPending):
        bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    assert runs == []
    assert len(waited) >= bake.BAKE_WAIT_SECONDS


def test_without_a_bake_in_flight_the_reader_computes_live_as_before(world):
    _redis, runs, _waited = world
    db = _FakeDb()
    block = bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    assert [row["id"] for row in block["changes"]] == ["cand-1"]
    assert runs == ["live"]
    assert db.stored == BLOCK  # the backfill, as before
