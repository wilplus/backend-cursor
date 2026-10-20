"""
STORY    As a speaker, I want deleting a presentation or a deckless training to
         really remove it, so that it never comes back in my lists.
         (Critical path: deletion.)
OUTCOME
  O1  The owner deletes a deckless session: 200, and the row is gone from
      the table the lists read.
  O2  A stranger cannot delete someone else's session: 404, and the row is
      still there.
  O3  Deleting a presentation removes EVERY Take of that deck, and nothing
      of the speaker's other trainings.
PROVES   O1 -> test_owner_deletes_a_deckless_session_and_it_is_gone
         O2 -> test_a_stranger_cannot_delete_someone_elses_session
         O3 -> test_presentation_delete_removes_every_take_of_that_deck_only
WHY      Backlog 4.4: "deleting a training doesn't remove it" (takes without
         library rows survived and resurfaced).

The routes run against the real TakeRepository over an in-memory v2_sessions
table, so "gone" is what the table holds afterwards. The SQL refusal of a Take
that still has lineage (409) is test_take_delete_lineage.py's.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request

    from routes.v2 import user_sessions as v2_user_sessions
    from services.db import db
    from services.take_repository import TakeRepository
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


ME, STRANGER = "u1", "u2"
DECKLESS = "11111111-1111-4111-8111-111111111111"
THEIRS = "22222222-2222-4222-8222-222222222222"
DECK = [{"title": "Q3", "body": "revenue"}]
OTHER_DECK = [{"title": "Hiring", "body": "plan"}]


def _deck_take(sid, slides, created_at, user=ME):
    return {"id": sid, "user_id": user, "source": "audit_upload",
            "created_at": created_at,
            "intake_context": {"topic": "t", "slides": slides,
                               "presentation_ref": "https://x.test/deck.pdf"}}


class _Q:
    def __init__(self, table, op):
        self.table, self.op, self.filters = table, op, []

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: str(r.get(col)) == str(val))
        return self

    def in_(self, col, vals):
        vals = {str(v) for v in vals}
        self.filters.append(lambda r: str(r.get(col)) in vals)
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def execute(self):
        hits = [r for r in self.table.rows if all(f(r) for f in self.filters)]
        if self.op == "delete":
            self.table.rows = [r for r in self.table.rows if r not in hits]
        return type("R", (), {"data": [dict(r) for r in hits]})()


class _Sessions:
    """v2_sessions in memory: enough of the PostgREST builder for the reads
    and the one owner-scoped DELETE the repository issues."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]

    def table(self, name):
        assert name == "v2_sessions", name
        return self

    def select(self, *_a):
        return _Q(self, "select")

    def delete(self):
        return _Q(self, "delete")

    def ids(self):
        return {r["id"] for r in self.rows}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TrainingDeletionTests(unittest.TestCase):

    def _use(self, rows):
        self.table = _Sessions(rows)
        repo = TakeRepository(type("Db", (), {"client": self.table})())
        p = patch.dict(db.__dict__, {"_takes_repo": repo})
        p.start()
        self.addCleanup(p.stop)

    def _call(self, view, *args, user_id=ME):
        with Flask(__name__).test_request_context():
            request.user_id = user_id
            resp, status = view.__wrapped__(*args)
            return resp.get_json(), status

    def test_owner_deletes_a_deckless_session_and_it_is_gone(self):
        self._use([{"id": DECKLESS, "user_id": ME, "source": "audit_upload",
                    "intake_context": {"topic": "book"}}])
        body, status = self._call(v2_user_sessions.v2_user_delete_session, DECKLESS)
        self.assertEqual((status, body["deleted_session"]), (200, DECKLESS))
        self.assertEqual(self.table.ids(), set())
        self.assertEqual(db.takes.v2_list_user_lab_sessions(ME), [])

    def test_a_stranger_cannot_delete_someone_elses_session(self):
        self._use([{"id": THEIRS, "user_id": ME, "source": "audit_upload"}])
        body, status = self._call(v2_user_sessions.v2_user_delete_session,
                                  THEIRS, user_id=STRANGER)
        self.assertEqual((status, body["code"]), (404, "SESSION_NOT_FOUND"))
        self.assertEqual(self.table.ids(), {THEIRS})

    def test_presentation_delete_removes_every_take_of_that_deck_only(self):
        self._use([
            _deck_take("t1", DECK, "2026-10-01"),
            _deck_take("t2", DECK, "2026-10-02"),
            _deck_take("t3", DECK, "2026-10-03"),
            _deck_take("keep", OTHER_DECK, "2026-10-04"),
            _deck_take("theirs", DECK, "2026-10-05", user=STRANGER),
        ])
        pid = v2_user_sessions._presentation_group_key(
            _deck_take("x", DECK, "")["intake_context"])
        body, status = self._call(v2_user_sessions.v2_user_delete_presentation, pid)
        self.assertEqual((status, body["deleted_sessions"]), (200, 3))
        self.assertEqual(self.table.ids(), {"keep", "theirs"})
        self.assertEqual([s["id"] for s in db.takes.v2_list_user_lab_sessions(ME)],
                         ["keep"])


if __name__ == "__main__":
    unittest.main()
