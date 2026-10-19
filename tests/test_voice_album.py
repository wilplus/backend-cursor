"""
STORY    As a speaker, I want a moment in my Voice Album only when the
         machine, I and a coach all agree, and shown without scores, so that
         the album is trustworthy and number-free.
OUTCOME
  O1  A moment enters only with all three yeses (machine reads it
      confident, the speaker said yes, a coach said yes); missing any one
      keeps it out.
  O2  A refresh run again adds nothing: the moment is in the album once.
  O3  NEVER-1: the album read shows the moment's words and place, and no
      confidence, tags, metrics or score.
PROVES   O1 -> test_a_moment_enters_only_with_all_three_yeses
         O2 -> test_a_second_refresh_adds_nothing
         O3 -> test_the_album_read_shows_words_and_no_scores
WHY      Founder re-lock 2026-08-13/14: "Acoustic data indicates a great
         moment -> User agrees -> Coach agrees = This moment lands in the
         Voice Album." AC-9.
"""
from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest
from flask import Flask, request

from routes.v2 import arcs as v2_arcs
from services.voice_album import refresh_voice_album

ARC, TAKE, OWNER = "arc-1", "t1", "u1"
# The clips of one Take, and which of the three legs said yes on each.
LEGS = {
    "all-three": {"machine": True, "user": True, "coach": True},
    "no-machine": {"machine": False, "user": True, "coach": True},
    "no-user": {"machine": True, "user": False, "coach": True},
    "no-coach": {"machine": True, "user": True, "coach": False},
}


class FakeDB:
    """One project with one Take; the album table kept in memory."""

    def __init__(self):
        self.album: list[dict] = []
        self.inserts = 0
        self.takes = SimpleNamespace(get_arc_sessions=lambda _arc, **_: [
            {"id": TAKE, "user_id": OWNER, "take_index": 2, "arc_id": ARC}])

    def list_confident_voice_self_reports(self, _arc, **_):
        return [{"snippet_id": sid, "response": "yes", "slide_index": 3}
                for sid, legs in LEGS.items() if legs["user"]]

    def list_owner_voice_album_routes(self, _arc, **_):
        return []

    def get_snippets_by_session(self, _sid, **_):
        return [{"id": sid, "session_id": TAKE, "transcript": f"The words of {sid}.",
                 "storage_path": None, "audio_url": None,
                 "start_offset_ms": 1200, "duration_ms": 4000,
                 "metrics": {"voice_confidence": {"score": 0.93}}}
                for sid in LEGS]

    def get_confidence_labels_by_snippet_ids(self, ids, **_):
        return {sid: [{"lane": "coach", "state_id": "confidence",
                       "value": "yes" if LEGS[sid]["coach"] else "no",
                       "tags": ["warm"]}]
                for sid in ids}

    def list_voice_album(self, _arc):
        return list(self.album)

    def insert_voice_album_entry(self, *, arc_id, snippet_id, take_session_id, slide_index):
        self.inserts += 1
        if any(e["snippet_id"] == snippet_id for e in self.album):
            return False
        self.album.append({"snippet_id": snippet_id, "take_session_id": take_session_id,
                           "slide_index": slide_index,
                           "entered_at": "2026-08-14T10:00:00Z"})
        return True

    def delete_voice_album_entry(self, *, arc_id, snippet_id):
        before = len(self.album)
        self.album = [e for e in self.album if e["snippet_id"] != snippet_id]
        return len(self.album) < before


@pytest.fixture
def fake(monkeypatch):
    # The machine leg is the clip's own read (founder 2026-10-05, Q5; N45),
    # its own service: here it answers from LEGS.
    monkeypatch.setattr(
        "services.judgement_follow_up.clip_machine_read",
        lambda _db, _take, sid: "confident" if LEGS[sid]["machine"] else "weak")
    database = FakeDB()
    monkeypatch.setattr(v2_arcs, "db", database)
    return database


def test_a_moment_enters_only_with_all_three_yeses(fake):
    assert refresh_voice_album(ARC, database=fake) == 1
    assert [e["snippet_id"] for e in fake.album] == ["all-three"]


def test_a_second_refresh_adds_nothing(fake):
    refresh_voice_album(ARC, database=fake)
    assert refresh_voice_album(ARC, database=fake) == 0
    assert [e["snippet_id"] for e in fake.album] == ["all-three"]
    assert fake.inserts == 1


def test_the_album_read_shows_words_and_no_scores(fake):
    refresh_voice_album(ARC, database=fake)
    with Flask(__name__).test_request_context():
        request.user_id = OWNER
        resp, status = inspect.unwrap(v2_arcs.v2_explore_arc_voice_album)(ARC)
    body = resp.get_json()
    assert status == 200
    [entry] = body["entries"]
    assert entry["snippet_id"] == "all-three"
    assert entry["text"] == "The words of all-three."
    assert entry["slide_index"] == 3 and entry["take_index"] == 2
    flat = json.dumps(body)
    for banned in ("confidence", "0.93", "tag", "warm", "metrics", "score"):
        assert banned not in flat, banned
