"""
STORY    As a coach, I want to see what the machine heard only after I give
         my own answer, so that my judgement stays blind.
OUTCOME
  O1  Never-2: before this coach's own rating (or after "Audio unclear"),
      the moment read answers 409 BLIND_RATING_REQUIRED and reads nothing
      about the moment.
  O2  After the rating, the read opens and "heard" says in words what the
      machine heard - never a number.
  O4  After the rating, the read carries the moment's willfidence as a whole
      percent for the coach (founder 2026-10-21, N104); a clip with no sound
      read carries none, never a made-up middle.
  O3  For each kind, "heard" names the right thing: the error labels, the
      confident cues behind praise, the clearer version's reason, all of it
      on an ambiguity, and an explicit "nothing" when it heard nothing.
PROVES   O1 -> test_the_read_is_still_behind_the_blind_gate
         O2 -> test_after_my_rating_the_read_says_what_was_heard_in_words
         O4 -> test_the_read_carries_willfidence_as_a_percent_only_when_heard
         O3 -> test_heard_names_what_the_machine_heard_for_each_kind
WHY      D-CP-3; coach panel lock flow 5 ("What happened").
"""
from __future__ import annotations

import json
import re
import uuid
from unittest.mock import patch

from flask import Flask, request

from services.coach_moment_read import machine_heard

SESSION, SNIPPET = str(uuid.uuid4()), str(uuid.uuid4())
COACH = "coach-1"


class _Db:
    """The reads the moment route makes; `rating` is this coach's own."""

    def __init__(self, rating=None, suggestion=None, request_row=None):
        self.rating = rating
        self.suggestion = suggestion
        self.request_row = request_row
        self.reads: list = []

    class takes:  # noqa: N801 -- the attribute the route reads
        @staticmethod
        def get_read_sessions_for(_sid):
            return []

    def v2_get_session_by_id(self, _sid):
        return {"id": SESSION, "user_id": "owner-1"}

    def get_snippets_by_session(self, _sid):
        return [{"id": SNIPPET, "transcript": "We grew in every region.",
                 "slide_index": 2}]

    def get_coach_snippet_drafts(self, _sid):
        return []

    def get_own_state_ratings_for_session(self, _sid, rater):
        return {SNIPPET: self.rating} if self.rating and rater == COACH else {}

    def get_exercise_coach_request(self, *_a):
        self.reads.append("request")
        return self.request_row

    def get_moment_suggestion(self, _snip):
        self.reads.append("suggestion")
        return self.suggestion

    def list_speaking_errors(self):
        return [{"error_id": "rushing", "label": "Rushing"}]


def _read(db):
    from routes.v2 import coach as route

    app = Flask(__name__)
    with patch.object(route, "db", db):
        with app.test_request_context("/v2/x"):
            request.user_id = COACH
            response, status = route.v2_coach_moment_read.__wrapped__(
                SESSION, SNIPPET)
    return status, response.get_json()


def test_the_read_is_still_behind_the_blind_gate():
    for rating in (None, {"value": None, "unrateable": True}):
        db = _Db(rating=rating,
                 suggestion={"kind": "replace", "trigger": "stickiness"})
        status, body = _read(db)
        assert status == 409
        assert body["code"] == "BLIND_RATING_REQUIRED"
        assert "heard" not in body
        assert db.reads == []  # nothing about the moment was read


def test_after_my_rating_the_read_says_what_was_heard_in_words():
    db = _Db(rating={"value": "in_between"},
             suggestion={"kind": "replace", "trigger": "stickiness",
                         "stickiness_pct": 12})
    status, body = _read(db)
    assert status == 200
    assert body["coach_answer"] == "in_between"
    assert body["heard"] == [{"kind": "reason", "key": "weak_slide_fit_read"}]
    assert not re.search(r"\d", json.dumps(body["heard"]))


def test_heard_names_what_the_machine_heard_for_each_kind():
    db = _Db()
    error = {"answer_kind": "error", "observed_tags": ["rushing"]}
    assert machine_heard(db, error, SNIPPET) == [
        {"kind": "error", "key": "rushing", "label": "Rushing"}]

    db.suggestion = {"kind": "emphasize", "cue_keys": ["wide_range", "z=1.7"]}
    assert machine_heard(db, {"answer_kind": "praise"}, SNIPPET) == [
        {"kind": "cue", "key": "wide_range"}]

    db.suggestion = {"kind": "replace", "trigger": "unconfident"}
    assert machine_heard(db, {"answer_kind": "rewrite"}, SNIPPET) == [
        {"kind": "reason", "key": "weak_delivery_read"}]

    db.suggestion = {"kind": "delivery", "cue_keys": ["kept_moving"]}
    ambiguity = {"answer_kind": "ambiguity", "observed_tags": ["rushing"]}
    assert machine_heard(db, ambiguity, SNIPPET) == [
        {"kind": "error", "key": "rushing", "label": "Rushing"},
        {"kind": "cue", "key": "kept_moving"}]

    db.suggestion = None
    assert machine_heard(db, None, SNIPPET) == [{"kind": "nothing", "key": "nothing"}]


def test_the_read_carries_willfidence_as_a_percent_only_when_heard():
    from services.voice_confidence import _VERSION

    db = _Db(rating={"value": "yes"})
    _status, unheard = _read(db)
    assert unheard["willfidence"] is None

    class _Heard(_Db):
        def get_snippets_by_session(self, _sid):
            return [{"id": SNIPPET, "transcript": "We grew in every region.",
                     "slide_index": 2,
                     "metrics": {"voice_confidence": {"version": _VERSION, "score": 0.5}}}]

    status, body = _read(_Heard(rating={"value": "yes"}))
    assert status == 200
    assert isinstance(body["willfidence"], int) and 0 <= body["willfidence"] <= 100
