"""
STORY    As a speaker, I want my latest answer to each feedback item shown back
         to me, and nobody else able to read it, so that my judgements stay mine
         and current.
OUTCOME
  O1  I get one answer per item, at its latest change.
  O2  Someone else's Take, or a Take that does not exist, is "not found".
PROVES   O1 -> test_the_owner_reads_each_answer_at_its_latest
         O2 -> test_someone_elses_take_or_no_take_is_not_found
WHY      Q19 A: the answered bookmark's read.
"""
from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import patch

from flask import Flask, request

from routes.v2 import user_sessions as route
from services.db import DatabaseService

TAKE = "11111111-0000-4000-8000-000000000001"
OWNER = "22222222-0000-4000-8000-000000000002"
STRANGER = "33333333-0000-4000-8000-000000000003"


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def select(self, _columns: str) -> "_Query":
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        return _Query([r for r in self.rows if str(r.get(column)) == str(value)])

    def in_(self, column: str, values: list) -> "_Query":
        wanted = {str(v) for v in values}
        return _Query([r for r in self.rows if str(r.get(column)) in wanted])

    def order(self, column: str) -> "_Query":
        return _Query(sorted(self.rows, key=lambda r: str(r.get(column))))

    def execute(self) -> _Result:
        return _Result([dict(r) for r in self.rows])


class _Tables:
    def __init__(self, tables: dict[str, list[dict]]):
        self.tables = tables

    def table(self, name: str) -> _Query:
        return _Query(self.tables.get(name, []))


def _database() -> DatabaseService:
    service = DatabaseService.__new__(DatabaseService)
    service.client = _Tables({
        "v2_sessions": [{"id": TAKE, "user_id": OWNER}],
        "take_feedback_self_report": [
            {"id": 1, "take_session_id": TAKE, "owner_user_id": OWNER,
             "feedback_id": "cv-1", "feedback_family": "confident_voice",
             "response": "no", "created_at": "2026-10-18T10:00:00Z"},
            {"id": 2, "take_session_id": TAKE, "owner_user_id": OWNER,
             "feedback_id": "rw-1", "feedback_family": "rewrite_clarity",
             "response": "keep_wording", "created_at": "2026-10-18T10:01:00Z"},
        ],
        "take_feedback_self_report_revision": [
            {"report_id": 1, "take_session_id": TAKE, "owner_user_id": OWNER,
             "response": "in_between", "revision": 1,
             "created_at": "2026-10-18T11:00:00Z"},
            {"report_id": 1, "take_session_id": TAKE, "owner_user_id": OWNER,
             "response": "yes", "revision": 2,
             "created_at": "2026-10-18T12:00:00Z"},
        ],
    })
    return service


def _get(take: str, user: str):
    app = Flask(__name__)
    view = inspect.unwrap(route.v2_get_take_feedback_responses)
    with app.test_request_context("/x", method="GET"), \
            patch.object(route, "db", _database()):
        request.user_id = user
        result = view(take)
    resp, status = result if isinstance(result, tuple) else (result, 200)
    return resp.get_json(), status


def test_the_owner_reads_each_answer_at_its_latest():
    body, status = _get(TAKE, OWNER)
    assert status == 200
    assert {a["feedback_id"]: (a["response"], a["at"]) for a in body["answers"]} == {
        "cv-1": ("yes", "2026-10-18T12:00:00Z"),
        "rw-1": ("keep_wording", "2026-10-18T10:01:00Z"),
    }


def test_someone_elses_take_or_no_take_is_not_found():
    assert _get(TAKE, STRANGER)[1] == 404
    assert _get("44444444-0000-4000-8000-000000000004", OWNER)[1] == 404
