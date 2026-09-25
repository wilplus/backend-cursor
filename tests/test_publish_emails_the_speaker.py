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
from unittest.mock import patch

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


class PublishingFinallySaysSomethingTests(unittest.TestCase):
    """FOUNDER 2026-09-25, decision 02.

    Every card publish could fire was conditional -- a correction, a shared
    video, an album clip, a milestone -- so a publish with none of them left
    the speaker's thread completely silent at the one moment the coach's work
    became visible. The email was carrying that alone.
    """

    def test_publish_fires_one_card_and_it_is_unconditional(self):
        import inspect

        from services import coach_publish_delivery as cpd

        source = inspect.getsource(cpd._deliver)
        self.assertIn("fire_coach_feedback_published(", source)
        # Not nested under a payload condition: the publish itself is the news.
        for line in source.splitlines():
            if "fire_coach_feedback_published(" in line:
                indent = len(line) - len(line.lstrip())
                self.assertEqual(
                    indent, 4,
                    "the publish card must not sit behind a payload flag")

    def test_the_card_carries_the_signed_copy(self):
        from services.arc_notifications import fire_coach_feedback_published
        captured = {}

        class _Db:
            def insert_lounge_messages(self, uid, messages):
                captured["uid"] = uid
                captured["messages"] = messages
                return messages

            def get_arc_by_id(self, _arc_id):
                return None

        self.assertTrue(fire_coach_feedback_published(
            _Db(), "user-1", "arc-1", "rev-9"))
        message = captured["messages"][0]
        # Founder sign-off 2026-09-25.
        self.assertEqual(message["body"], "Your coach's feedback is in.")
        self.assertEqual(message["kind"], "ideal_text")
        self.assertEqual(
            message["metadata"]["variant"], "coach_feedback_published")

    def test_the_same_revision_delivered_twice_is_one_card(self):
        """Publish delivery is a RETRYING outbox: the same event can arrive
        again, and a second card in the thread would be the visible cost."""
        from services.arc_notifications import fire_coach_feedback_published
        keys = []

        class _Db:
            def insert_lounge_messages(self, uid, messages):
                keys.append(messages[0]["client_id"])
                return messages

            def get_arc_by_id(self, _arc_id):
                return None

        fire_coach_feedback_published(_Db(), "user-1", "arc-1", "rev-9")
        fire_coach_feedback_published(_Db(), "user-1", "arc-1", "rev-9")
        self.assertEqual(len(set(keys)), 1, "same revision → same client key")

        fire_coach_feedback_published(_Db(), "user-1", "arc-1", "rev-10")
        self.assertEqual(len(set(keys)), 2, "a new revision announces again")

    def test_nothing_fires_without_a_revision(self):
        from services.arc_notifications import fire_coach_feedback_published

        class _Db:
            def insert_lounge_messages(self, uid, messages):
                raise AssertionError("must not write")

        for missing in (None, "", 0):
            self.assertFalse(fire_coach_feedback_published(
                _Db(), "user-1", "arc-1", missing))


class OneBubblePerPublishTests(unittest.TestCase):
    """FOUNDER 2026-09-25, Q34 B: one chat bubble per publish and nothing
    else. The coach's own Take video is gone from the product; the exercise
    video is the only video."""

    def test_delivery_fires_only_the_feedback_bubble(self):
        import inspect

        from services import coach_publish_delivery as cpd

        source = inspect.getsource(cpd._deliver)
        for gone in ("fire_material_coach_correction", "fire_coach_video_shared",
                     "fire_voice_album_ready", "maybe_fire_best_presentation_ready",
                     "share_video"):
            self.assertNotIn(gone, source)
        self.assertEqual(source.count("fire_"), 2)  # the import and the call

    def test_the_coach_video_card_no_longer_exists(self):
        from services import arc_notifications

        self.assertFalse(hasattr(arc_notifications, "fire_coach_video_shared"))
        self.assertFalse(hasattr(arc_notifications,
                                 "fire_material_coach_correction"))

    def test_the_email_link_opens_the_feedback_sheet(self):
        from services import post_session_results_email as pse

        sent = {}

        def fake_send(**kwargs):
            sent.update(kwargs)
            return {"id": "x"}

        with patch.object(pse.db, "get_email_pref_publish_results",
                          return_value=True), \
             patch.object(pse, "Config") as cfg, \
             patch.object(pse, "build_unsubscribe_url", return_value=None), \
             patch.object(pse, "render_post_session_results_email",
                          side_effect=lambda props: sent.setdefault(
                              "props", props) and {"html": "h", "text": "t"}), \
             patch.object(pse, "send_email_resend", side_effect=fake_send):
            cfg.return_value.SEND_EMAILS = True
            cfg.return_value.PUBLIC_FRONTEND_URL = "https://www.willpowerlab.com"
            cfg.return_value.RESEND_FROM_EMAIL = "hi@willpowerlab.com"
            pse.send_publish_results_email(
                user_id="u", user_email="a@b.c", user_first_name=None,
                snippet_count=2, top_theme="Pitch", session_id="s",
                arc_id="arc-1")
        self.assertEqual(
            sent["props"]["journeyUrl"],
            "https://www.willpowerlab.com/chat?idealArc=arc-1&feedback=1")


class EmailConfigIsVisibleAtBootTests(unittest.TestCase):
    """Founder 2026-09-25: make the Railway settings checkable from a log."""

    def test_the_summary_names_presence_never_values(self):
        from services import post_session_results_email as pse

        with patch.object(pse, "Config") as cfg:
            c = cfg.return_value
            c.SEND_EMAILS = True
            c.RESEND_API_KEY = "re_secret_value"
            c.RESEND_FROM_EMAIL = "hi@willpowerlab.com"
            c.PUBLIC_FRONTEND_URL = "https://www.willpowerlab.com"
            c.FRONTEND_BASE_URL = "https://www.willpowerlab.com"
            c.EMAIL_RENDER_SECRET = "shh"
            c.UNSUBSCRIBE_TOKEN_SECRET = ""
            summary = pse.email_config_summary()
        self.assertNotIn("re_secret_value", str(summary))
        self.assertNotIn("shh", str(summary))
        self.assertTrue(summary["resend_api_key"])
        self.assertFalse(summary["unsubscribe_token_secret"])
        self.assertEqual(summary["public_frontend_url"],
                         "https://www.willpowerlab.com")

    def test_a_localhost_link_is_called_out(self):
        from services import post_session_results_email as pse

        with patch.object(pse, "Config") as cfg:
            cfg.return_value.PUBLIC_FRONTEND_URL = "http://localhost:3000"
            self.assertEqual(pse.email_config_summary()["public_frontend_url"],
                             "localhost")

    def test_the_worker_logs_it_at_boot(self):
        with open("worker.py", encoding="utf-8") as fh:
            self.assertIn("email_config_summary()", fh.read())
