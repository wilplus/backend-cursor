"""The publish-results email is connected again.

It was called from the publish endpoint until b73697f ("feat: make coach
review publishing atomic", 2026-08-24) moved delivery effects into
services/coach_publish_delivery.py and left the email behind. Nothing
failed; it simply stopped sending, and stayed off for five weeks.

Founder 2026-09-24: "You should turn on the email so that they know that
they have it." These tests exist so a fourth refactor cannot drop it
silently a second time.

Run: python3 -m unittest tests.test_publish_emails_the_speaker
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import services.coach_publish_delivery as cpd


class _Db:
    def __init__(self, email="speaker@example.com"):
        self._email = email

    def get_user_email_from_auth(self, user_id):
        return self._email


class MailTheSpeaker(unittest.TestCase):
    def _call(self, db=None, payload=None, **kw):
        with patch("services.arc_notifications._arc_topic",
                   return_value=kw.pop("topic", "Series A narrative")), \
             patch("services.post_session_results_email."
                   "send_publish_results_email") as send:
            send.return_value = kw.pop("result", {"status": "sent"})
            cpd._mail_the_speaker(
                db or _Db(), "user-1", "arc-1", "take-1",
                payload if payload is not None else {"feedback_items": [1, 2, 3]},
            )
        return send

    def test_publishing_sends_the_email(self):
        send = self._call()
        send.assert_called_once()
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["user_email"], "speaker@example.com")
        self.assertEqual(kwargs["snippet_count"], 3)

    def test_it_carries_the_arc_so_the_deep_link_lands(self):
        # Without arc_id the CTA falls back to bare /chat and the speaker is
        # handed a thread to search — the exact thing the founder asked to be
        # fixed on 2026-08-15.
        send = self._call()
        self.assertEqual(send.call_args.kwargs["arc_id"], "arc-1")

    def test_top_theme_is_never_blank(self):
        # The render endpoint refuses an empty topTheme, and the sender would
        # quietly fall back to its degraded inline template instead of the
        # designed one. A project with no topic must still render properly.
        send = self._call(topic=None)
        self.assertTrue(send.call_args.kwargs["top_theme"].strip())

    def test_a_failed_send_never_breaks_the_publish(self):
        # This module is a retrying outbox. A raise here would re-run the whole
        # event — and the bubbles are idempotent but an inbox is not.
        with patch("services.arc_notifications._arc_topic", return_value="t"), \
             patch("services.post_session_results_email."
                   "send_publish_results_email",
                   side_effect=RuntimeError("resend is down")):
            cpd._mail_the_speaker(_Db(), "user-1", "arc-1", "take-1", {})

    def test_no_address_on_file_is_not_an_error(self):
        send = self._call(db=_Db(email=None))
        send.assert_not_called()

    def test_a_guest_with_no_owner_is_skipped(self):
        with patch("services.post_session_results_email."
                   "send_publish_results_email") as send:
            cpd._mail_the_speaker(_Db(), None, "arc-1", "take-1", {})
        send.assert_not_called()

    def test_the_delivery_path_still_calls_it(self):
        # The guard against a fourth refactor: _deliver must reach the mailer.
        import inspect
        self.assertIn("_mail_the_speaker", inspect.getsource(cpd._deliver))


if __name__ == "__main__":
    unittest.main()
