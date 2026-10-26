"""
STORY    As a developer on call, I want an Ideal Text whose publication keeps
         failing to stop being retried every minute, so that the logs and the
         job queue stay usable.
OUTCOME
  O1  After three failed publications the sweep leaves that version alone for
      the failure window instead of queueing it again.
  O2  Resting versions never use up the sweep: a newer interrupted
      publication behind them is still queued.
PROVES   O1 -> test_three_failed_deliveries_put_the_generation_to_rest
         O2 -> test_resting_generations_do_not_starve_a_newer_one
WHY      Production 2026-10-03: two documents failed LINEAGE_REQUIRED every minute.
         Production 2026-10-26: 103 resting versions filled the 100-row sweep.
"""
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

    def list_pending_ideal_text_document_publications(self, limit):
        return self.rows[:limit]


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


def test_resting_generations_do_not_starve_a_newer_one(monkeypatch, redis):
    queued = []
    monkeypatch.setattr(core, "enqueue_pending_publication",
                        lambda arc, gen: queued.append((arc, gen)) or True)
    rows = [{"arc_id": f"stuck-{i}", "generation": 1} for i in range(3)]
    for row in rows:
        redis.store[core._publication_failure_key(  # noqa: SLF001
            row["arc_id"], 1)] = core.PUBLICATION_FAILURES_BEFORE_REST
    rows.append({"arc_id": "fresh", "generation": 1})

    assert core.sweep_pending_publications(PendingDatabase(rows), limit=2) == 1
    assert queued == [("fresh", 1)]
