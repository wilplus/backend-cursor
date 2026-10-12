"""WhatsApp: the speaker leaves a number, the coach's feedback reaches it
(founder 2026-10-12, "Add Phone Input for WhatsApp Notifications").

Pins the two contracts a speaker would notice:
  * /v2/user/whatsapp saves a valid number in E.164, refuses one without a
    country code (nothing written), reads it back and removes it;
  * a coach's FIRST share of a Take word sends one WhatsApp message to the
    speaker's number; editing an already-shared word sends nothing more.

Run: python3 -m unittest tests.test_whatsapp_number
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from config import Config
from services import coach_take_word as ctw
from services import whatsapp_notify as wn
from services.db import db
from tests.fakes import FakeSupabaseClient, swap_attr

USER = "11111111-1111-4111-8111-111111111111"
TAKE = "22222222-2222-4222-8222-222222222222"
COACH = "33333333-3333-4333-8333-333333333333"


class WhatsAppNumberRouteTest(unittest.TestCase):
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
        self.supabase = FakeSupabaseClient(
            {"user_settings": [{"whatsapp_phone": "+447700900123"}]})
        for p in (patch.object(auth, "verify_supabase_token", lambda t: {"sub": USER}),
                  patch.object(db, "client", self.supabase)):
            p.start()
            self.addCleanup(p.stop)

    def _call(self, method, json=None):
        return self.client.open("/v2/user/whatsapp", method=method, json=json,
                                headers={"Authorization": "Bearer t"})

    def test_a_valid_number_is_saved_in_e164(self):
        res = self._call("PUT", {"phone": "+44 (7700) 900-123"})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json(), {"phone": "+447700900123"})
        saved = self.supabase.tables["user_settings"].payload
        self.assertEqual(saved["user_id"], USER)
        self.assertEqual(saved["whatsapp_phone"], "+447700900123")
        self.assertTrue(saved["whatsapp_opted_in_at"])

    def test_a_number_without_country_code_is_refused(self):
        for bad in ("07700 900123", "+12", "call me", ""):
            res = self._call("PUT", {"phone": bad})
            self.assertEqual(res.status_code, 422, bad)
            self.assertEqual(res.get_json()["code"], "INVALID_INPUT")
        self.assertNotIn("user_settings", self.supabase.tables)

    def test_the_number_reads_back_and_can_be_removed(self):
        self.assertEqual(self._call("GET").get_json(), {"phone": "+447700900123"})
        self.assertEqual(self._call("DELETE").get_json(), {"phone": None})
        self.assertIsNone(self.supabase.tables["user_settings"].payload["whatsapp_phone"])


class _Db:
    """The coach save's database: one Take word row, one speaker number."""

    def __init__(self, existing_shared_at=None):
        self.existing_shared_at = existing_shared_at
        self.client = FakeSupabaseClient(
            {"user_settings": [{"whatsapp_phone": "+447700900123"}]})

    def upsert_coach_take_word(self, *, share, **_kw):
        now = "2026-10-12T10:00:00+00:00"
        shared_at = self.existing_shared_at or (now if share else None)
        return {"take_session_id": TAKE, "coach_id": COACH, "text": "Well done",
                "shared_at": shared_at, "updated_at": now}

    def v2_get_session_by_id(self, _sid):
        return {"user_id": USER, "arc_id": "arc-1"}

    def bump_latest_lounge_ideal_bubble(self, *a):
        return True


class _SyncThread:
    def __init__(self, target, args, **_kw):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class CoachFeedbackMessageTest(unittest.TestCase):
    def setUp(self):
        self.posts = []

        class _Res:
            def raise_for_status(self):
                return None

        def _post(url, json, headers, **_kw):
            self.posts.append((url, json, headers))
            return _Res()

        for p in (patch.object(Config, "WHATSAPP_NOTIFICATIONS", True),
                  patch.object(Config, "WHATSAPP_ACCESS_TOKEN", "tok"),
                  patch.object(Config, "WHATSAPP_PHONE_NUMBER_ID", "1055"),
                  patch.object(Config, "WHATSAPP_TEMPLATE_NAME", "coach_feedback_in"),
                  patch.object(Config, "WHATSAPP_TEMPLATE_LANGUAGE", "en"),
                  patch.object(Config, "WHATSAPP_REDIRECT_TO", ""),
                  patch.object(wn.httpx, "post", _post),
                  patch.object(wn.threading, "Thread", _SyncThread),
                  patch.object(ctw, "_the_pair", lambda *a, **k: None)):
            p.start()
            self.addCleanup(p.stop)

    def _share(self, database):
        ctw.save_take_word(database, take_session_id=TAKE, coach_id=COACH,
                           body={"text": "Well done", "share": True})

    def test_the_first_share_sends_one_whatsapp_message(self):
        self._share(_Db())
        self.assertEqual(len(self.posts), 1)
        url, body, headers = self.posts[0]
        self.assertIn("/1055/messages", url)
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertEqual(body["to"], "447700900123")
        self.assertEqual(body["template"], {"name": "coach_feedback_in",
                                            "language": {"code": "en"}})

    def test_editing_a_shared_word_sends_nothing_more(self):
        self._share(_Db(existing_shared_at="2026-10-11T09:00:00+00:00"))
        self.assertEqual(self.posts, [])

    def test_nothing_is_sent_while_switched_off(self):
        with swap_attr(Config, "WHATSAPP_NOTIFICATIONS", False):
            self._share(_Db())
        self.assertEqual(self.posts, [])


if __name__ == "__main__":
    unittest.main()
