"""A generation whose publication keeps failing rests instead of being
re-enqueued every minute (production, 2026-10-03: two arcs with no project
owner failed LINEAGE_REQUIRED once a minute, each with a traceback, from the
moment the worker booted)."""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from services import ideal_text_core_snapshot as core
from services import job_queue


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}
        self.ttl: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds

    def get(self, key: str):
        value = self.store.get(key)
        return None if value is None else str(value).encode()


class PendingDatabase:
    def __init__(self, rows):
        self.rows = rows

    def list_pending_ideal_text_document_publications(self, _limit):
        return self.rows


@pytest.fixture
def redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(job_queue, "get_redis", lambda **_k: fake)
    return fake


def _failing_delivery(monkeypatch):
    database = Mock()
    database.get_ideal_text_document_generation.return_value = 7
    monkeypatch.setattr("services.db.db", database, raising=False)
    monkeypatch.setattr(core, "publish_for_arc", lambda *_a, **_k: None)


def test_three_failed_deliveries_put_the_generation_to_rest(
        monkeypatch, redis):
    _failing_delivery(monkeypatch)
    queued = []
    monkeypatch.setattr(core, "enqueue_pending_publication",
                        lambda arc, gen: queued.append((arc, gen)) or True)
    rows = [{"arc_id": "arc-a", "generation": 7}]

    for _attempt in range(core.PUBLICATION_FAILURES_BEFORE_REST):
        assert core.sweep_pending_publications(PendingDatabase(rows)) == 1
        with pytest.raises(RuntimeError, match="PUBLICATION_RETRY_REQUIRED"):
            core.run_pending_publication("arc-a", 7)

    assert len(queued) == core.PUBLICATION_FAILURES_BEFORE_REST
    # The fourth sweep leaves it alone.
    assert core.sweep_pending_publications(PendingDatabase(rows)) == 0
    assert len(queued) == core.PUBLICATION_FAILURES_BEFORE_REST
    key = core._publication_failure_key("arc-a", 7)  # noqa: SLF001
    assert redis.ttl[key] == core.PUBLICATION_FAILURE_WINDOW_SECONDS


def test_a_new_generation_is_tried_again(monkeypatch, redis):
    key = core._publication_failure_key("arc-a", 7)  # noqa: SLF001
    redis.store[key] = core.PUBLICATION_FAILURES_BEFORE_REST
    queued = []
    monkeypatch.setattr(core, "enqueue_pending_publication",
                        lambda arc, gen: queued.append((arc, gen)) or True)
    rows = [{"arc_id": "arc-a", "generation": 7},
            {"arc_id": "arc-a", "generation": 8},
            {"arc_id": "arc-b", "generation": 1}]

    assert core.sweep_pending_publications(PendingDatabase(rows)) == 2
    assert queued == [("arc-a", 8), ("arc-b", 1)]


def test_a_superseded_delivery_does_not_count_as_a_failure(
        monkeypatch, redis):
    database = Mock()
    database.get_ideal_text_document_generation.return_value = 8
    monkeypatch.setattr("services.db.db", database, raising=False)
    monkeypatch.setattr(core, "publish_for_arc",
                        lambda *_a, **_k: pytest.fail("must not publish"))

    core.run_pending_publication("arc-a", 7)

    assert redis.store == {}


def test_an_unreadable_broker_keeps_retrying(monkeypatch):
    class BrokenRedis:
        def get(self, _key):
            raise ConnectionError("broker away")

    monkeypatch.setattr(job_queue, "get_redis", lambda **_k: BrokenRedis())
    queued = []
    monkeypatch.setattr(core, "enqueue_pending_publication",
                        lambda arc, gen: queued.append((arc, gen)) or True)
    rows = [{"arc_id": "arc-a", "generation": 7}]

    assert core.sweep_pending_publications(PendingDatabase(rows)) == 1
    assert queued == [("arc-a", 7)]


def test_no_broker_means_no_count_and_no_rest(monkeypatch):
    monkeypatch.setattr(job_queue, "get_redis", lambda **_k: None)
    _failing_delivery(monkeypatch)
    with pytest.raises(RuntimeError):
        core.run_pending_publication("arc-a", 7)
    assert core._publication_resting("arc-a", 7) is False  # noqa: SLF001
