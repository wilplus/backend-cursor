"""Training deletion (backlog 4.4) — regression tests for the reported
"deleting a training doesn't remove it" bug.

Root cause: the DELETE endpoints resolved their target set from the
strong-sides LIBRARY grouping, so (a) a deck with no coach-published
'strong' rows 404'd, and (b) takes without library rows survived a
"delete ALL takes" and kept resurfacing in session-backed lists.
Fixed: presentation delete resolves the COMPLETE session set from the
user's lab sessions; a new DELETE /user/sessions/<id> covers deckless
trainings (previously undeletable). Take-number deletes keep the library
grouping — that numbering is the FE contract from /user/strengths.

Flask-route classes skip locally, run in CI (the known gotcha).

Run: python3 -m unittest test_training_deletion
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
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
        self._pid = v2._presentation_group_key(
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
            patch.object(v2.db, "v2_list_user_lab_sessions",
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
            resp, status = v2.v2_user_delete_presentation.__wrapped__(
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
            patch.object(v2.db, "v2_get_session_by_id",
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
            resp, status = v2.v2_user_delete_session.__wrapped__(session_id)
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


if __name__ == "__main__":
    unittest.main()
