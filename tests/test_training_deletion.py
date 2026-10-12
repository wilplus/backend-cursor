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

    from routes.v2 import user_sessions as v2_user_sessions
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


_SID = "11111111-1111-4111-8111-111111111111"


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
            patch("routes.v2.user_sessions._hard_delete_sessions_for_user",
                  lambda uid, sids: self._deleted.extend(sids)),
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


if __name__ == "__main__":
    unittest.main()
