"""Take deletes never claim a delete that did not happen (2026-09-25).

The bug: ``v2_delete_session`` committed an UPDATE nulling
``v2_sessions.recording_1_id`` / ``report_id``, then DELETEd the row. A
canonical Take is referenced ON DELETE RESTRICT (recording attempts, feedback
candidates, Ideal Text core snapshots, Confident Moment bundles, Voice Album —
manifest 0296/0297/0315/0327), so the DELETE was refused *after* the links
were cut. The route helper swallowed the refusal and answered 200. The same
defect got the project delete reverted (#647 → #649).

Now: the DELETE runs first and alone — PostgreSQL refuses it without changing
anything — the refusal is ``TakeHasLineageError``, and every user delete route
answers 409 ``TAKE_HAS_LINEAGE``. A presentation's takes go in ONE statement,
so they all delete or none do. Success is what the table says afterwards.

The repository classes need no Flask; the route classes skip locally without
it and run in CI (the known gotcha).

Run: python3 -m unittest tests.test_take_delete_lineage
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.take_repository import (
    TakeDeleteNotApplied,
    TakeHasLineageError,
    TakeRepository,
)

try:
    from flask import Flask, request
    from routes.v2 import arcs as v2_arcs
    from routes.v2 import user_sessions as v2_user_sessions
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


_SID = "11111111-1111-4111-8111-111111111111"
DECK = [{"title": "Pitch", "body": "the ask"}]


class _FkViolation(Exception):
    """Shaped like postgrest's APIError for SQLSTATE 23503."""

    code = "23503"

    def __init__(self):
        super().__init__(
            'update or delete on table "v2_sessions" violates foreign key '
            'constraint "recording_attempts_take_id_fkey" on table '
            '"recording_attempts"')


class _Result:
    def __init__(self, data):
        self.data = data


class _Query:
    def __init__(self, client, table, op, payload=None):
        self.client, self.table, self.op, self.payload = client, table, op, payload
        self.filters = []

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def in_(self, col, vals):
        self.filters.append(("in", col, list(vals)))
        return self

    def execute(self):
        self.client.calls.append((self.table, self.op, self.payload, self.filters))
        return self.client.respond(self)


class _Table:
    def __init__(self, client, name):
        self.client, self.name = client, name

    def select(self, cols="*"):
        return _Query(self.client, self.name, "select", cols)

    def update(self, data):
        return _Query(self.client, self.name, "update", data)

    def delete(self):
        return _Query(self.client, self.name, "delete")


class _FakeV2Sessions:
    """A v2_sessions table that behaves like PostgreSQL does for a DELETE:
    one statement is all-or-nothing, and a row with a RESTRICT dependent
    refuses the whole statement without changing anything."""

    def __init__(self, rows, restricted=(), silently_ignore_delete=False):
        self.rows = {r["id"]: dict(r) for r in rows}
        self.restricted = set(restricted)
        self.silently_ignore_delete = silently_ignore_delete
        self.calls = []

    def table(self, name):
        return _Table(self, name)

    def _match(self, q):
        out = []
        for row in self.rows.values():
            ok = True
            for kind, col, val in q.filters:
                if kind == "eq" and str(row.get(col)) != str(val):
                    ok = False
                if kind == "in" and str(row.get(col)) not in [str(v) for v in val]:
                    ok = False
            if ok:
                out.append(row)
        return out

    def respond(self, q):
        assert q.table == "v2_sessions", q.table
        hits = self._match(q)
        if q.op == "select":
            return _Result([dict(r) for r in hits])
        if q.op == "update":
            for r in hits:
                r.update(q.payload)
            return _Result([dict(r) for r in hits])
        if q.op == "delete":
            if any(r["id"] in self.restricted for r in hits):
                raise _FkViolation()
            if self.silently_ignore_delete:
                return _Result([])
            for r in hits:
                del self.rows[r["id"]]
            return _Result([dict(r) for r in hits])
        raise AssertionError(q.op)


class _Db:
    def __init__(self, client):
        self.client = client


def _row(sid, user="u1"):
    return {"id": sid, "user_id": user, "recording_1_id": f"rec-{sid}",
            "report_id": f"rep-{sid}"}


class RepositoryDeleteTests(unittest.TestCase):

    def _repo(self, client):
        return TakeRepository(_Db(client))

    def test_canonical_take_is_refused_and_left_exactly_as_it_was(self):
        client = _FakeV2Sessions([_row("t1")], restricted={"t1"})
        with self.assertRaises(TakeHasLineageError) as ctx:
            self._repo(client).v2_delete_session("t1", "u1")
        self.assertEqual(ctx.exception.session_ids, ["t1"])
        # THE BUG: links were nulled in a separate commit before the refusal.
        self.assertEqual(client.rows["t1"], _row("t1"))
        self.assertEqual([c for c in client.calls if c[1] == "update"], [])

    def test_no_links_are_cleared_before_the_delete_even_when_it_succeeds(self):
        client = _FakeV2Sessions([_row("t1")])
        self.assertTrue(self._repo(client).v2_delete_session("t1", "u1"))
        self.assertNotIn("t1", client.rows)
        self.assertEqual([c[1] for c in client.calls], ["delete", "select"])

    def test_one_statement_for_many_takes_is_all_or_nothing(self):
        client = _FakeV2Sessions(
            [_row("t1"), _row("t2"), _row("t3")], restricted={"t2"})
        with self.assertRaises(TakeHasLineageError):
            self._repo(client).v2_delete_sessions(["t1", "t2", "t3"], "u1")
        self.assertEqual(set(client.rows), {"t1", "t2", "t3"})
        deletes = [c for c in client.calls if c[1] == "delete"]
        self.assertEqual(len(deletes), 1)
        self.assertIn(("in", "id", ["t1", "t2", "t3"]), deletes[0][3])

    def test_the_delete_stays_owner_scoped(self):
        # The routes resolve ownership first; this proves the statement
        # itself can never reach another user's Take.
        client = _FakeV2Sessions([_row("t1", user="someone-else")])
        self._repo(client).v2_delete_sessions(["t1"], "u1")
        self.assertEqual(client.rows["t1"], _row("t1", user="someone-else"))
        delete = next(c for c in client.calls if c[1] == "delete")
        self.assertIn(("eq", "user_id", "u1"), delete[3])

    def test_a_silent_no_op_is_not_success(self):
        client = _FakeV2Sessions([_row("t1")], silently_ignore_delete=True)
        with self.assertRaises(TakeDeleteNotApplied) as ctx:
            self._repo(client).v2_delete_session("t1", "u1")
        self.assertEqual(ctx.exception.session_ids, ["t1"])

    def test_fk_violation_is_recognised_by_message_too(self):
        class _Bare(Exception):
            pass

        class _Client(_FakeV2Sessions):
            def respond(self, q):
                if q.op == "delete":
                    raise _Bare('... violates foreign key constraint "x" ...')
                return super().respond(q)

        with self.assertRaises(TakeHasLineageError):
            self._repo(_Client([_row("t1")])).v2_delete_session("t1", "u1")

    def test_other_failures_propagate_unchanged(self):
        class _Client(_FakeV2Sessions):
            def respond(self, q):
                if q.op == "delete":
                    raise RuntimeError("connection reset")
                return super().respond(q)

        with self.assertRaises(RuntimeError):
            self._repo(_Client([_row("t1")])).v2_delete_session("t1", "u1")

    def test_empty_set_touches_nothing(self):
        client = _FakeV2Sessions([_row("t1")])
        self._repo(client).v2_delete_sessions([], "u1")
        self.assertEqual(client.calls, [])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RoutesAnswer409OnLineageTests(unittest.TestCase):
    """All three user delete routes, against the fake table: a refused Take
    is 409 TAKE_HAS_LINEAGE with every row untouched — never 200."""

    def setUp(self):
        self.app = Flask(__name__)
        ref = "https://x/deck.pdf"
        self.pid = v2_arcs._presentation_group_key(
            {"slides": DECK, "presentation_ref": ref})
        ctx = {"slides": DECK, "presentation_ref": ref}
        self.sessions = [
            {"id": "t1", "user_id": "u1", "created_at": "2026-07-01",
             "intake_context": ctx},
            {"id": _SID, "user_id": "u1", "created_at": "2026-07-02",
             "intake_context": ctx},
        ]
        self.table = _FakeV2Sessions(
            [dict(_row(s["id"])) for s in self.sessions], restricted={_SID})
        repo = TakeRepository(_Db(self.table))
        self._p = [
            patch.object(db.takes, "v2_delete_sessions", repo.v2_delete_sessions),
            patch.object(db.takes, "v2_list_user_lab_sessions",
                         lambda uid, **kw: list(self.sessions)),
            patch.object(db, "v2_get_session_by_id",
                         lambda sid: next((s for s in self.sessions
                                           if s["id"] == sid), None)),
            patch("routes.v2.user_sessions._user_presentation_groups",
                  lambda uid: {self.pid: ["t1", _SID]}),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _call(self, view, *args):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = view.__wrapped__(*args)
            return resp.get_json(), status

    def _assert_untouched(self):
        self.assertEqual(self.table.rows["t1"], _row("t1"))
        self.assertEqual(self.table.rows[_SID], _row(_SID))

    def test_presentation_with_one_canonical_take_deletes_nothing(self):
        body, status = self._call(
            v2_user_sessions.v2_user_delete_presentation, self.pid)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "TAKE_HAS_LINEAGE")
        # The legacy take t1 would have deleted alone; one statement means
        # the presentation is never left half-deleted.
        self._assert_untouched()

    def test_take_delete_refused_is_409(self):
        body, status = self._call(
            v2_user_sessions.v2_user_delete_take, self.pid, "2")
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "TAKE_HAS_LINEAGE")
        self._assert_untouched()

    def test_session_delete_refused_is_409(self):
        body, status = self._call(v2_user_sessions.v2_user_delete_session, _SID)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "TAKE_HAS_LINEAGE")
        self._assert_untouched()

    def test_legacy_take_still_deletes(self):
        body, status = self._call(
            v2_user_sessions.v2_user_delete_take, self.pid, "1")
        self.assertEqual(status, 200)
        self.assertEqual(body["deleted_session"], "t1")
        self.assertNotIn("t1", self.table.rows)
        self.assertIn(_SID, self.table.rows)

    def test_a_delete_that_did_not_land_is_not_200(self):
        self.table.restricted.clear()
        self.table.silently_ignore_delete = True
        _, status = self._call(
            v2_user_sessions.v2_user_delete_take, self.pid, "1")
        self.assertEqual(status, 500)
        self.assertIn("t1", self.table.rows)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CleanupKeepsCanonicalTakesQuietlyTests(unittest.TestCase):

    def test_lineage_refusal_is_not_counted_and_not_reported(self):
        table = _FakeV2Sessions([_row("a"), _row("b")], restricted={"b"})
        repo = TakeRepository(_Db(table))
        with patch.object(db.takes, "v2_get_incomplete_sessions_older_than",
                          lambda h: [{"id": "a", "user_id": "u1"},
                                     {"id": "b", "user_id": "u1"}]), \
             patch.object(db.takes, "v2_delete_session", repo.v2_delete_session), \
             patch("services.db.sentry_sdk.capture_exception") as capture:
            n, ids = db.v2_cleanup_incomplete_sessions(hours=1)
        self.assertEqual((n, ids), (1, ["a"]))
        self.assertEqual(table.rows["b"], _row("b"))
        capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
