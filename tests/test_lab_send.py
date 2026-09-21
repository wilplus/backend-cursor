"""Unit tests for services.lab_send (willab send-gate §3.4-3.7).

Covers the idempotent send primitive (status flip = success signal,
already-sent no-op, best-effort notify).
DB + notify mocked.

Run: python3 -m unittest tests.test_lab_send
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
             patch.object(db.takes, "v2_mark_session_pending_review",
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
             patch.object(db.takes, "v2_mark_session_pending_review",
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


class ReviewCreditTests(unittest.TestCase):
    """Everyone receives the coach hand-off (founder 2026-09-21).

    The free tier allows zero coach reviews, so the automatic delivery hit
    `coach_cap_reached` on every open, the route answered 500 "please retry",
    and nothing was logged. The price no longer refuses a review; only a
    charge the ledger could not record does.
    """

    def _reserve(self, reason, ok):
        from services import lab_send as mod
        from services.token_account import ChargeResult
        outcome = ChargeResult(ok, 0, 0, reason, "coach_feedback")
        with patch("services.token_account.charge",
                   return_value=outcome) as charge:
            result = mod._reserve_review_credit("u1", "s")
        charge.assert_called_once_with("u1", "coach_feedback", ref_id="s")
        return result

    def test_a_capped_tier_is_still_admitted(self):
        self.assertIsNotNone(self._reserve("coach_cap_reached", False))

    def test_an_empty_balance_is_still_admitted(self):
        self.assertIsNotNone(self._reserve("insufficient", False))

    def test_a_paid_review_is_admitted_as_before(self):
        self.assertIsNotNone(self._reserve("", True))

    def test_an_unrecordable_charge_still_stops_the_hand_off(self):
        for reason in ("account_unavailable", "write_failed", "cas_contention"):
            with self.subTest(reason=reason):
                self.assertIsNone(self._reserve(reason, True))

    def test_every_refusal_names_itself(self):
        from services import lab_send as mod
        with self.assertLogs(mod.logger, level="INFO") as captured:
            self._reserve("coach_cap_reached", False)
            self._reserve("write_failed", True)
        joined = "\n".join(captured.output)
        self.assertIn("admitted past the price", joined)
        self.assertIn("coach_cap_reached", joined)
        self.assertIn("unrecorded", joined)
        self.assertIn("write_failed", joined)


if __name__ == "__main__":
    unittest.main()
