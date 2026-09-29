"""The coach hand-off's authorization, permit evidence and unwinding, pinned.

`tests/test_lab_send.py` covers the queue flip, idempotency and the review
credit. These cases pin the rest of the hand-off by behaviour:

* a refused Phase-1 authorization stops the Take before any charge or flip;
* a delivered Take records its permit as started, then completed;
* a failed flip records the permit as failed and refunds the credit;
* a re-read never sends its own admin email;
* a non-owner is refused before anything else is read or written.
"""
from __future__ import annotations

import logging
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from services.processing_authorization import ProcessingAuthorizationError

_ORIG_SERVICES_DB = None


def setUpModule():
    # Same isolation as tests/test_lab_send.py: stub services.db for this
    # module only, and put the original back afterwards.
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()  # type: ignore[attr-defined]
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


class _Authorization:
    def __init__(self, _db, *, refuse=None):
        self.refuse = refuse
        self.events: list[tuple] = []

    def resolve_acquisition_principal(self, owner, *, user_id=None,
                                      recording_id=None):
        if self.refuse:
            raise self.refuse
        return "principal-1"

    def record_provider_event(self, permit_id, event, **kwargs):
        self.events.append((permit_id, event, kwargs))


class _Adapter:
    def __init__(self, _db, coordinates, *, authorization):
        self.coordinates = coordinates
        self.authorization = authorization
        self.keys: list[str] = []

    def authorize_operation(self, kind, *, manifest, idempotency_key):
        self.keys.append(idempotency_key)
        assert kind == "coach_delivery"
        assert manifest == {"content": ["coach_packet"],
                            "purpose": "coach_review"}
        return {"permit_id": "permit-1"}


class _Lines(logging.Handler):
    """Collects formatted lines; unlike assertLogs, zero lines is fine."""

    def __init__(self):
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(record.getMessage())


class HandOffTests(unittest.TestCase):

    def _send(self, session, *, refuse=None, flip=True, refund=True):
        from services import lab_send as mod
        from services.db import db
        db.reset_mock()
        authorization = _Authorization(None, refuse=refuse)
        adapters: list[_Adapter] = []

        def adapter(*args, **kwargs):
            adapters.append(_Adapter(*args, **kwargs))
            return adapters[-1]

        session = {"id": "s", "user_id": "u1", "status": "readout_ready",
                   **session}
        refund_effect = None if refund else RuntimeError("refund down")
        with patch.object(db, "v2_get_session_by_id", return_value=session), \
             patch.object(db.takes, "v2_mark_session_pending_review",
                          return_value=({"id": "s"} if flip else None)) as flipped, \
             patch.object(db, "refund_coach_review_credit",
                          side_effect=refund_effect) as refunded, \
             patch.object(db, "get_snippets_by_session", return_value=[]), \
             patch.object(mod, "_reserve_review_credit",
                          return_value=object()) as charged, \
             patch("services.processing_authorization."
                   "ProcessingAuthorizationService",
                   return_value=authorization), \
             patch("services.authorized_provider.AuthorizedProviderAdapter",
                   side_effect=adapter), \
             patch("services.session_publish._send_admin_notification",
                   return_value="sent") as notified:
            lines = _Lines()
            logger = logging.getLogger("services.lab_send")
            previous = logger.level
            logger.addHandler(lines)
            logger.setLevel(logging.INFO)
            try:
                result = mod.send_lab_recording_to_coach("s", "u1")
            finally:
                logger.removeHandler(lines)
                logger.setLevel(previous)
        return {
            "result": result, "events": authorization.events,
            "adapters": adapters, "flipped": flipped, "refunded": refunded,
            "charged": charged, "notified": notified, "logs": lines.lines,
        }

    def test_a_refused_authorization_stops_before_any_charge_or_flip(self):
        run = self._send({}, refuse=ProcessingAuthorizationError(
            "NO_RECEIPT", "no receipt"))
        self.assertEqual(run["result"], {
            "ok": False, "already_sent": False, "status": "readout_ready",
            "reason": "processing_authorization_required",
            "code": "NO_RECEIPT",
        })
        run["charged"].assert_not_called()
        run["flipped"].assert_not_called()
        self.assertEqual(run["events"], [])
        self.assertEqual(run["logs"], [])

    def test_a_delivered_take_records_its_permit_started_then_completed(self):
        run = self._send({"recording_id": "rec-1"})
        self.assertTrue(run["result"]["ok"])
        self.assertEqual(run["result"]["coach_review_status"], "queued")
        self.assertEqual(run["events"], [
            ("permit-1", "started", {}),
            ("permit-1", "completed",
             {"metadata": {"result_kind": "coach_queue"}}),
        ])
        (adapter,) = run["adapters"]
        self.assertTrue(adapter.keys[0].startswith("coach-delivery:s:"))
        self.assertEqual(adapter.coordinates.take_id, "s")
        self.assertEqual(adapter.coordinates.recording_id, "rec-1")
        run["notified"].assert_called_once_with(
            session_id="s", user_id="u1", snippet_count=0)

    def test_a_failed_flip_fails_the_permit_and_refunds(self):
        run = self._send({}, flip=False)
        self.assertEqual(run["result"]["reason"], "queue_write_failed")
        self.assertEqual(run["events"], [
            ("permit-1", "started", {}),
            ("permit-1", "failed",
             {"error_code": "COACH_QUEUE_WRITE_FAILED"}),
        ])
        run["refunded"].assert_called_once_with("u1", "s")
        run["notified"].assert_not_called()
        self.assertTrue(any("hand-off not queued sid=s user=u1" in line
                            for line in run["logs"]))

    def test_a_refund_that_fails_is_logged_as_deferred(self):
        run = self._send({}, flip=False, refund=False)
        self.assertEqual(run["result"]["reason"], "queue_write_failed")
        self.assertTrue(any(
            "queue failed and refund deferred sid=s err=refund down" in line
            for line in run["logs"]))

    def test_a_re_read_is_queued_without_its_own_admin_email(self):
        run = self._send({"paired_session_id": "parent"})
        self.assertTrue(run["result"]["ok"])
        run["notified"].assert_not_called()
        self.assertTrue(any("admin email skipped (folds into take parent)"
                            in line for line in run["logs"]))

    def test_a_non_owner_is_refused_before_anything_else(self):
        run = self._send({"user_id": "someone-else",
                          "coach_review_status": "draft"})
        self.assertEqual(run["result"], {
            "ok": False, "already_sent": False, "status": "draft",
            "reason": "owner_required",
        })
        self.assertEqual(run["adapters"], [])
        run["charged"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
