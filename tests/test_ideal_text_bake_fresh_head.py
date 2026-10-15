"""The bake works on the Take that was just told "ready" (founder 2026-10-15).

The head stored during processing named the PREVIOUS Take with the new
version, so the bake re-ran the old Take and every guard threw its marks
away ("feedback set not claimable ... index=2 version=3"). The bake job now
republishes a head that is behind the arc's generation before baking it.
"""
from __future__ import annotations

from services import ideal_text_feedback_bake as bake
from services import ideal_text_core_snapshot as core_snapshot

ARC, ACTOR = "arc-1", "actor-1"
STALE = {"id": "snap-old", "source_generation": 4,
         "payload": {"text": "T3", "latest_take_session_id": "take-2",
                     "version": 3}}
FRESH = {"id": "snap-new", "source_generation": 5,
         "payload": {"text": "T3", "latest_take_session_id": "take-3",
                     "version": 3}}


class _Db:
    def __init__(self, head, generation):
        self.head, self.generation, self.published = head, generation, 0

    def get_ideal_text_document_snapshot(self, arc_id, actor_id):
        return self.head

    def get_ideal_text_document_generation(self, arc_id):
        return self.generation


def _baked(monkeypatch, db):
    seen = []
    monkeypatch.setattr("services.db.db", db)
    monkeypatch.setattr(bake, "bake_for_snapshot",
                        lambda _db, arc, actor, head: seen.append(head))

    def publish(database, arc_id, actor_id=None, *, enqueue_on_failure=True):
        database.published += 1
        database.head = FRESH
    monkeypatch.setattr(core_snapshot, "publish_for_arc", publish)
    bake.run_pending_bake(ARC, ACTOR)
    return seen


def test_a_stale_head_is_republished_and_the_new_take_is_baked(monkeypatch):
    db = _Db(STALE, generation=5)
    seen = _baked(monkeypatch, db)
    assert db.published == 1
    assert [h["payload"]["latest_take_session_id"] for h in seen] == ["take-3"]


def test_a_current_head_is_baked_as_it_stands(monkeypatch):
    db = _Db(FRESH, generation=5)
    seen = _baked(monkeypatch, db)
    assert db.published == 0
    assert seen == [FRESH]
