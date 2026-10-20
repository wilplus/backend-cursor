"""
STORY    As a speaker, I want my Ideal Text ready quickly after I answer
         feedback, and my answer never blocked by that refresh, so that the
         next open is fast and answering always works.
OUTCOME
  O1  However many answers land in one window, the document is rebaked once;
      an answer after the window closes asks for the next rebake.
  O2  Never-3: a broken queue never fails the answer - it is still saved.
PROVES   O1 -> test_answers_in_one_window_rebake_the_document_once
         O2 -> test_a_failure_to_enqueue_does_not_fail_the_answer
WHY      F3 2026-10-08: the first open after a walk ran the whole Manager live.
"""
from __future__ import annotations

import pytest

from services import ideal_text_feedback_bake as bake
from services import job_queue
from tests import judgement_route_fakes as judgement


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


def _answer_route_db():
    change = {"outcome": "replayed", "row": {"id": 7, "snippet_id": judgement.SNIP,
                                             "response": "no", "revision": 0}}
    return judgement._RouteDb("saved", change)


def _rebakes(queued):
    return [q for q in queued if q[0] == bake.BAKE_TASK_PATH]


def test_answers_in_one_window_rebake_the_document_once(broker):
    redis, queued = broker
    for response in ("no", "yes", "no"):
        status, body, _ = judgement._post(_answer_route_db(), response=response)
        assert status == 200 and body["saved"] is True
    assert len(_rebakes(queued)) == 1
    _path, args, kwargs = _rebakes(queued)[0]
    assert args == ("arc-1", judgement.OWNER)
    assert kwargs["delay_seconds"] == bake.REBAKE_DEBOUNCE_SECONDS

    redis.now += bake.REBAKE_DEBOUNCE_SECONDS + 1
    judgement._post(_answer_route_db(), response="yes")
    assert len(_rebakes(queued)) == 2


def test_a_failure_to_enqueue_does_not_fail_the_answer(broker, monkeypatch):
    attempts = []

    def _boom(*_a, **_k):
        attempts.append(1)
        raise RuntimeError("broker gone")

    monkeypatch.setattr(job_queue, "enqueue", _boom)
    status, body, _ = judgement._post(_answer_route_db(), response="no")
    assert attempts, "the answer must have asked for a rebake"
    assert status == 200 and body["saved"] is True
