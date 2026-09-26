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


class PublishMovesTheIdealBubbleTests(unittest.TestCase):
    """FOUNDER 2026-09-25 (Q39 B, Q41 A): the feedback bubble is deleted; the
    project's own Ideal Text bubble comes back to the bottom of the chat."""

    def test_publish_bumps_the_bubble_unconditionally(self):
        import inspect

        from services import coach_publish_delivery as cpd

        source = inspect.getsource(cpd._deliver)
        self.assertIn("bump_ideal_bubble(", source)
        self.assertNotIn("fire_coach_feedback_published", source)
        for line in source.splitlines():
            if "bump_ideal_bubble(" in line and "import" not in line:
                indent = len(line) - len(line.lstrip())
                self.assertEqual(indent, 4,
                                 "the bump must not sit behind a payload flag")

    def test_the_feedback_bubble_no_longer_exists(self):
        from services import arc_notifications

        self.assertFalse(hasattr(arc_notifications,
                                 "fire_coach_feedback_published"))

    def test_it_moves_only_a_version_bubble(self):
        from services.arc_notifications import bump_ideal_bubble

        calls = []

        class _Db:
            def bump_latest_lounge_ideal_bubble(self, uid, arc, variants, at):
                calls.append((uid, arc, variants, at))
                return True

        self.assertTrue(bump_ideal_bubble(_Db(), "user-1", "arc-1"))
        uid, arc, variants, at = calls[0]
        self.assertEqual((uid, arc), ("user-1", "arc-1"))
        self.assertEqual(variants, ["ready", "verified"])
        self.assertTrue(at.endswith("+00:00"))

    def test_nothing_moves_without_an_owner_or_a_project(self):
        from services.arc_notifications import bump_ideal_bubble

        class _Db:
            def bump_latest_lounge_ideal_bubble(self, *a):
                raise AssertionError("must not write")

        self.assertFalse(bump_ideal_bubble(_Db(), None, "arc-1"))
        self.assertFalse(bump_ideal_bubble(_Db(), "user-1", ""))

    def test_a_failure_never_breaks_the_publish(self):
        from services.arc_notifications import bump_ideal_bubble

        class _Db:
            def bump_latest_lounge_ideal_bubble(self, *a):
                raise RuntimeError("db down")

        self.assertFalse(bump_ideal_bubble(_Db(), "user-1", "arc-1"))


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
        self.assertEqual(source.count("fire_"), 0)  # no bubble fires at all

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


class FallbackEmailSaysTheSignedWordsTests(unittest.TestCase):
    """Founder 2026-09-25: the fallback send carries the same words."""

    def test_fallback_wording(self):
        from services.post_session_results_email import _render_inline_fallback

        out = _render_inline_fallback({
            "snippetCount": 2, "topTheme": "Series A pitch",
            "journeyUrl": "https://x/chat?idealArc=a&feedback=1",
            "unsubscribeUrl": "https://x/unsubscribe?token=t",
        })
        for text in (out["html"], out["text"]):
            self.assertIn("Your coach's feedback is in.", text.replace("&#x27;", "'"))
            self.assertIn("left feedback on 2 moments.", text)
            self.assertIn("Open the feedback", text)
        self.assertIn("/willab-logo", out["html"])
        self.assertNotIn("Top theme", out["html"])
        self.assertNotIn("View your results", out["html"])
