"""
STORY    As a speaker, I want deleting a Take to either really delete it or
         tell me it cannot, so that the app never claims a delete that did not
         happen. (Critical path: deletion.)
OUTCOME
  O1  Deleting my own Take answers 200 and the row is gone.
  O2  A Take the database refuses to delete (its lineage still points at it)
      answers 409 TAKE_HAS_LINEAGE, and the row is left exactly as it was,
      its recording and report links included.
  O3  A presentation's Takes delete all together or not at all: one refused
      Take means 409 and every Take of it is still there.
  O4  A delete the database did not apply is never answered as a success.
  O5  Only my own Takes can be deleted: a stranger gets 404 and the delete
      statement itself is scoped to the owner.
  O6  The hourly cleanup skips a Take with lineage without counting it as
      deleted or paging anyone.
PROVES   O1 -> test_the_owner_deletes_a_take
         O2 -> test_a_take_with_lineage_answers_409_and_is_unchanged
         O3 -> test_a_presentation_deletes_all_or_none
         O4 -> test_a_delete_that_did_not_happen_is_not_a_success
         O5 -> test_a_stranger_cannot_delete_my_take
         O6 -> test_cleanup_keeps_a_take_with_lineage_quietly
WHY      2026-09-25: links were nulled before a refused DELETE and the route
         answered 200 (the same defect reverted the project delete, #647).

Covers the Python routes and repository only, against a table double that
refuses a DELETE the way PostgreSQL does (one statement, all or nothing); the
database's own RESTRICT keys are not exercised here.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from flask import Flask, request

from routes.v2 import user_sessions as routes
from services.db import db
from services.take_repository import TakeRepository

T1 = "11111111-1111-4111-8111-111111111111"
T2 = "22222222-2222-4222-8222-222222222222"
DECK = {"slides": [{"title": "Q3 results"}], "topic": "Q3"}


class _FkViolation(Exception):
    """Shaped like postgrest's APIError for SQLSTATE 23503."""

    code = "23503"


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, table, op, payload=None):
        self.table, self.op, self.payload, self.filters = table, op, payload, []

    def eq(self, col, val):
        self.filters.append((col, [val]))
        return self

    def in_(self, col, vals):
        self.filters.append((col, list(vals)))
        return self

    def execute(self):
        return self.table.run(self)


class _V2Sessions:
    """v2_sessions as PostgreSQL treats a DELETE: one statement is all or
    nothing, and a row with a RESTRICT dependent refuses the whole statement
    without changing anything."""

    def __init__(self, rows, restricted=(), ignore_delete=False):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.restricted = set(restricted)
        self.ignore_delete = ignore_delete
        self.writes = []

    # supabase client surface
    def table(self, name):
        assert name == "v2_sessions", name
        return self

    def select(self, _cols="*"):
        return _Query(self, "select")

    def update(self, payload):
        return _Query(self, "update", payload)

    def delete(self):
        return _Query(self, "delete")

    def run(self, q):
        hits = [r for r in self.rows.values()
                if all(str(r.get(c)) in [str(v) for v in vals]
                       for c, vals in q.filters)]
        if q.op == "select":
            return _Result([dict(r) for r in hits])
        self.writes.append((q.op, q.filters))
        if q.op == "update":
            for r in hits:
                r.update(q.payload)
            return _Result([dict(r) for r in hits])
        if any(r["id"] in self.restricted for r in hits):
            raise _FkViolation("update or delete on table \"v2_sessions\" "
                               "violates foreign key constraint")
        if self.ignore_delete:
            return _Result([])
        for r in hits:
            del self.rows[r["id"]]
        return _Result([dict(r) for r in hits])


class _Db:
    def __init__(self, client):
        self.client = client


def _row(sid, user="u1", created="2026-09-01"):
    return {"id": sid, "user_id": user, "recording_1_id": f"rec-{sid}",
            "report_id": f"rep-{sid}", "created_at": created,
            "intake_context": DECK}


class DeleteRouteTests(unittest.TestCase):

    def _world(self, rows, **kw):
        self.table = _V2Sessions(rows, **kw)
        repo = TakeRepository(_Db(self.table))
        for p in (
            patch.object(db.takes, "v2_delete_sessions", repo.v2_delete_sessions),
            patch.object(db, "v2_get_session_by_id",
                         lambda sid: self.table.rows.get(sid)),
            patch.object(db.takes, "v2_list_user_lab_sessions",
                         lambda uid: [r for r in self.table.rows.values()
                                      if r["user_id"] == uid]),
            patch("routes.v2.user_sessions.sentry_sdk.capture_exception"),
        ):
            p.start()
            self.addCleanup(p.stop)

    def _call(self, view, *args, user="u1"):
        with Flask(__name__).test_request_context():
            request.user_id = user
            resp, status = view.__wrapped__(*args)
            return resp.get_json(), status

    def _delete_take(self, sid=T1, user="u1"):
        return self._call(routes.v2_user_delete_session, sid, user=user)

    def test_the_owner_deletes_a_take(self):
        self._world([_row(T1)])
        body, status = self._delete_take()
        self.assertEqual((status, body["deleted_session"]), (200, T1))
        self.assertNotIn(T1, self.table.rows)

    def test_a_take_with_lineage_answers_409_and_is_unchanged(self):
        self._world([_row(T1)], restricted={T1})
        body, status = self._delete_take()
        self.assertEqual((status, body["code"]), (409, "TAKE_HAS_LINEAGE"))
        self.assertEqual(self.table.rows[T1], _row(T1))
        # The DELETE runs first and alone: no link is cut before it.
        self.assertEqual([op for op, _ in self.table.writes], ["delete"])

    def test_a_presentation_deletes_all_or_none(self):
        self._world([_row(T1, created="2026-09-01"),
                     _row(T2, created="2026-09-02")], restricted={T2})
        pid = routes._presentation_group_key(DECK)
        body, status = self._call(routes.v2_user_delete_presentation, pid)
        self.assertEqual((status, body["code"]), (409, "TAKE_HAS_LINEAGE"))
        self.assertEqual(self.table.rows, {T1: _row(T1, created="2026-09-01"),
                                           T2: _row(T2, created="2026-09-02")})

        self.table.restricted.clear()
        body, status = self._call(routes.v2_user_delete_presentation, pid)
        self.assertEqual((status, body["deleted_sessions"]), (200, 2))
        self.assertEqual(self.table.rows, {})

    def test_a_delete_that_did_not_happen_is_not_a_success(self):
        self._world([_row(T1)], ignore_delete=True)
        body, status = self._delete_take()
        self.assertEqual(status, 500)
        self.assertNotEqual(body.get("status"), "ok")
        self.assertIn(T1, self.table.rows)

    def test_a_stranger_cannot_delete_my_take(self):
        self._world([_row(T1, user="owner")])
        body, status = self._delete_take(user="stranger")
        self.assertEqual((status, body["code"]), (404, "SESSION_NOT_FOUND"))
        self.assertEqual(self.table.rows[T1], _row(T1, user="owner"))
        # Even past the route's ownership check, the statement is owner-scoped.
        db.takes.v2_delete_sessions([T1], "stranger")
        self.assertIn(T1, self.table.rows)


class CleanupTests(unittest.TestCase):

    def test_cleanup_keeps_a_take_with_lineage_quietly(self):
        table = _V2Sessions([_row("a"), _row("b")], restricted={"b"})
        repo = TakeRepository(_Db(table))
        with patch.object(db.takes, "v2_get_incomplete_sessions_older_than",
                          lambda h: [{"id": "a", "user_id": "u1"},
                                     {"id": "b", "user_id": "u1"}]), \
             patch.object(db.takes, "v2_delete_session", repo.v2_delete_session), \
             patch("services.db.sentry_sdk.capture_exception") as capture:
            n, ids = db.v2_cleanup_incomplete_sessions(hours=1)
        self.assertEqual((n, ids), (1, ["a"]))
        self.assertEqual(table.rows, {"b": _row("b")})
        capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
