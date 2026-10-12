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
    TakeRepository,
)

try:
    from flask import Flask, request

    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


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
    return {"id": sid, "user_id": user, "recording_id": f"rec-{sid}",
            "report_id": f"rep-{sid}"}


class RepositoryDeleteTests(unittest.TestCase):

    def _repo(self, client):
        return TakeRepository(_Db(client))


    def test_the_delete_stays_owner_scoped(self):
        # The routes resolve ownership first; this proves the statement
        # itself can never reach another user's Take.
        client = _FakeV2Sessions([_row("t1", user="someone-else")])
        self._repo(client).v2_delete_sessions(["t1"], "u1")
        self.assertEqual(client.rows["t1"], _row("t1", user="someone-else"))
        delete = next(c for c in client.calls if c[1] == "delete")
        self.assertIn(("eq", "user_id", "u1"), delete[3])


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
