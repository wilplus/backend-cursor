"""Fix-pack BE-3 b+c — per-user email threading/consolidation.

Covers:
  - services/email_threading.py header builders (values, guest fallback)
  - services/coach_pseudonym.py determinism + parity with the routes copy
    (parity class imports routes/v2_routes — skips locally without Flask,
    runs in CI)
  - send_lesson_complete_to_admin: stable "Homework — {pseudonym}" subject
    (NO session id), per-student References/In-Reply-To, guest (user_id
    None) sends unthreaded without crashing, never raises on send failure
  - send_publish_results_email: stable subject, per-user thread headers,
    List-Unsubscribe preserved alongside them
  - send_audit_ready_email: per-user thread headers (+ the config-module
    AttributeError bugfix — the send now actually goes out)
  - user_audit.send_user_audit_email: stable subject + thread headers
  - send_email_resend forwards the threading headers verbatim
  - dead EmailService methods removed

Run: python3 -m unittest test_email_threading
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# services.db pulls in supabase; email modules pull in resend / sentry_sdk /
# httpx — none of which are in the local test image. Stub in setUpModule
# (never at import time) and RESTORE the saved originals in tearDownModule
# (willab test-stub-isolation convention: a bare pop corrupts sibling
# modules). resend/sentry_sdk/httpx are stubbed only when missing so CI
# keeps the real packages.
_ORIG_SERVICES_DB = None
_OPTIONAL_STUBS = ("resend", "sentry_sdk", "httpx")
_ORIG_OPTIONAL: dict[str, object] = {}
_ADDED_OPTIONAL: list[str] = []


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub

    for name in _OPTIONAL_STUBS:
        try:
            __import__(name)
        except ImportError:
            _ORIG_OPTIONAL[name] = sys.modules.get(name)
            mod = types.ModuleType(name)
            if name == "resend":
                mod.Emails = MagicMock()
            if name == "sentry_sdk":
                mod.capture_exception = lambda *a, **k: None
            sys.modules[name] = mod
            _ADDED_OPTIONAL.append(name)


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)
    for name in _ADDED_OPTIONAL:
        orig = _ORIG_OPTIONAL.get(name)
        if orig is not None:
            sys.modules[name] = orig
        else:
            sys.modules.pop(name, None)


UID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class ThreadHeaderTests(unittest.TestCase):

    def test_student_headers_value(self):
        from services.email_threading import student_thread_headers
        h = student_thread_headers("u-123")
        ref = "<willab-student-u-123@willpowerlab.com>"
        self.assertEqual(h, {"References": ref, "In-Reply-To": ref})

    def test_user_headers_value(self):
        from services.email_threading import user_thread_headers
        h = user_thread_headers("u-123")
        ref = "<willab-user-u-123@willpowerlab.com>"
        self.assertEqual(h, {"References": ref, "In-Reply-To": ref})

    def test_guest_falls_back_to_empty(self):
        from services.email_threading import (
            student_thread_headers, user_thread_headers,
        )
        for bad in (None, ""):
            self.assertEqual(student_thread_headers(bad), {})
            self.assertEqual(user_thread_headers(bad), {})

    def test_student_and_user_roots_are_distinct(self):
        """Coach inbox and student inbox must not share one thread root."""
        from services.email_threading import (
            student_thread_headers, user_thread_headers,
        )
        self.assertNotEqual(
            student_thread_headers("u-1")["References"],
            user_thread_headers("u-1")["References"],
        )


class CoachPseudonymTests(unittest.TestCase):

    def test_deterministic_and_well_formed(self):
        from services.coach_pseudonym import (
            coach_pseudonym, _COACH_PSEUDONYM_ADJ, _COACH_PSEUDONYM_ANIMAL,
        )
        a = coach_pseudonym(UID)
        self.assertEqual(a, coach_pseudonym(UID))  # stable
        adj, animal = a.split(" ")
        self.assertIn(adj, _COACH_PSEUDONYM_ADJ)
        self.assertIn(animal, _COACH_PSEUDONYM_ANIMAL)

    def test_falsy_user_is_anonymous(self):
        from services.coach_pseudonym import coach_pseudonym
        self.assertEqual(coach_pseudonym(None), "Anonymous")
        self.assertEqual(coach_pseudonym(""), "Anonymous")


class LessonCompleteToAdminTests(unittest.TestCase):
    """BE-3b — the coach 'homework completed' mail."""

    def _send(self, *, user_id, student_email="s@x.com", session_id="sess-abcdef12"):
        from services import email_service as mod
        with patch.object(mod, "send_email_resend") as mock_send, \
             patch.object(mod.config, "SEND_EMAILS", True), \
             patch.object(mod.config, "ADMIN_EMAIL", "coach@x.com"), \
             patch.object(mod.email_service, "api_key_set", True):
            result = mod.email_service.send_lesson_complete_to_admin(
                user_id=user_id,
                session_id=session_id,
                report_preview="spoke clearly",
                student_email=student_email,
                score=None,
                student_name="Sam",
            )
        return result, mock_send

    def test_stable_subject_no_session_id(self):
        from services.coach_pseudonym import coach_pseudonym
        result, mock_send = self._send(user_id=UID)
        self.assertEqual(result["status"], "sent")
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["subject"], f"Homework — {coach_pseudonym(UID)}")
        self.assertNotIn("sess", kwargs["subject"].lower())
        self.assertNotIn("abcdef12", kwargs["subject"])
        # Same user, different session → SAME subject (this is the thread).
        _, mock_send2 = self._send(user_id=UID, session_id="sess-99999999")
        self.assertEqual(mock_send2.call_args.kwargs["subject"], kwargs["subject"])

    def test_per_student_thread_headers(self):
        _, mock_send = self._send(user_id=UID)
        headers = mock_send.call_args.kwargs["headers"]
        ref = f"<willab-student-{UID}@willpowerlab.com>"
        self.assertEqual(headers["References"], ref)
        self.assertEqual(headers["In-Reply-To"], ref)
        self.assertEqual(mock_send.call_args.kwargs["to"], "coach@x.com")

    def test_guest_send_unthreaded_and_no_crash(self):
        result, mock_send = self._send(user_id=None, student_email=None)
        self.assertEqual(result["status"], "sent")
        kwargs = mock_send.call_args.kwargs
        self.assertIsNone(kwargs["headers"])  # no References for guests
        self.assertEqual(kwargs["subject"], "Homework — Anonymous")

    def test_send_failure_never_raises(self):
        from services import email_service as mod
        with patch.object(mod, "send_email_resend",
                          side_effect=Exception("resend down")), \
             patch.object(mod.config, "SEND_EMAILS", True), \
             patch.object(mod.config, "ADMIN_EMAIL", "coach@x.com"), \
             patch.object(mod.email_service, "api_key_set", True):
            result = mod.email_service.send_lesson_complete_to_admin(
                user_id=UID, session_id="s1",
            )
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["sent"])


class PublishResultsEmailTests(unittest.TestCase):
    """BE-3c — the user-bound publish-results mail."""

    def _send(self, *, user_id="u-9"):
        from config import Config
        from services import post_session_results_email as mod
        stub_db = MagicMock()
        stub_db.get_email_pref_publish_results.return_value = True
        with patch.object(mod, "db", stub_db), \
             patch.object(Config, "SEND_EMAILS", True), \
             patch.object(Config, "PUBLIC_FRONTEND_URL", "https://app.x.com"), \
             patch.object(mod, "build_unsubscribe_url",
                          return_value="https://app.x.com/unsubscribe?token=tok"), \
             patch.object(mod, "render_post_session_results_email",
                          return_value={"html": "<p>hi</p>", "text": "hi"}), \
             patch.object(mod, "send_email_resend",
                          return_value={"status": "sent", "sent": True}) as mock_send:
            result = mod.send_publish_results_email(
                user_id=user_id,
                user_email="student@x.com",
                user_first_name="Al",
                snippet_count=4,
                top_theme="clarity",
                session_id="sess-1",
            )
        return result, mock_send

    def test_stable_subject(self):
        result, mock_send = self._send()
        self.assertEqual(result["status"], "sent")
        subject = mock_send.call_args.kwargs["subject"]
        self.assertEqual(subject, "Your feedback from WillpowerLab")
        # No per-send variance: no counts, no session ids.
        self.assertNotIn("4", subject)
        self.assertNotIn("sess", subject.lower())

    def test_thread_headers_and_list_unsubscribe_preserved(self):
        _, mock_send = self._send(user_id="u-9")
        headers = mock_send.call_args.kwargs["headers"]
        ref = "<willab-user-u-9@willpowerlab.com>"
        self.assertEqual(headers["References"], ref)
        self.assertEqual(headers["In-Reply-To"], ref)
        # RFC 8058 pair kept exactly as before, alongside threading.
        self.assertEqual(
            headers["List-Unsubscribe"],
            "<https://app.x.com/unsubscribe?token=tok>",
        )
        self.assertEqual(
            headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click",
        )


class AuditReadyEmailTests(unittest.TestCase):
    """BE-3c — audit-ready mail. Also pins the config-module bugfix:
    before, ``config.PUBLIC_FRONTEND_URL`` raised AttributeError (class
    attribute read off the module) and every send returned False."""

    def test_headers_and_send(self):
        from config import Config
        from services import audit_email as mod
        with patch("services.email_service.send_email_resend",
                   return_value={"status": "sent", "sent": True}) as mock_send, \
             patch.object(Config, "SEND_EMAILS", True), \
             patch.object(Config, "PUBLIC_FRONTEND_URL", "https://app.x.com"), \
             patch.object(Config, "RESEND_FROM_EMAIL", "Artur <hello@x.com>"):
            ok = mod.send_audit_ready_email("u-9", user_email="student@x.com")
        self.assertTrue(ok)
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs["subject"], "Your audit is ready")
        ref = "<willab-user-u-9@willpowerlab.com>"
        self.assertEqual(kwargs["headers"]["References"], ref)
        self.assertEqual(kwargs["headers"]["In-Reply-To"], ref)
        # Branded-from preserved.
        self.assertEqual(kwargs["from_addr"], "WillpowerLab <hello@x.com>")

    def test_never_raises_on_failure(self):
        from services import audit_email as mod
        with patch("services.email_service.send_email_resend",
                   side_effect=Exception("boom")):
            ok = mod.send_audit_ready_email("u-9", user_email="student@x.com")
        self.assertFalse(ok)


class UserAuditSendTests(unittest.TestCase):
    """BE-3c — strong-sides audit send helper (threaded)."""

    def test_stable_subject_and_headers(self):
        from services import user_audit as mod
        audit = {"strong_sides": [], "sessions": []}
        with patch("services.email_service.send_email_resend",
                   return_value={"status": "sent", "sent": True}) as mock_send:
            res = mod.send_user_audit_email("u-7", to_email="student@x.com", audit=audit)
        self.assertEqual(res["status"], "sent")
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(
            kwargs["subject"], "Your WillpowerLab audit — your strong sides so far",
        )
        ref = "<willab-user-u-7@willpowerlab.com>"
        self.assertEqual(kwargs["headers"]["References"], ref)
        self.assertEqual(kwargs["headers"]["In-Reply-To"], ref)
        self.assertEqual(kwargs["to"], "student@x.com")


class SendEmailResendHeaderPassthroughTests(unittest.TestCase):
    """The only headers-capable sender must forward threading headers
    verbatim to the Resend payload."""

    def test_headers_forwarded_verbatim(self):
        from services import email_service as mod
        captured = {}

        def _fake_send(params):
            captured.update(params)
            return {"id": "email-1"}

        with patch.object(mod.config, "SEND_EMAILS", True), \
             patch.object(mod.config, "RESEND_API_KEY", "k"), \
             patch.object(mod.config, "RESEND_FROM_EMAIL", "w@x.com"), \
             patch.object(mod.resend.Emails, "send", side_effect=_fake_send):
            mod.send_email_resend(
                to="coach@x.com",
                subject="Homework — Playful Octopus",
                html="<p>hi</p>",
                headers={
                    "References": "<willab-student-u-1@willpowerlab.com>",
                    "In-Reply-To": "<willab-student-u-1@willpowerlab.com>",
                },
            )
        self.assertEqual(
            captured["headers"],
            {
                "References": "<willab-student-u-1@willpowerlab.com>",
                "In-Reply-To": "<willab-student-u-1@willpowerlab.com>",
            },
        )


class DeadMethodsGoneTests(unittest.TestCase):
    """Cleanup: the three caller-free EmailService methods are deleted."""

    def test_dead_methods_removed(self):
        from services.email_service import EmailService
        self.assertFalse(hasattr(EmailService, "send_admin_notification"))
        self.assertFalse(hasattr(EmailService, "send_assignment_to_student"))
        self.assertFalse(hasattr(EmailService, "send_lesson_complete_to_student"))
        # The live one stays.
        self.assertTrue(hasattr(EmailService, "send_lesson_complete_to_admin"))


# ── pseudonym parity with the routes copy (skip locally without flask; run
# in CI). The services copy MUST stay byte-identical in behaviour to
# routes/v2_routes.py::_coach_pseudonym — the coach recognises a student by
# the same handle across queue, overlay and mailbox. ──
try:
    from routes import v2_routes as _v2
    _RT_ERR = None
except Exception as e:  # pragma: no cover
    _v2 = None
    _RT_ERR = e


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class PseudonymParityTests(unittest.TestCase):

    def test_parity_with_routes_impl(self):
        from services.coach_pseudonym import coach_pseudonym
        samples = [
            UID,
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "00000000-0000-4000-8000-000000000001",
            "u-plain-string",
            123456,
        ]
        for uid in samples:
            self.assertEqual(
                coach_pseudonym(uid), _v2._coach_pseudonym(uid),
                f"pseudonym drift for {uid!r} — the two copies MUST match",
            )

    def test_parity_on_falsy(self):
        from services.coach_pseudonym import coach_pseudonym
        for bad in (None, ""):
            self.assertEqual(coach_pseudonym(bad), _v2._coach_pseudonym(bad))


if __name__ == "__main__":
    unittest.main()
