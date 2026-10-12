"""The bookmarks are baked again after the speaker answers (F3, 2026-10-08).

Every answer writes to the mutable feedback surface, which retires the stored
block, and only the end of an analysis run used to bake again — so the first
open of the Ideal Text after a walk ran the whole Manager live. These pin the
rebake: one per document per window however many answers land in it, never
in the way of the answer that asked for it.
"""
from __future__ import annotations

import pytest

from services import ideal_text_feedback_bake as bake
from services import job_queue
from tests import test_a_speaker_may_change_a_judgement as judgement


class _FakeRedis:
    """SET NX EX with a clock the test moves."""

    def __init__(self):
        self.now = 0.0
        self.keys: dict[str, float] = {}

    def set(self, key, _value, nx=False, ex=None):
        expires = self.keys.get(key)
        if nx and expires is not None and expires > self.now:
            return None
        self.keys[key] = self.now + (ex or 0)
        return True

    def delete(self, key):
        self.keys.pop(key, None)
        return 1


@pytest.fixture
def broker(monkeypatch):
    redis = _FakeRedis()
    queued: list[tuple] = []
    monkeypatch.setattr(bake, "_bake_enabled", lambda: True)
    monkeypatch.setattr(job_queue, "queue_configured", lambda: True)
    monkeypatch.setattr(job_queue, "get_redis", lambda **_k: redis)
    monkeypatch.setattr(job_queue, "bake_queue_name", lambda: "bakes")

    def _enqueue(path, *args, **kwargs):
        queued.append((path, args, kwargs))
        return True

    monkeypatch.setattr(job_queue, "enqueue", _enqueue)
    return redis, queued


# ── the answer route ──────────────────────────────────────────────────────


def _answer_route_db():
    change = {"outcome": "replayed", "row": {"id": 7, "snippet_id": judgement.SNIP,
                                             "response": "no", "revision": 0}}
    return judgement._RouteDb("saved", change)


def test_a_failure_to_enqueue_does_not_fail_the_answer(broker, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("broker gone")

    monkeypatch.setattr(job_queue, "enqueue", _boom)
    status, body, _ = judgement._post(_answer_route_db(), response="no")
    assert status == 200 and body["saved"] is True
