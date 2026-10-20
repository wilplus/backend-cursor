"""
STORY    As a speaker, I want my Accept/Keep taps on a suggestion in the Ideal
         Text to be saved, so that my choice sticks and I am never told
         "Couldn't save that just now".
OUTCOME
  O1  POST suggestion-feedback with document_replace or document_bold
      answers 200 {saved: true} and records the decision with the right kind
      (polish/replace, emphasize).
  O2  A guest without a signed Guest ID (a bare session UUID) is refused
      404 and nothing is recorded.
PROVES   O1 -> test_document_replace_and_bold_are_saved_with_their_kind
         O2 -> test_a_guest_without_a_signed_id_is_refused
WHY      Founder bug 2026-07-22: the document targets were rejected 400 by
         the allowlist, so every Accept/Keep on the document failed. The
         other targets live in tests/test_user_sessions_route_contracts.py.
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

SESS = "11111111-1111-1111-1111-111111111111"
SNIP = "22222222-2222-2222-2222-222222222222"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DocumentTargetTests(unittest.TestCase):

    ARC = "arc-9"

    def _call(self, target, action="applied"):
        body = {"session_id": SESS, "target": target, "action": action}
        with Flask(__name__).test_request_context(json=body):
            request.user_id = "u1"
            with patch.object(db, "v2_get_session_by_id",
                              return_value={"id": SESS, "user_id": "u1",
                                            "arc_id": self.ARC}), \
                 patch.object(db, "get_snippet_by_id",
                              return_value={"id": SNIP, "session_id": SESS,
                                            "transcript": "the span"}), \
                 patch.object(db, "insert_user_suggestion_feedback",
                              return_value=True), \
                 patch.object(db, "get_moment_suggestions_by_arc",
                              return_value={SNIP: {
                                  "snippet_id": SNIP, "kind": "replace",
                                  "trigger": "polish",
                                  "replacement_text": "smoother"}}), \
                 patch.object(db.ideal_text, "get_coach_arc_ideal_text",
                              return_value={"version": 2}), \
                 patch("routes.v2.user_sessions._document_phrase_for",
                              side_effect=lambda a, sn, fallback=None:
                              fallback), \
                 patch.object(db, "upsert_ideal_decision",
                              return_value=True) as m_led, \
                 patch.object(db, "delete_moment_suggestion",
                              return_value=True), \
                 patch("routes.v2.user_sessions._reassemble_after_decision",
                              return_value=None):
                out = v2_user_sessions.v2_user_suggestion_feedback.__wrapped__(SNIP)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_led

    def test_document_replace_and_bold_are_saved_with_their_kind(self):
        for target, kind in (("document_replace", "polish"),
                             ("document_bold", "emphasize")):
            body, status, m_led = self._call(target)
            self.assertEqual((status, body), (200, {"saved": True}), target)
            self.assertEqual(m_led.call_args.kwargs["kind"], kind, target)

    def test_a_guest_without_a_signed_id_is_refused(self):
        body = {"session_id": SESS, "target": "document_replace",
                "action": "applied"}
        session = {"id": SESS, "user_id": None,
                   "owner_principal_id": "33333333-3333-4333-8333-333333333333"}
        with Flask(__name__).test_request_context(
                json=body, headers={v2_user_sessions.GUEST_OWNER_HEADER: SESS}):
            request.user_id = None
            with patch.object(db, "v2_get_session_by_id", return_value=session), \
                 patch.object(db, "insert_user_suggestion_feedback") as insert, \
                 patch.object(db, "upsert_ideal_decision") as ledger:
                resp, status = v2_user_sessions.v2_user_suggestion_feedback.__wrapped__(SNIP)
        self.assertEqual((status, resp.get_json()["code"]), (404, "NOT_FOUND"))
        insert.assert_not_called()
        ledger.assert_not_called()


if __name__ == "__main__":
    unittest.main()
