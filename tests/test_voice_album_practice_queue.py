"""
STORY    As a speaker, I want a "practise new" queue of my starred clips I
         have not answered, shown without scores, so that I practise the
         right moments.
OUTCOME
  O1  Every starred clip I have not answered is in the queue, in Take and
      Slide order, with its playback; a clip without a star is not.
  O2  A clip I answered leaves the queue, whatever the answer and wherever
      I gave it (in a Take review or in this queue).
  O3  NEVER-1: the queue carries no score and no machine read.
PROVES   O1 -> test_unanswered_starred_clips_enter_the_queue
         O2 -> test_an_answered_clip_leaves_the_queue
         O3 -> test_the_queue_carries_no_score_or_machine_read
WHY      Founder 2026-09-18, the Album's "Practice new"; AC-9.
"""
from __future__ import annotations

import json

from services.voice_album_practice_queue import (
    build_practice_queue,
    record_practice_answer,
)

ARC = "arc-1"
STAR = {"kind": "emphasize", "trigger": "confident",
        "power_score": 0.91, "machine_confidence": "high"}
SESSIONS = {ARC: [
    {"id": "sess-1", "take_index": 1, "analysis_state": "ready"},
    {"id": "sess-2", "take_index": 2, "analysis_state": "ready"},
]}
SNIPPETS = {
    "sess-1": [{"id": "s1", "slide_index": 3, "duration_ms": 6000},
               {"id": "s2", "slide_index": 1, "duration_ms": 5000},
               {"id": "s4", "slide_index": 0, "duration_ms": 5000}],
    "sess-2": [{"id": "s3", "slide_index": 2, "duration_ms": 7000}],
}


class _Db:
    """s1, s3 and s4 are starred; s2 is not. Answers land in two places."""

    def __init__(self, *, self_reports=()):
        self.stars = {"s1": STAR, "s3": STAR, "s4": STAR}
        self.self_reports = list(self_reports)
        self.routes: list[dict] = []

    def get_moment_suggestions_by_arc(self, _arc_id):
        return self.stars

    def list_confident_voice_self_reports(self, _arc_id, **_):
        return self.self_reports

    def list_owner_voice_album_routes(self, _arc_id, **_):
        return self.routes

    def get_snippets_by_session(self, session_id, **_):
        return SNIPPETS.get(session_id, [])

    def upsert_owner_voice_album_route(self, **row):
        self.routes.append(row)
        return True


def _queue(db):
    return build_practice_queue(
        sessions_by_arc=SESSIONS, titles_by_arc={ARC: "Series A"}, database=db,
        resolve_audio=lambda snippet: "https://cdn/" + str(snippet.get("id")))


def test_unanswered_starred_clips_enter_the_queue():
    queue = _queue(_Db())
    assert [row["snippet_id"] for row in queue] == ["s4", "s1", "s3"]
    first = queue[0]
    assert first["audio_url"] == "https://cdn/s4"
    assert (first["arc_title"], first["take_index"], first["slide_index"]) == (
        "Series A", 1, 0)


def test_an_answered_clip_leaves_the_queue():
    db = _Db(self_reports=[{"snippet_id": "s4", "response": "yes"}])
    assert record_practice_answer(arc_id=ARC, take_session_id="sess-1", snippet_id="s1",
                                  response="no", owner_user_id="u1",
                                  database=db) == (True, None)
    assert [row["snippet_id"] for row in _queue(db)] == ["s3"]


def test_the_queue_carries_no_score_or_machine_read():
    queue = _queue(_Db())
    assert queue
    flat = json.dumps(queue)
    for banned in ("power_score", "machine_confidence", "0.91", "high",
                   "emphasize", "confident"):
        assert banned not in flat, banned
