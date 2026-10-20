"""
STORY    As a speaker, I want deleting a presentation or one Take to remove
         exactly those Takes, and nobody else to be able to delete them, so
         that deleted work is gone and nothing else is (deletion).
OUTCOME
  O1  Deleting a presentation deletes every Take of that deck, and no Take
      of another deck or of a deckless talk.
  O2  Deleting Take n deletes the n-th oldest Take of that deck, only it.
  O3  Someone else asking for the same presentation or Take gets 404 and
      nothing is deleted.
  O4  A Take the database refuses to delete (its lineage still points at
      it) answers 409 and the route does not report success.
PROVES   O1 -> test_deleting_a_presentation_deletes_all_its_takes
         O2 -> test_deleting_take_n_deletes_the_nth_oldest_take
         O3 -> test_someone_else_cannot_delete_my_presentation_or_take
         O4 -> test_a_take_with_lineage_is_refused_and_not_reported_deleted
WHY      FE PR #161 (hard delete, founder call). The database delete itself
         (v2_delete_sessions) is stubbed here: these cases prove which Takes
         the routes ask it to delete, for whom, not the SQL.
"""
from __future__ import annotations

import pytest
from flask import Flask, request

from routes.v2 import user_sessions as v2_user_sessions
from routes.v2.arcs import _presentation_group_key
from services.db import db
from services.take_repository import TakeHasLineageError

OWNER, STRANGER = "user-1", "user-2"
DECK_A = {"slides": [{"title": "Intro", "body": "hello"}],
          "presentation_ref": "https://x/a.pdf"}
DECK_B = {"slides": [{"title": "Other", "body": "x"}],
          "presentation_ref": "https://x/b.pdf"}
# The presentation id the frontend sends is the deck's identity key.
PID_A = _presentation_group_key(DECK_A)

# The owner's Takes, listed out of order on purpose: deck A has three
# (s1 oldest .. s3 newest), deck B one, and s5 is a deckless talk.
SESSIONS = {
    "s3": {"user_id": OWNER, "created_at": "2026-03-01T00:00:00Z", "intake_context": DECK_A},
    "s1": {"user_id": OWNER, "created_at": "2026-01-01T00:00:00Z", "intake_context": DECK_A},
    "s2": {"user_id": OWNER, "created_at": "2026-02-01T00:00:00Z", "intake_context": DECK_A},
    "s4": {"user_id": OWNER, "created_at": "2026-04-01T00:00:00Z", "intake_context": DECK_B},
    "s5": {"user_id": OWNER, "created_at": "2026-05-01T00:00:00Z", "intake_context": {"slides": []}},
}


@pytest.fixture
def deleted(monkeypatch):
    """The sessions the routes asked the database to delete, per caller."""
    calls: list = []

    def list_sessions(uid, **_kw):
        return [dict(meta, id=sid) for sid, meta in SESSIONS.items()
                if meta["user_id"] == uid]

    monkeypatch.setattr(db.takes, "v2_list_user_lab_sessions", list_sessions)
    monkeypatch.setattr(db.takes, "v2_delete_sessions",
                        lambda sids, uid: calls.append((sorted(sids), uid)))
    return calls


def _as(user_id, view, *args):
    with Flask(__name__).test_request_context():
        request.user_id = user_id
        return getattr(v2_user_sessions, view).__wrapped__(*args)


def test_deleting_a_presentation_deletes_all_its_takes(deleted):
    response, status = _as(OWNER, "v2_user_delete_presentation", PID_A)
    assert status == 200
    assert response.get_json()["deleted_sessions"] == 3
    assert deleted == [(["s1", "s2", "s3"], OWNER)]


def test_deleting_take_n_deletes_the_nth_oldest_take(deleted):
    response, status = _as(OWNER, "v2_user_delete_take", PID_A, "1")
    assert status == 200
    assert response.get_json()["deleted_session"] == "s1"
    assert deleted == [(["s1"], OWNER)]

    _response, status = _as(OWNER, "v2_user_delete_take", PID_A, "4")
    assert status == 404
    assert deleted == [(["s1"], OWNER)]


def test_someone_else_cannot_delete_my_presentation_or_take(deleted):
    _response, status = _as(STRANGER, "v2_user_delete_presentation", PID_A)
    assert status == 404
    _response, status = _as(STRANGER, "v2_user_delete_take", PID_A, "1")
    assert status == 404
    assert deleted == []


def test_a_take_with_lineage_is_refused_and_not_reported_deleted(deleted, monkeypatch):
    def refuse(sids, _uid):
        raise TakeHasLineageError(list(sids))

    monkeypatch.setattr(db.takes, "v2_delete_sessions", refuse)
    response, status = _as(OWNER, "v2_user_delete_take", PID_A, "1")
    assert status == 409
    assert response.get_json()["code"] == "TAKE_HAS_LINEAGE"
