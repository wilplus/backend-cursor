"""
STORY    As someone who teaches models, I want to see that models which
         learn from images, video and recordings are coming, and to tell
         the founder with one tap that I want one (N642 item 6, N643 item 4,
         N645).
OUTCOME
  O1  GET /v2/models/coming lists images, video and recordings, each with
      its title and whether this person asked; only for the ring
      chat_builder or ai_models.
  O2  POST /v2/models/coming/<kind>/want sends the founder one mail and
      keeps the ask on the account; again, nothing more; a mail that cannot
      go is logged and the answer is the same; nothing is counted.
PROVES   O1 -> ModelsComingTest::test_three_kinds_are_coming_for_the_ring
         O2 -> ModelsComingTest::test_i_want_this_tells_the_founder_once
         O2 -> ModelsComingTest::test_the_ask_is_answered_when_the_mail_cannot_go
WHY      The vote of N641 item 3, for the models tab; kept in the account's
         user_metadata (services/model_coming.py), which goes with the account.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

H = {"Authorization": "Bearer t"}
ME = "11111111-1111-1111-1111-111111111111"


class ModelsComingTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.rate_limits import limiter
        register_domains()
        if hasattr(limiter, "initialized"):
            self.addCleanup(setattr, limiter, "initialized", limiter.initialized)
            limiter.initialized = False
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.meta: dict = {}
        self.rings = {"chat_builder"}

        def save(_user, values):
            self.meta.update(values)
        payload = {"sub": ME, "email": "ola@example.com", "user_metadata": {"full_name": "Ola Nowak"}}
        for p in (patch.object(auth, "verify_supabase_token", lambda _t: payload),
                  patch("services.rings.feature_is_on_for_user",
                        lambda feature, _user, database=None: feature in self.rings),
                  patch("services.admin_person.auth_user", lambda _u: {"user_metadata": dict(self.meta)}),
                  patch("services.admin_person.set_metadata", save)):
            p.start()
            self.addCleanup(p.stop)

    def _coming(self):
        return self.client.get("/v2/models/coming", headers=H)

    def _want(self, kind):
        return self.client.post(f"/v2/models/coming/{kind}/want", headers=H)

    def test_three_kinds_are_coming_for_the_ring(self):
        self.assertEqual(self._coming().get_json(), {"coming": [
            {"kind": "images", "title": "Images", "wanted": False},
            {"kind": "video", "title": "Video", "wanted": False},
            {"kind": "recordings", "title": "Recordings", "wanted": False}]})
        self.rings = {"ai_models"}
        self.assertEqual(self._coming().status_code, 200)
        self.rings = set()
        self.assertEqual(self._coming().status_code, 404)
        self.assertEqual(self._want("images").status_code, 404)

    def test_i_want_this_tells_the_founder_once(self):
        from config import Config
        with patch("services.email_service.send_email_resend") as mail:
            self.assertEqual(self._want("recordings").get_json(), {"wanted": True})
            self.assertEqual(self._want("recordings").get_json(), {"wanted": True})
            self.assertEqual(self._want("photos").status_code, 404)
        self.assertEqual(mail.call_count, 1)
        sent = mail.call_args.kwargs
        self.assertEqual(sent["to"], Config().ADMIN_EMAIL)
        self.assertIn("Ola Nowak", sent["text"])
        self.assertIn(ME, sent["text"])
        self.assertIn("recordings", sent["text"])
        self.assertEqual([c["kind"] for c in self._coming().get_json()["coming"] if c["wanted"]], ["recordings"])
        self.assertEqual(set(self.meta["models_wanted"]), {"recordings"})

    def test_the_ask_is_answered_when_the_mail_cannot_go(self):
        with patch("services.email_service.send_email_resend", side_effect=RuntimeError("RESEND_API_KEY")), \
                self.assertLogs("services.model_coming", "WARNING"):
            res = self._want("video")
        self.assertEqual((res.status_code, res.get_json()), (200, {"wanted": True}))
        self.assertIn("video", self.meta["models_wanted"])


if __name__ == "__main__":
    unittest.main()
