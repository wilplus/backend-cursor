"""willab — POST /v2/user/snippets/<id>/suggestion-feedback (founder
2026-07-14): the Apply / ✓-prefer taps on the instant view's suggestion rows.

Route-level tests (test_arc_unlock.py harness: patch db.* on the v2 module,
call the unwrapped handler in a test_request_context). Guest writes require
the same signed Guest ID as the readout; a bare session UUID fails closed.

Run: python3 -m unittest test_suggestion_feedback
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    from services.project_ownership import (
        GUEST_OWNER_HEADER,
        issue_guest_owner,
    )
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

    def _call(self, body, caller=None, snippet_id=SNIP, guest_token=None):
        headers = {GUEST_OWNER_HEADER: guest_token} if guest_token else None
        with self.app.test_request_context(json=body, headers=headers):
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
        issued = issue_guest_owner()
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value={
                              "id": SESS,
                              "user_id": None,
                              "owner_principal_id": issued.principal_id,
                          }), \
             patch.object(v2.db, "get_owner_principal",
                          return_value={
                              "id": issued.principal_id,
                              "user_id": None,
                              "guest_secret_hash": issued.secret_hash,
                          }), \
             patch.object(v2.db, "get_snippet_by_id",
                          return_value={"id": SNIP, "session_id": SESS}), \
             patch.object(v2.db, "insert_user_suggestion_feedback",
                          return_value=True) as m_ins:
            body, status = self._call(
                self._ok_body(target="comment", action="preferred",
                              upgrade_index=None),
                caller=None,
                guest_token=issued.token)
        self.assertEqual(status, 200)
        self.assertIsNone(m_ins.call_args.kwargs["user_id"])

    def test_guest_bare_session_id_is_not_authorization(self):
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value={
                              "id": SESS,
                              "user_id": None,
                              "owner_principal_id": (
                                  "33333333-3333-4333-8333-333333333333"
                              ),
                          }), \
             patch.object(v2.db, "insert_user_suggestion_feedback") as m_ins:
            _, status = self._call(self._ok_body(), caller=None)
        self.assertEqual(status, 404)
        m_ins.assert_not_called()

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


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class LedgerHookTests(unittest.TestCase):
    """Founder 2026-07-20 (gradual refinement PR-2): a star tap on
    moment_replace/moment_emphasize is ALSO a durable phrase decision —
    applied → approved (bakes next assembly), dismissed → dismissed + the
    star row is deleted (never offered again, current version included),
    reverted → the ledger row is wiped (clean slate)."""

    ARC = "arc-9"

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, action, target="moment_replace", trigger="polish"):
        body = {"session_id": SESS, "target": target, "action": action}
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value={"id": SESS, "user_id": "u1",
                                            "arc_id": self.ARC}), \
                 patch.object(v2.db, "get_snippet_by_id",
                              return_value={"id": SNIP, "session_id": SESS,
                                            "transcript": "The Rough Span"}), \
                 patch.object(v2.db, "insert_user_suggestion_feedback",
                              return_value=True), \
                 patch.object(v2.db, "get_moment_suggestions_by_arc",
                              return_value={SNIP: {
                                  "snippet_id": SNIP, "kind": "replace",
                                  "trigger": trigger,
                                  "replacement_text": "smoother"}}), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={"version": 3}), \
                 patch.object(v2.db, "upsert_ideal_decision",
                              return_value=True) as m_up, \
                 patch.object(v2.db, "delete_ideal_decision",
                              return_value=True) as m_del, \
                 patch.object(v2.db, "delete_moment_suggestion",
                              return_value=True) as m_row:
                out = v2.v2_user_suggestion_feedback.__wrapped__(SNIP)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_up, m_del, m_row

    def test_applied_writes_approved_polish(self):
        body, status, m_up, m_del, m_row = self._call("applied")
        self.assertEqual(status, 200)
        kw = m_up.call_args.kwargs
        self.assertEqual(kw["kind"], "polish")     # trigger=polish maps
        self.assertEqual(kw["decision"], "approved")
        self.assertEqual(kw["target_phrase"], "the rough span")
        self.assertEqual(kw["replacement_text"], "smoother")
        self.assertEqual(kw["version"], 3)
        m_del.assert_not_called()
        m_row.assert_not_called()   # an applied star folds; row stays

    def test_dismissed_writes_dismissed_and_kills_the_row(self):
        body, status, m_up, m_del, m_row = self._call(
            "dismissed", trigger="threat")
        self.assertEqual(status, 200)
        kw = m_up.call_args.kwargs
        self.assertEqual(kw["kind"], "replace")
        self.assertEqual(kw["decision"], "dismissed")
        m_row.assert_called_once_with(SNIP)

    def test_reverted_wipes_the_ledger_row(self):
        body, status, m_up, m_del, m_row = self._call("reverted")
        self.assertEqual(status, 200)
        m_del.assert_called_once_with(self.ARC, "polish", "the rough span")
        m_up.assert_not_called()
        m_row.assert_not_called()

    def test_structure_target_never_touches_the_ledger(self):
        body, status, m_up, m_del, m_row = self._call(
            "applied", target="moment_structure")
        self.assertEqual(status, 200)
        m_up.assert_not_called()
        m_del.assert_not_called()

    def test_ledger_failure_never_breaks_the_post(self):
        body = {"session_id": SESS, "target": "moment_replace",
                "action": "applied"}
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value={"id": SESS, "user_id": "u1",
                                            "arc_id": self.ARC}), \
                 patch.object(v2.db, "get_snippet_by_id",
                              return_value={"id": SNIP, "session_id": SESS,
                                            "transcript": "x"}), \
                 patch.object(v2.db, "insert_user_suggestion_feedback",
                              return_value=True), \
                 patch.object(v2.db, "get_moment_suggestions_by_arc",
                              side_effect=RuntimeError("boom")):
                out = v2.v2_user_suggestion_feedback.__wrapped__(SNIP)
                resp, status = out if isinstance(out, tuple) else (out, 200)
        self.assertEqual(status, 200)
        self.assertTrue(resp.get_json()["saved"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DocumentPhraseKeyTests(unittest.TestCase):
    """The ledger key must be the DOCUMENT phrase (founder bug
    2026-07-22) — keyed on the raw transcript the approval saved and
    then silently did nothing."""

    ARC = "arc-9"
    RAW = "um we started small in a tiny room"

    def setUp(self):
        self.app = Flask(__name__)

    def test_key_is_the_smoothed_document_phrase_not_the_raw_words(self):
        with self.app.test_request_context():
            with patch.dict("os.environ",
                            {"LIVING_TRANSCRIPT_ENABLED": "1"}), \
                 patch.object(v2.db, "get_arc_sessions",
                              return_value=[{"id": SESS, "take_index": 1,
                                             "recording_kind": "spoken"}]), \
                 patch.object(v2.db, "get_snippets_by_session",
                              return_value=[{"id": SNIP,
                                             "start_offset_ms": 0,
                                             "language": "en",
                                             "transcript": self.RAW}]), \
                 patch.object(v2.db, "get_coach_snippet_drafts",
                              return_value=[]), \
                 patch.object(v2.db, "get_user_transcript_edits",
                              return_value=[]):
                out = v2._document_phrase_for(self.ARC, SNIP,
                                              fallback=self.RAW)
        self.assertEqual(out, "We started small in a tiny room")
        self.assertNotIn("um ", out)

    def test_flag_off_keeps_the_raw_fallback(self):
        with self.app.test_request_context():
            with patch.dict("os.environ",
                            {"LIVING_TRANSCRIPT_ENABLED": "0"}):
                out = v2._document_phrase_for(self.ARC, SNIP,
                                              fallback=self.RAW)
        self.assertEqual(out, self.RAW)

    def test_build_failure_falls_back_never_raises(self):
        with self.app.test_request_context():
            with patch.dict("os.environ",
                            {"LIVING_TRANSCRIPT_ENABLED": "1"}), \
                 patch.object(v2.db, "get_arc_sessions",
                              side_effect=RuntimeError("boom")):
                out = v2._document_phrase_for(self.ARC, SNIP,
                                              fallback=self.RAW)
        self.assertEqual(out, self.RAW)


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
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value={"id": SESS, "user_id": "u1",
                                            "arc_id": self.ARC}), \
                 patch.object(v2.db, "get_snippet_by_id",
                              return_value={"id": SNIP, "session_id": SESS,
                                            "transcript": "the span"}), \
                 patch.object(v2.db, "insert_user_suggestion_feedback",
                              return_value=True), \
                 patch.object(v2.db, "get_moment_suggestions_by_arc",
                              return_value={SNIP: {
                                  "snippet_id": SNIP, "kind": "replace",
                                  "trigger": "polish",
                                  "replacement_text": "smoother"}}), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={"version": 2}), \
                 patch("routes.v2.user_sessions._document_phrase_for",
                              side_effect=lambda a, sn, fallback=None:
                              fallback), \
                 patch.object(v2.db, "upsert_ideal_decision",
                              return_value=True) as m_led, \
                 patch.object(v2.db, "delete_moment_suggestion",
                              return_value=True), \
                 patch("routes.v2.user_sessions._reassemble_after_decision",
                              return_value=None):
                out = v2.v2_user_suggestion_feedback.__wrapped__(SNIP)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_led

    def test_document_replace_is_accepted_and_ledgered(self):
        body, status, m_led = self._call("document_replace")
        self.assertEqual(status, 200)          # was 400 before the fix
        self.assertTrue(body["saved"])
        kw = m_led.call_args.kwargs
        self.assertEqual(kw["decision"], "approved")
        self.assertEqual(kw["kind"], "polish")   # trigger=polish maps

    def test_document_bold_maps_to_emphasize(self):
        _, status, m_led = self._call("document_bold")
        self.assertEqual(status, 200)
        self.assertEqual(m_led.call_args.kwargs["kind"], "emphasize")

    def test_document_dismiss_is_remembered(self):
        _, status, m_led = self._call("document_replace",
                                      action="dismissed")
        self.assertEqual(status, 200)
        self.assertEqual(m_led.call_args.kwargs["decision"], "dismissed")

    def test_applied_map_counts_document_targets(self):
        with Flask(__name__).test_request_context():
            with patch.object(v2.db, "get_suggestion_feedback_by_session",
                              return_value=[{"snippet_id": SNIP,
                                             "target": "document_replace",
                                             "action": "applied"}]):
                out = v2._moment_applied_map([SESS])
        self.assertTrue(out.get(SNIP))   # consumed → no re-offer


if __name__ == "__main__":
    unittest.main()
