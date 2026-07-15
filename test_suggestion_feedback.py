"""willab — POST /v2/user/snippets/<id>/suggestion-feedback (founder
2026-07-14): the Apply / ✓-prefer taps on the instant view's suggestion rows.

Route-level tests (test_arc_unlock.py harness: patch db.* on the v2 module,
call the unwrapped handler in a test_request_context). Guest capability
mirrors the guest readout: unclaimed session writable by bare id; claimed →
owner-only 404 (no existence leak).

Run: python3 -m unittest test_suggestion_feedback
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

SESS = "11111111-1111-1111-1111-111111111111"
SNIP = "22222222-2222-2222-2222-222222222222"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SuggestionFeedbackTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, body, caller=None, snippet_id=SNIP):
        with self.app.test_request_context(json=body):
            request.user_id = caller
            out = v2.v2_user_suggestion_feedback.__wrapped__(snippet_id)
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    def _ok_body(self, **over):
        b = {"session_id": SESS, "target": "upgrade",
             "action": "applied", "upgrade_index": 1,
             "suggestion_version": "2"}
        b.update(over)
        return b

    def test_authed_owner_saves(self):
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value={"id": SESS, "user_id": "u1"}), \
             patch.object(v2.db, "get_snippet_by_id",
                          return_value={"id": SNIP, "session_id": SESS}), \
             patch.object(v2.db, "insert_user_suggestion_feedback",
                          return_value=True) as m_ins:
            body, status = self._call(self._ok_body(), caller="u1")
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        kw = m_ins.call_args.kwargs
        self.assertEqual(kw["snippet_id"], SNIP)
        self.assertEqual(kw["target"], "upgrade")
        self.assertEqual(kw["action"], "applied")
        self.assertEqual(kw["upgrade_index"], 1)
        self.assertEqual(kw["user_id"], "u1")

    def test_guest_on_unclaimed_session_saves(self):
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value={"id": SESS, "user_id": None}), \
             patch.object(v2.db, "get_snippet_by_id",
                          return_value={"id": SNIP, "session_id": SESS}), \
             patch.object(v2.db, "insert_user_suggestion_feedback",
                          return_value=True) as m_ins:
            body, status = self._call(
                self._ok_body(target="comment", action="preferred",
                              upgrade_index=None),
                caller=None)
        self.assertEqual(status, 200)
        self.assertIsNone(m_ins.call_args.kwargs["user_id"])

    def test_claimed_session_hidden_from_other_caller(self):
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value={"id": SESS, "user_id": "owner"}), \
             patch.object(v2.db, "insert_user_suggestion_feedback") as m_ins:
            _, s_guest = self._call(self._ok_body(), caller=None)
            _, s_other = self._call(self._ok_body(), caller="intruder")
        self.assertEqual((s_guest, s_other), (404, 404))
        m_ins.assert_not_called()

    def test_snippet_must_belong_to_session(self):
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value={"id": SESS, "user_id": "u1"}), \
             patch.object(v2.db, "get_snippet_by_id",
                          return_value={"id": SNIP,
                                        "session_id": "other-session"}), \
             patch.object(v2.db, "insert_user_suggestion_feedback") as m_ins:
            body, status = self._call(self._ok_body(), caller="u1")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "SNIPPET_NOT_FOUND")
        m_ins.assert_not_called()

    def test_bad_target_action_and_index_400(self):
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value={"id": SESS, "user_id": "u1"}):
            _, s1 = self._call(self._ok_body(target="scores"), caller="u1")
            _, s2 = self._call(self._ok_body(action="loved"), caller="u1")
            _, s3 = self._call(self._ok_body(upgrade_index=-1), caller="u1")
            _, s4 = self._call(self._ok_body(upgrade_index=True), caller="u1")
        self.assertEqual((s1, s2, s3, s4), (400, 400, 400, 400))

    def test_bad_uuids_400(self):
        _, s1 = self._call(self._ok_body(session_id="nope"), caller="u1")
        _, s2 = self._call(self._ok_body(), caller="u1", snippet_id="nope")
        self.assertEqual((s1, s2), (400, 400))

    def test_reverted_action_accepted(self):
        # Approve is a reversible toggle (2026-07-15) — the undo reports as
        # action='reverted' so applied→reverted pairs stay honest.
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value={"id": SESS, "user_id": "u1"}), \
             patch.object(v2.db, "get_snippet_by_id",
                          return_value={"id": SNIP, "session_id": SESS}), \
             patch.object(v2.db, "insert_user_suggestion_feedback",
                          return_value=True) as m_ins:
            body, status = self._call(
                self._ok_body(action="reverted"), caller="u1")
        self.assertEqual(status, 200)
        self.assertEqual(m_ins.call_args.kwargs["action"], "reverted")

    def test_apply_all_case(self):
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value={"id": SESS, "user_id": "u1"}), \
             patch.object(v2.db, "get_snippet_by_id",
                          return_value={"id": SNIP, "session_id": SESS}), \
             patch.object(v2.db, "insert_user_suggestion_feedback",
                          return_value=True) as m_ins:
            body, status = self._call(
                self._ok_body(target="comment_video", action="apply_all",
                              upgrade_index=None),
                caller="u1")
        self.assertEqual(status, 200)
        self.assertEqual(m_ins.call_args.kwargs["action"], "apply_all")


if __name__ == "__main__":
    unittest.main()
