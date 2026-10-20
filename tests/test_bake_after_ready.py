"""
STORY    As a speaker, I want my feedback marks ready the moment my Take is,
         so that the walk opens as soon as the processing bubble ends and I
         never sit on typing dots (founder 2026-10-20, flow page A2; WIL-76).
OUTCOME
  O1  When the run itself has just flipped my Take ready, the marks are
      baked there and then, over the head as it stands, and nothing is
      queued for later.
  O2  When the run did not flip ready (the dispatcher writes it after the
      return) the bake is queued as before: the head is not final yet.
  O3  A bake that cannot run in the run (no document yet, or a failure) is
      queued, so the queue still has its try.
PROVES   O1 -> test_a_flipped_take_is_baked_in_the_run_and_not_queued
         O2 -> test_an_unflipped_take_is_queued_as_before
         O3 -> test_a_bake_that_cannot_run_now_is_queued
WHY      Founder 2026-10-20: "It doesn't open right after the processing";
         the queued bake landed after the page had stopped asking.
"""
from __future__ import annotations

from services import ideal_text_feedback_bake as bake

ARC, ACTOR = "arc-1", "actor-1"
HEAD = {"id": "snap-1", "payload": {"text": "Hello.",
                                    "latest_take_session_id": "take-1",
                                    "version": 1}}


def _world(monkeypatch, *, head=HEAD, bake_raises=False):
    baked: list = []
    queued: list = []
    monkeypatch.setattr(bake, "_bake_enabled", lambda: True)
    monkeypatch.setattr("services.db.db", object())
    monkeypatch.setattr(bake, "_current_head", lambda _db, arc, actor: head)

    def _bake(_db, arc, actor, published):
        if bake_raises:
            raise RuntimeError("manager down")
        baked.append(published)
        return True
    monkeypatch.setattr(bake, "bake_for_snapshot", _bake)
    monkeypatch.setattr(bake, "enqueue_bake",
                        lambda arc, actor, kind: queued.append(kind) or True)
    return baked, queued


def test_a_flipped_take_is_baked_in_the_run_and_not_queued(monkeypatch):
    baked, queued = _world(monkeypatch)
    assert bake.bake_after_ready(ARC, ACTOR, "spoken", flipped=True) is True
    assert baked == [HEAD]
    assert queued == []


def test_an_unflipped_take_is_queued_as_before(monkeypatch):
    baked, queued = _world(monkeypatch)
    assert bake.bake_after_ready(ARC, ACTOR, "spoken", flipped=False) is True
    assert baked == []
    assert queued == ["spoken"]


def test_a_bake_that_cannot_run_now_is_queued(monkeypatch):
    baked, queued = _world(monkeypatch, head=None)
    bake.bake_after_ready(ARC, ACTOR, "spoken", flipped=True)
    assert baked == [] and queued == ["spoken"]
    baked, queued = _world(monkeypatch, bake_raises=True)
    bake.bake_after_ready(ARC, ACTOR, "spoken", flipped=True)
    assert baked == [] and queued == ["spoken"]
