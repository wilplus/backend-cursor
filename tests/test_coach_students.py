"""
STORY    As a speaker, I want my coach to see me only by pseudonym, so that
         my identity stays private.
OUTCOME
  O1  The coach's roster shows each speaker by pseudonym and domain; no
      name or email reaches it, even when the profile holds them.
  O2  The roster also carries no user_id. NOT TRUE TODAY: it sends the
      user_id as the drill key (routes/v2/coach.py, "user_id": str(uid)),
      though the route's own docstring says "NEVER user_id"; pinned as a
      known gap that turns red once fixed.
  O3  The Students screens' walk-take read stays off: 404 for a valid id,
      400 for a bad one.
PROVES   O1 -> test_the_roster_shows_a_pseudonym_and_no_name_or_email
         O2 -> test_the_roster_carries_no_user_id
         O3 -> test_the_walk_take_read_stays_off
WHY      Founder 2026-10-01 (Phase 0b), N48.5 Q26 A. The profile drill-down
         (GET /v2/coach/students/<id>) is pinned whole in
         test_coach_route_contracts.py (StudentDetailContract).
"""
from __future__ import annotations

import inspect
import json
from unittest.mock import patch

import pytest
from flask import Flask, request

from routes.v2 import coach as v2_coach
from services.db import db

UID = "11111111-1111-4111-8111-111111111111"
PROFILE = {"domain": "sales", "name": "Jane Speaker", "full_name": "Jane Speaker",
           "email": "jane@example.com"}


def _call(route, *args):
    with Flask(__name__).test_request_context():
        request.user_id = "coach-1"
        resp, status = inspect.unwrap(route)(*args)
        return status, resp.get_json()


def _roster():
    with patch.object(db.takes, "list_coach_students",
                      return_value=[{"user_id": UID, "last_active": "x", "session_count": 1,
                                     "email": PROFILE["email"]}]), \
            patch.object(db, "get_user_profiles", return_value={UID: PROFILE}):
        return _call(v2_coach.v2_coach_students)


def test_the_roster_shows_a_pseudonym_and_no_name_or_email():
    status, body = _roster()
    assert status == 200
    [row] = body
    assert row["pseudonym"] == v2_coach._coach_pseudonym(UID)
    assert row["domain"] == "sales"
    text = json.dumps(body)
    assert "Jane" not in text and "jane@example.com" not in text


@pytest.mark.xfail(strict=True, reason="KNOWN GAP: the coach roster sends the speaker's "
                   "user_id as its drill key (routes/v2/coach.py v2_coach_students)")
def test_the_roster_carries_no_user_id():
    _status, body = _roster()
    assert UID not in json.dumps(body)


def test_the_walk_take_read_stays_off():
    status, body = _call(v2_coach.v2_coach_walk_take, UID)
    assert (status, body["code"]) == (404, "NOT_FOUND")
    status, body = _call(v2_coach.v2_coach_walk_take, "not-a-uuid")
    assert (status, body["code"]) == (400, "INVALID_INPUT")
