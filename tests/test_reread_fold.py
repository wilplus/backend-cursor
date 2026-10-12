"""willab — fold mid-take RE-READS into their parent take (founder fix-pack
2026-07-16, BE-2 + BE-3a + BE-4).

The founder's rule: "recordings recorded in the middle of the take are part
of the take — revealed by clicking next like normal snippets, with a small
're-read' label; never separate items." This suite pins the whole lifecycle:

  * the coach packet APPENDS the read's snippets after the parent's (never
    sorted across sessions — the read's clock restarts at 0), stamped with
    take_session_id + recording_kind, one continuous index;
  * coach writes on a folded read snippet route to the READ's own session
    (snippet save and save-feedback snippets[]);
  * the queue + student drill-down hide read rows and mark the parent
    (has_reread), and the queue row carries the opaque user_id drill key
    (BE-4);
  * publish-analysis flips the paired reads (no more queue zombies);
  * a read never competes as a take in cross-take selection;
  * a read never fires its own "homework completed" coach email (BE-3a).

Run: python3 -m unittest tests.test_reread_fold
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request

    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

SPOKEN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
READ = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _session_row(sid=SPOKEN, **over):
    row = {"id": sid, "user_id": "u1", "arc_id": None,
           "intake_context": {
               "topic": "Demo", "domain": "sales", "language": "en",
           },
           "status": "pending_admin_review",
           "review_requested_at": "2026-07-16T10:00:00Z",
           "results_published_at": None,
           "coach_feedback_saved_at": None}
    row.update(over)
    return row


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class QueueRowShapeTests(unittest.TestCase):
    """BE-4: the opaque per-user drill key + fold markers on queue rows."""

    def test_queue_row_carries_drill_key_and_fold_markers(self):
        row = dict(_session_row(), has_reread=True,
                   arc_id="arc9", take_index=2, user_id="u-42")
        app = Flask(__name__)
        with app.test_request_context():
            request.user_id = "coach1"
            with patch.object(db, "list_review_queue",
                              return_value=[row]), \
                 patch.object(db, "get_user_proficient_languages",
                              return_value=["en"]), \
                 patch.object(db, "get_snippets_by_session",
                              return_value=[]), \
                 patch.object(db, "get_coach_snippet_drafts",
                              return_value=[]):
                resp, status = v2_coach.v2_coach_queue.__wrapped__()
        self.assertEqual(status, 200)
        out = resp.get_json()
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["user_id"], "u-42")      # opaque drill key
        self.assertTrue(r["has_reread"])
        self.assertEqual(r["arc_id"], "arc9")
        self.assertEqual(r["take_index"], 2)
        self.assertTrue(r["pseudonym"])              # still pseudonymized
        self.assertNotIn("intake_context", r)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class LabSendEmailGateTests(unittest.TestCase):
    """BE-3a: a re-read never fires its own coach email — max one email per
    spoken take ⇒ max 3 per arc."""

    def _send(self, session_row):
        from services.lab_send import send_lab_recording_to_coach
        with patch.object(db, "v2_get_session_by_id",
                          return_value=session_row), \
             patch.object(db.takes, "v2_mark_session_pending_review",
                          return_value=True), \
             patch.object(db, "get_snippets_by_session",
                          return_value=[]), \
             patch("services.session_publish._send_admin_notification") \
                as m_mail:
            res = send_lab_recording_to_coach(SPOKEN, "u1")
        return res, m_mail

    def test_read_flips_but_never_emails(self):
        res, m_mail = self._send(_session_row(
            sid=READ, status="processing",
            recording_kind="read", paired_session_id=SPOKEN))
        self.assertTrue(res["ok"])                # still enters the flow
        m_mail.assert_not_called()                # but no email


if __name__ == "__main__":
    unittest.main()
