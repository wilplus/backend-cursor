"""The bookmarks are baked again after the speaker answers (F3, 2026-10-08).

Every answer writes to the mutable feedback surface, which retires the stored
block, and only the end of an analysis run used to bake again — so the first
open of the Ideal Text after a walk ran the whole Manager live. These pin the
rebake: one per document per window however many answers land in it, never
in the way of the answer that asked for it.
"""
from __future__ import annotations

from unittest.mock import patch

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


def test_a_walk_of_answers_asks_for_one_rebake_per_window(broker):
    redis, queued = broker
    results = [bake.request_rebake_after_answer("arc-1", "actor-1")
               for _ in range(8)]
    assert results == [True] + [False] * 7
    assert len(queued) == 1
    path, args, kwargs = queued[0]
    assert path == bake.BAKE_TASK_PATH
    assert args == ("arc-1", "actor-1")
    # Trailing: the one bake runs after the window, so it sees every answer.
    assert kwargs["delay_seconds"] == bake.REBAKE_DEBOUNCE_SECONDS
    assert kwargs["queue"] == "bakes"
    assert kwargs["rq_job_id"] == "ideal-text-rebake:arc-1:actor-1"


def test_another_document_has_its_own_window(broker):
    _redis, queued = broker
    assert bake.request_rebake_after_answer("arc-1", "actor-1") is True
    assert bake.request_rebake_after_answer("arc-2", "actor-1") is True
    assert len(queued) == 2


def test_an_answer_after_the_window_asks_again(broker):
    redis, queued = broker
    bake.request_rebake_after_answer("arc-1", "actor-1")
    redis.now += bake.REBAKE_DEBOUNCE_SECONDS - 1
    assert bake.request_rebake_after_answer("arc-1", "actor-1") is False
    redis.now += 2
    assert bake.request_rebake_after_answer("arc-1", "actor-1") is True
    assert len(queued) == 2


def test_a_failed_enqueue_releases_the_window(broker, monkeypatch):
    redis, _queued = broker
    monkeypatch.setattr(job_queue, "enqueue", lambda *a, **k: False)
    assert bake.request_rebake_after_answer("arc-1", "actor-1") is False
    assert redis.keys == {}


def test_nothing_is_asked_without_the_flag_a_broker_or_a_document(
        broker, monkeypatch):
    _redis, queued = broker
    assert bake.request_rebake_after_answer("", "actor-1") is False
    assert bake.request_rebake_after_answer("arc-1", None) is False
    monkeypatch.setattr(job_queue, "queue_configured", lambda: False)
    assert bake.request_rebake_after_answer("arc-1", "actor-1") is False
    monkeypatch.setattr(job_queue, "queue_configured", lambda: True)
    monkeypatch.setattr(bake, "_bake_enabled", lambda: False)
    assert bake.request_rebake_after_answer("arc-1", "actor-1") is False
    assert queued == []


def test_a_broken_broker_never_raises(broker, monkeypatch):
    def _boom(**_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(job_queue, "get_redis", _boom)
    assert bake.request_rebake_after_answer("arc-1", "actor-1") is False


def test_the_document_actor_is_the_account_else_the_guest_principal():
    assert bake.document_actor_of({"user_id": "u", "owner_principal_id": "p"}) == "u"
    assert bake.document_actor_of({"user_id": None, "owner_principal_id": "p"}) == "p"
    assert bake.document_actor_of(None) == ""


# ── the answer route ──────────────────────────────────────────────────────


def _answer_route_db():
    change = {"outcome": "replayed", "row": {"id": 7, "snippet_id": judgement.SNIP,
                                             "response": "no", "revision": 0}}
    return judgement._RouteDb("saved", change)


def test_an_answer_asks_for_a_rebake_of_its_document():
    with patch.object(bake, "request_rebake_after_answer",
                      return_value=True) as asked:
        status, body, _ = judgement._post(_answer_route_db(), response="no")
    assert status == 200 and body["saved"] is True
    asked.assert_called_once_with("arc-1", judgement.OWNER)


def test_a_failure_to_enqueue_does_not_fail_the_answer(broker, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("broker gone")

    monkeypatch.setattr(job_queue, "enqueue", _boom)
    status, body, _ = judgement._post(_answer_route_db(), response="no")
    assert status == 200 and body["saved"] is True


def test_an_open_or_skip_asks_for_a_rebake_too(monkeypatch):
    from services import moment_events

    class _Db:
        def get_snippet_by_id(self, _sid):
            return {"session_id": "take-1"}

        def v2_get_session_by_id(self, _sid):
            return {"id": "take-1", "user_id": "u-1", "arc_id": "arc-9"}

        def record_moment_event(self, **_k):
            return True

    monkeypatch.setattr(
        "services.judgement_follow_up.judgement_after_feedback_enabled",
        lambda: False)
    with patch.object(bake, "request_rebake_after_answer",
                      return_value=True) as asked:
        status, payload = moment_events.record_moment_event(
            _Db(), user_id="u-1", snippet_id="s-1", body={"event": "skipped"})
    assert status == 200 and payload["recorded"] is True
    asked.assert_called_once_with("arc-9", "u-1")


def test_the_side_lane_worker_runs_a_scheduler_for_the_delayed_bake(monkeypatch):
    """The rebake is a delayed job, and rq moves due jobs only for the queues
    its own worker serves. Without this a named bake queue never runs one."""
    import worker as worker_entry

    seen: list = []
    monkeypatch.setattr(worker_entry, "_run_worker_loop",
                        lambda _conn, *, with_scheduler: seen.append(with_scheduler))
    worker_entry._run_side_lane(object())
    assert seen == [True]


def test_a_take_asks_only_once_its_write_succeeded(broker):
    _redis, queued = broker
    take = {"arc_id": "arc-1", "user_id": None, "owner_principal_id": "guest-p"}
    assert bake.request_rebake_for_take(take, written=False) is False
    assert bake.request_rebake_for_take({"user_id": "u"}) is False
    assert bake.request_rebake_for_take(take) is True
    assert queued[0][1] == ("arc-1", "guest-p")
