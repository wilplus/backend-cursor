"""
STORY    As a speaker, I want my Take to reach a coach even when many newer
         Takes were already answered, so that no moment I meet is lost.
OUTCOME
  O1  With more than 100 newer published Takes, an older waiting Take is
      still in the review queue.
  O2  The reach alarm hears that Take (it is in the rows it counts).
PROVES   O1, O2 -> test_older_waiting_take_survives_newer_published_ones
WHY      Founder promise: every moment a speaker meets reaches a coach. The
         limit of 100 was applied before published rows were dropped, so
         published rows took slots.
"""
from __future__ import annotations

from types import SimpleNamespace

from services.db import DatabaseService


class _Query:
    """Just enough of the PostgREST builder: eq, is_ null, order, limit."""

    def __init__(self, rows):
        self.rows, self._limit = list(rows), None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def is_(self, col, _null):
        self.rows = [r for r in self.rows if r.get(col) is None]
        return self

    def order(self, col, desc=False):
        self.rows.sort(key=lambda r: r[col], reverse=desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        return SimpleNamespace(data=self.rows[:self._limit])


def _row(i, published):
    return {"id": f"t{i:04d}", "user_id": "u", "intake_context": {},
            "status": "pending_admin_review", "source": "audit_upload",
            "review_requested_at": f"2026-11-{1 + i // 1000:02d}T{(i % 1000) // 60:02d}:{i % 60:02d}:00+00:00",
            "created_at": "2026-11-01T00:00:00+00:00", "recording_id": None,
            "recording_kind": None, "paired_session_id": None,
            "arc_id": None, "take_index": 1,
            "results_published_at": "2026-11-10T00:00:00+00:00" if published else None}


def test_older_waiting_take_survives_newer_published_ones():
    waiting = _row(0, published=False)
    rows = [waiting] + [_row(i, published=True) for i in range(1, 131)]
    service = DatabaseService.__new__(DatabaseService)
    service.client = SimpleNamespace(table=lambda _n: _Query(rows))
    queue = service.list_review_queue()
    assert [r["id"] for r in queue] == [waiting["id"]]
