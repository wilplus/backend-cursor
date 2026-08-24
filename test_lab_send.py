"""Unit tests for services.lab_send (willab send-gate §3.4-3.7).

Covers the idempotent send primitive (status flip = success signal,
already-sent no-op, best-effort notify).
DB + notify mocked.

Run: python3 -m unittest test_lab_send
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# services.db pulls in supabase/postgrest, which aren't in the test
# image, so we stub it — in setUpModule, NOT at import time. A stub
# left in sys.modules at import time leaks into sibling test modules:
# test_homework_regressions decides at import time whether the real
# services.db is importable, and a leaked stub makes it run against
# the fake instead of skipping. tearDownModule restores the state.
_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


class SendTests(unittest.TestCase):

    def _send(self, session, *, flip_ok=True, credit_ok=True):
        from services import lab_send as mod
        from services.db import db
        session = {"user_id": "u1", **session}
        with patch.object(db, "v2_get_session_by_id", return_value=session), \
             patch.object(db, "v2_mark_session_pending_review",
                          return_value=({"id": "s"} if flip_ok else None)), \
             patch.object(db, "refund_coach_review_credit",
                          return_value=True) as mock_refund, \
             patch.object(db, "get_snippets_by_session", return_value=[{"id": "a"}]), \
             patch.object(mod, "_reserve_review_credit",
                          return_value=(object() if credit_ok else None)) as mock_charge, \
             patch("services.session_publish._send_admin_notification",
                   return_value="sent") as mock_notify:
            result = mod.send_lab_recording_to_coach("s", "u1")
            return result, mock_notify, mock_charge, mock_refund

    def test_happy_flip_and_notify(self):
        result, notify, charge, refund = self._send(
            {"id": "s", "status": "readout_ready"})
        self.assertTrue(result["ok"])
        self.assertFalse(result["already_sent"])
        self.assertEqual(result["status"], "pending_admin_review")
        charge.assert_called_once_with("u1", "s")
        refund.assert_not_called()
        notify.assert_called_once()

    def test_already_in_queue_is_noop(self):
        result, notify, charge, _ = self._send(
            {"id": "s", "status": "pending_admin_review"})
        self.assertTrue(result["ok"])
        self.assertTrue(result["already_sent"])
        charge.assert_not_called()
        notify.assert_not_called()  # no re-notify on idempotent re-send

    def test_already_published_is_noop(self):
        result, notify, charge, _ = self._send({
            "id": "s", "status": "completed",
            "results_published_at": "2026-06-01T10:00:00Z",
        })
        self.assertTrue(result["already_sent"])
        charge.assert_not_called()
        notify.assert_not_called()

    def test_flip_failure_not_ok(self):
        result, _, charge, refund = self._send(
            {"id": "s", "status": "readout_ready"}, flip_ok=False)
        self.assertFalse(result["ok"])
        self.assertFalse(result["already_sent"])
        charge.assert_called_once()
        refund.assert_called_once_with("u1", "s")

    def test_missing_session(self):
        from services import lab_send as mod
        from services.db import db
        with patch.object(db, "v2_get_session_by_id", return_value=None):
            result = mod.send_lab_recording_to_coach("s", "u1")
        self.assertFalse(result["ok"])

    def test_missing_args(self):
        from services.lab_send import send_lab_recording_to_coach
        self.assertFalse(send_lab_recording_to_coach("", "u1")["ok"])
        self.assertFalse(send_lab_recording_to_coach("s", "")["ok"])

    def test_notify_failure_still_ok(self):
        """Admin email is a nudge — its failure must not fail the send
        (the recording is in the queue; that's success)."""
        from services import lab_send as mod
        from services.db import db
        with patch.object(db, "v2_get_session_by_id",
                          return_value={"id": "s", "user_id": "u1",
                                        "status": "readout_ready"}), \
             patch.object(db, "v2_mark_session_pending_review",
                          return_value={"id": "s"}), \
             patch.object(db, "get_snippets_by_session", return_value=[]), \
             patch.object(mod, "_reserve_review_credit",
                          return_value=object()), \
             patch("services.session_publish._send_admin_notification",
                   side_effect=Exception("smtp down")):
            result = mod.send_lab_recording_to_coach("s", "u1")
        self.assertTrue(result["ok"])

    def test_unclaimed_guest_never_enters_coach_queue(self):
        result, notify, charge, refund = self._send(
            {"id": "s", "user_id": None, "status": "readout_ready"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "owner_required")
        charge.assert_not_called()
        refund.assert_not_called()
        notify.assert_not_called()

    def test_credit_must_be_reserved_before_queue_accepts_take(self):
        result, notify, charge, refund = self._send(
            {"id": "s", "status": "readout_ready"}, credit_ok=False)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "review_credit_unavailable")
        charge.assert_called_once_with("u1", "s")
        refund.assert_not_called()
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
