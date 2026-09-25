"""Training deletion (backlog 4.4) — regression tests for the reported
"deleting a training doesn't remove it" bug.

Root cause: the DELETE endpoints resolved their target set from the
historical deck-hash grouping, so (a) a deck with no coach-published
'strong' rows 404'd, and (b) takes without library rows survived a
"delete ALL takes" and kept resurfacing in session-backed lists.
Fixed: presentation delete resolves the COMPLETE session set from the
user's lab sessions; a new DELETE /user/sessions/<id> covers deckless
trainings (previously undeletable). Take-number deletes keep the library
grouping — that numbering is the FE contract from /user/strengths.

Flask-route classes skip locally, run in CI (the known gotcha).

Run: python3 -m unittest tests.test_training_deletion
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

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


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PresentationDeleteCompleteSetTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        # Keyed the same way the route keys it (2026-08-15): an UPLOADED
        # deck — the PDF is what makes slides an identity.
        self._ref = "https://x/deck.pdf"
        self._pid = v2_arcs._presentation_group_key(
            {"slides": DECK, "presentation_ref": self._ref})
        # 3 takes of the deck; only ONE has library rows (the old grouping
        # saw just that one). +1 unrelated deck session.
        self._sessions = [
            {"id": "t1", "created_at": "2026-07-01",
             "intake_context": {"slides": DECK,
                                "presentation_ref": "https://x/deck.pdf"}},
            {"id": "t2", "created_at": "2026-07-02",
             "intake_context": {"slides": DECK,
                                "presentation_ref": "https://x/deck.pdf"}},
            {"id": "t3", "created_at": "2026-07-03",
             "intake_context": {"slides": DECK,
                                "presentation_ref": "https://x/deck.pdf"}},
            {"id": "x1", "created_at": "2026-07-04",
             "intake_context": {"slides": [{"title": "Other", "body": "z"}],
                                "presentation_ref": "https://x/other.pdf"}},
        ]
        self._deleted = []
        self._p = [
            patch.object(db.takes, "v2_list_user_lab_sessions",
                         lambda uid, **kw: list(self._sessions)),
            patch("routes.v2.user_sessions._hard_delete_session_for_user",
                         lambda uid, sid: self._deleted.append(sid)),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _call(self, pid=None):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2_user_sessions.v2_user_delete_presentation.__wrapped__(
                pid if pid is not None else self._pid)
            return resp.get_json(), status

    def test_deletes_every_take_not_just_library_visible(self):
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(body["deleted_sessions"], 3)
        self.assertEqual(sorted(self._deleted), ["t1", "t2", "t3"])
        self.assertNotIn("x1", self._deleted)  # other deck untouched

    def test_unknown_presentation_404s(self):
        _, status = self._call(pid="not-a-real-pid")
        self.assertEqual(status, 404)
        self.assertEqual(self._deleted, [])

    def test_no_library_rows_still_deletes(self):
        # The old grouping (library-driven) would 404 here; the fix resolves
        # from sessions, so a never-published deck still deletes fully.
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(len(self._deleted), 3)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SessionDeleteTests(unittest.TestCase):
    """DELETE /user/sessions/<id> — the deckless-training delete path."""

    def setUp(self):
        self.app = Flask(__name__)
        self._session = {"id": _SID, "user_id": "u1"}
        self._deleted = []
        self._p = [
            patch.object(db, "v2_get_session_by_id",
                         lambda sid: self._session),
            patch("routes.v2.user_sessions._hard_delete_session_for_user",
                         lambda uid, sid: self._deleted.append(sid)),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _call(self, session_id=_SID, user_id="u1"):
        with self.app.test_request_context():
            request.user_id = user_id
            resp, status = v2_user_sessions.v2_user_delete_session.__wrapped__(session_id)
            return resp.get_json(), status

    def test_owner_deletes(self):
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(body["deleted_session"], _SID)
        self.assertEqual(self._deleted, [_SID])

    def test_non_owner_404s(self):
        _, status = self._call(user_id="intruder")
        self.assertEqual(status, 404)
        self.assertEqual(self._deleted, [])

    def test_unknown_session_404s(self):
        self._session = None
        _, status = self._call()
        self.assertEqual(status, 404)

    def test_bad_uuid_400s(self):
        _, status = self._call(session_id="nope")
        self.assertEqual(status, 400)


_ARC = "22222222-2222-4222-8222-222222222222"
_OTHER_ARC = "33333333-3333-4333-8333-333333333333"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ArcDeleteTests(unittest.TestCase):
    """DELETE /user/arcs/<arc_id> — the project picker's delete. The set is
    the owner's arc-keyed rows, read through the same scoped repository read
    /user/trainings uses, so another user's project can never be reached."""

    def setUp(self):
        self.app = Flask(__name__)
        self._rows = {
            "u1": [
                {"id": "t1", "arc_id": _ARC, "take_index": 1},
                {"id": "t2", "arc_id": _ARC, "take_index": 2},
                {"id": "r2", "arc_id": _ARC, "take_index": 2,
                 "recording_kind": "read", "paired_session_id": "t2"},
                {"id": "o1", "arc_id": _OTHER_ARC, "take_index": 1},
            ],
            "intruder": [],
        }
        self._deleted = []
        self._p = [
            patch.object(db.takes, "list_user_arc_sessions",
                         lambda uid: list(self._rows.get(uid, []))),
            patch("routes.v2.user_sessions._hard_delete_session_for_user",
                  lambda uid, sid: self._deleted.append((uid, sid))),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _call(self, arc_id=_ARC, user_id="u1"):
        with self.app.test_request_context():
            request.user_id = user_id
            resp, status = v2_user_sessions.v2_user_delete_arc.__wrapped__(arc_id)
            return resp.get_json(), status

    def test_deletes_every_take_of_the_arc_only(self):
        body, status = self._call()
        self.assertEqual(status, 200)
        self.assertEqual(body["deleted_sessions"], 3)
        self.assertEqual(self._deleted,
                         [("u1", "t1"), ("u1", "t2"), ("u1", "r2")])

    def test_non_owner_404s(self):
        _, status = self._call(user_id="intruder")
        self.assertEqual(status, 404)
        self.assertEqual(self._deleted, [])

    def test_bad_uuid_400s(self):
        _, status = self._call(arc_id="nope")
        self.assertEqual(status, 400)
        self.assertEqual(self._deleted, [])


if __name__ == "__main__":
    unittest.main()
