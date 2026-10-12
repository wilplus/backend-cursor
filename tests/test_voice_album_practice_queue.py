"""THE "PRACTICE NEW" QUEUE (founder 2026-09-18).

Every starred clip of yours you have not answered yet, one per screen. These
pins hold what may enter the queue, what must leave it, and that the five
states survive the write whole.

Run: python3 -m unittest tests.test_voice_album_practice_queue
"""
from __future__ import annotations

import unittest

from services.voice_album_practice_queue import build_practice_queue

ARC = "arc-1"


def _star(trigger="confident", kind="emphasize"):
    return {"kind": kind, "trigger": trigger}


class _Db:
    def __init__(self, *, stars=None, self_reports=None, routes=None,
                 snippets=None):
        self.stars = stars or {}
        self.self_reports = self_reports or []
        self.routes = routes or []
        self.snippets = snippets or {}

    def get_moment_suggestions_by_arc(self, arc_id):
        return self.stars

    def list_confident_voice_self_reports(self, arc_id):
        return self.self_reports

    def list_owner_voice_album_routes(self, arc_id):
        return self.routes

    def get_snippets_by_session(self, session_id):
        return self.snippets.get(session_id, [])


SESSIONS = {ARC: [
    {"id": "sess-1", "take_index": 1, "analysis_state": "ready",
     "created_at": "2026-08-01T00:00:00Z"},
    {"id": "sess-2", "take_index": 2, "analysis_state": "ready",
     "created_at": "2026-08-02T00:00:00Z"},
]}
SNIPPETS = {
    "sess-1": [{"id": "s1", "slide_index": 3, "duration_ms": 6000},
               {"id": "s2", "slide_index": 1, "duration_ms": 5000}],
    "sess-2": [{"id": "s3", "slide_index": 2, "duration_ms": 7000}],
}


def _build(db, sessions=None, titles=None):
    return build_practice_queue(
        sessions_by_arc=sessions if sessions is not None else SESSIONS,
        titles_by_arc=titles if titles is not None else {ARC: "Series A"},
        database=db,
        resolve_audio=lambda snippet: "https://cdn/" + str(snippet.get("id")),
    )


class NeverSurfacedTests(unittest.TestCase):
    def test_the_queue_carries_no_score_or_machine_read(self):
        db = _Db(stars={"s1": dict(_star(), power_score=0.91,
                                   machine_confidence="high")},
                 snippets=SNIPPETS)
        blob = str(_build(db))
        for banned in ("power_score", "machine_confidence", "0.91", "high"):
            self.assertNotIn(banned, blob)


if __name__ == "__main__":
    unittest.main()
