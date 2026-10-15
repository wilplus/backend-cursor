"""One Manager per document (founder 2026-10-14, the blank lens screen).

The bake is enqueued the moment a Take flips ready and the speaker's screen
asks for the marks within the same second. The reader used to run the whole
Manager live beside the bake worker's identical run. These pin the contract:
a reader that finds a bake in flight answers "ask me again" at once, never
computes a second copy and never holds the request while it waits; the next
read is served the bake's row.
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

    def get(self, key):
        return self.keys.get(key)

    def delete(self, *keys):
        return sum(self.keys.pop(k, None) is not None for k in keys)

    def exists(self, *keys):
        return sum(k in self.keys for k in keys)


class _FakeDb:
    def __init__(self, analysis_state="ready"):
        self.stored: dict | None = None
        self.analysis_state = analysis_state

    def v2_get_session_by_id(self, session_id):
        return {"id": session_id, "analysis_state": self.analysis_state}

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

    answers = {"live": BLOCK}

    def _manager(arc_id, *_a, **_k):
        runs.append("live")
        return answers["live"]
    monkeypatch.setattr(route, "_tracked_changes_block", _manager)

    def _compute(arc_id, *_a, **_k):
        runs.append("bake")
        return BLOCK, 10
    monkeypatch.setattr(bake, "_compute_block", _compute)
    return redis, runs, answers


def test_a_reader_finding_a_bake_in_flight_asks_again_and_never_recomputes(
        world):
    _redis, runs, _answers = world
    db = _FakeDb()
    assert bake.enqueue_bake(ARC, ACTOR, "spoken") is True
    with pytest.raises(SectionPending):
        bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    assert runs == []

    # The worker bakes; the page's next ask is served the stored row.
    assert bake.bake_for_snapshot(db, ARC, ACTOR, HEAD) is True
    block = bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    assert [row["id"] for row in block["changes"]] == ["cand-1"]
    assert runs == ["bake"]
    # The bake released its marks on the way out.
    assert bake.bake_in_flight(ARC, ACTOR, SNAPSHOT) is False


def test_without_a_bake_in_flight_the_reader_computes_live_as_before(world):
    _redis, runs, _answers = world
    db = _FakeDb()
    block = bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    assert [row["id"] for row in block["changes"]] == ["cand-1"]
    assert runs == ["live"]
    assert db.stored == BLOCK  # the backfill, as before


# ── ONE LIVE MANAGER PER DOCUMENT, AND NO RECOMPUTE STORM (2026-10-15) ────
#
# The same document's Manager ran six times in thirty-one seconds on the web
# service: the page's settle loop asked again and again, nothing was stored
# (an empty lane never is), and every ask computed live beside the last.


def test_a_second_reader_during_a_live_run_asks_again_and_never_recomputes(
        world):
    redis, runs, _answers = world
    db = _FakeDb()
    # Another request holds the live lock for this exact document.
    redis.set(bake._live_lock_key(ARC, ACTOR, SNAPSHOT), "1")
    with pytest.raises(SectionPending):
        bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    assert runs == []
    # Its run finished and left the block behind: the next ask is served it.
    redis.delete(bake._live_lock_key(ARC, ACTOR, SNAPSHOT))
    bake._remember_live_block(db, ARC, ACTOR, SNAPSHOT, CORE, BLOCK)
    block = bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    assert [row["id"] for row in block["changes"]] == ["cand-1"]
    assert runs == []


def test_the_settle_loops_repeat_asks_are_served_the_remembered_empty(world):
    redis, runs, answers = world
    db = _FakeDb()
    answers["live"] = {"changes": [], "style_changes": []}
    for _ in range(3):
        block = bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
        assert block["changes"] == []
    assert runs == ["live"]            # computed once, not three times
    assert db.stored is None           # an empty lane is still not stored
    assert bake.bake_in_flight(ARC, ACTOR, SNAPSHOT) is False  # lock released
    # A different snapshot is a different document: computed afresh.
    bake.changes_block_for(db, ARC, ACTOR, "snap-2", CORE)
    assert runs == ["live", "live"]
    # An answer forgets the remembered block; the next ask computes again.
    bake.request_rebake_after_answer(ARC, ACTOR)
    bake.changes_block_for(db, ARC, ACTOR, "snap-2", CORE)
    assert runs == ["live", "live", "live"]


def test_an_empty_computed_before_the_take_is_ready_is_not_remembered(world):
    _redis, runs, answers = world
    db = _FakeDb(analysis_state="processing")
    answers["live"] = {"changes": []}
    bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    bake.changes_block_for(db, ARC, ACTOR, SNAPSHOT, CORE)
    assert runs == ["live", "live"]
