"""willab — POST /v2/user/snippets/<id>/suggestion-feedback (founder
2026-07-14): the Apply / ✓-prefer taps on the instant view's suggestion rows.

Route-level tests (test_arc_unlock.py harness: patch db.* on the v2 module,
call the unwrapped handler in a test_request_context). Guest writes require
the same signed Guest ID as the readout; a bare session UUID fails closed.

Run: python3 -m unittest tests.test_suggestion_feedback
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
    """Founder bug 2026-07-22 ("Couldn't save that just now"): the FE's
    Living-Transcript targets document_replace / document_bold were
    rejected 400 by the allowlist — every Accept/Keep on the document
    failed at the door. The #221 bug class, pinned here."""

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


    def test_document_bold_maps_to_emphasize(self):
        _, status, m_led = self._call("document_bold")
        self.assertEqual(status, 200)
        self.assertEqual(m_led.call_args.kwargs["kind"], "emphasize")


if __name__ == "__main__":
    unittest.main()
