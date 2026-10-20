"""
STORY    As the founder, I want a product purpose to run only when its registry
         row says it is operational, so that consent decisions, not code
         switches, open features (consent, on the path that gates a feature).
OUTCOME
  O1  A phase-1, operational, authorising row runs the handler.
  O2  A missing row, a phase-2 row and `operational = false` each answer 410
      PURPOSE_NOT_OPERATIONAL, and the handler never runs.
  O3  A registry read that fails (the database raises) also answers 410;
      it does not become a 500 and does not open the door.
PROVES   O1 -> test_an_open_registry_row_runs_the_handler
         O2 -> test_a_closed_registry_row_never_enters_the_handler
         O3 -> test_an_unreadable_registry_never_enters_the_handler
WHY      routes/phase2_guard.py used to answer 410 unconditionally while
         claiming to read the registry (0335 made the answer yes).
"""
from __future__ import annotations

import flask
import pytest

from routes.phase2_guard import operational_purpose_disabled
from services import processing_purposes as pp
from services.db import db

PURPOSE = "personalized_exercise_recommendation"
OPEN_ROW = {"id": PURPOSE, "phase": "phase1", "operational": True,
            "authorizes_processing": True}


class _Registry:
    """The registry read, answering one fixed row (None = no such row)."""

    def __init__(self, row):
        self.row = row

    def get_processing_purpose(self, purpose_id):
        return self.row


@pytest.fixture(autouse=True)
def _fresh_cache():
    pp.forget_cached_purposes()
    yield
    pp.forget_cached_purposes()


def _call(monkeypatch, database=None):
    """Call a gated handler; `database` stands in for the registry read."""
    ran = []

    @operational_purpose_disabled(PURPOSE)
    def handler():
        ran.append(True)
        return "handler ran", 200

    if database is not None:
        original = pp.purpose_is_operational
        monkeypatch.setattr(pp, "purpose_is_operational", lambda purpose_id, **kw:
                            original(purpose_id, database=database))
    with flask.Flask(__name__).test_request_context("/"):
        return handler(), ran


def test_an_open_registry_row_runs_the_handler(monkeypatch):
    result, ran = _call(monkeypatch, _Registry(OPEN_ROW))
    assert ran == [True]
    assert result == ("handler ran", 200)


@pytest.mark.parametrize("row", [
    None,                                     # no such purpose
    {**OPEN_ROW, "phase": "phase2"},          # a phase-2 purpose
    {**OPEN_ROW, "operational": False},       # the emergency stop
    {**OPEN_ROW, "authorizes_processing": False},
], ids=["missing", "phase2", "not_operational", "not_authorising"])
def test_a_closed_registry_row_never_enters_the_handler(monkeypatch, row):
    result, ran = _call(monkeypatch, _Registry(row))
    assert ran == []
    body, status = result
    assert status == 410
    assert body.get_json()["code"] == "PURPOSE_NOT_OPERATIONAL"


def test_an_unreadable_registry_never_enters_the_handler(monkeypatch):
    class _Down:
        def table(self, _name):
            raise ConnectionError("registry unreachable")

    # The real registry read on the app's database, its client down.
    monkeypatch.setattr(db, "client", _Down())
    result, ran = _call(monkeypatch)
    assert ran == []
    body, status = result
    assert status == 410
    assert body.get_json()["code"] == "PURPOSE_NOT_OPERATIONAL"
