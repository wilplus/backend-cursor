"""
STORY    As a person in a chat with someone else, I want to block them and to
         report what they sent, so that I stop hearing from someone abusive
         and the founder can act on it; and as the founder, I want every
         report in front of me at once.
OUTCOME
  O1  When I block the other person, what they send from then on never
      reaches me: not in my chat, not as my list's last line, not as a push,
      and not after I unblock either. They are not told: their own chat
      reads as before, their message sent. My chat and my list say I
      blocked them; after Unblock, what they send reaches me again (N466
      item 2).
  O2  When I report them, the chat's last five messages as I see them are
      kept with who reported whom and whether I also blocked; the founder
      gets an email and sees it in the CEO panel's list, and can mark it
      read. Nobody else can read that list, and someone not in the chat can
      neither block nor report it, and writes nothing (N466 item 3).
PROVES   O1 -> ChatSafetyTest::test_a_blocked_persons_messages_never_reach_me_and_they_are_not_told
         O2 -> ChatSafetyTest::test_a_report_keeps_the_last_five_and_reaches_the_founder
WHY      Founder 2026-11-04 (N466): Block and Report in the chats between
         people, for Apple's rule 1.2.
"""
from __future__ import annotations

import os
import unittest
from datetime import timedelta
from unittest.mock import patch

from services.db import db
from tests.test_chats import ME, OTHER, SOMEONE, _Store


class ChatSafetyTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        import routes.admin
        from config import Config
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
        self.store = _Store()
        self.who, self.admin = ME, False
        self.pushes: list = []
        self.emails: list = []

        def tick():
            # One clock for the messages and the blocks, as the database has.
            self.store.clock += timedelta(minutes=1)
            return self.store.clock

        for p in (patch.object(auth, "verify_supabase_token", lambda t: {"sub": self.who}),
                  patch.object(db, "client", self.store),
                  patch.object(routes.admin, "is_admin", lambda _uid: self.admin),
                  patch("services.chat_safety._now", tick),
                  patch("services.push_devices.push_later",
                        lambda _db, user, **kw: self.pushes.append((user, kw["body"]))),
                  patch("services.email_service.send_email_resend",
                        lambda **kw: self.emails.append(kw)),
                  patch.object(Config, "SEND_EMAILS", True, create=True),
                  patch.object(Config, "ADMIN_EMAIL", "founder@example.com", create=True),
                  patch.dict(os.environ, {})):
            p.start()
            self.addCleanup(p.stop)
        thread = self.store.table("chat_threads").insert(
            {"kind": "team", "title": "Ariel"}).execute().data[0]["id"]
        self.store.table("chat_members").insert([
            {"thread_id": thread, "user_id": ME, "display_name": "Artur"},
            {"thread_id": thread, "user_id": SOMEONE, "display_name": "Ariel"}]).execute()
        self.thread = thread

    def _as(self, who, method, path, body=None):
        self.who = who
        return self.client.open(path, method=method, json=body, headers={"Authorization": "Bearer t"})

    def _say(self, who, emoji):
        return self._as(who, "POST", f"/v2/chats/{self.thread}/messages", {"kind": "emoji", "body": emoji})

    def _read(self, who):
        return self._as(who, "GET", f"/v2/chats/{self.thread}/messages").get_json()

    def _listed(self, who):
        return self._as(who, "GET", "/v2/chats").get_json()["chats"][0]

    def test_a_blocked_persons_messages_never_reach_me_and_they_are_not_told(self):
        self._say(SOMEONE, "👍")
        self.assertEqual(self._as(ME, "POST", f"/v2/chats/{self.thread}/block").get_json(), {"blocked": True})

        self.pushes.clear()
        self.assertEqual(self._say(SOMEONE, "👀").status_code, 200)
        self.assertEqual(self.pushes, [])
        mine = self._read(ME)
        self.assertTrue(mine["blocked"])
        self.assertEqual([m["body"] for m in mine["messages"]], ["👍"])
        listed = self._listed(ME)
        self.assertTrue(listed["blocked"])
        self.assertEqual(listed["last"]["body"], "👍")
        theirs = self._read(SOMEONE)
        self.assertFalse(theirs["blocked"])
        self.assertEqual([m["body"] for m in theirs["messages"]], ["👍", "👀"])

        self.assertEqual(self._as(ME, "DELETE", f"/v2/chats/{self.thread}/block").get_json(), {"blocked": False})
        self._say(SOMEONE, "🙏")
        mine = self._read(ME)
        self.assertFalse(mine["blocked"])
        self.assertEqual([m["body"] for m in mine["messages"]], ["👍", "🙏"])
        self.assertEqual(self.pushes, [(ME, "🙏 Thanks")])

    def test_a_report_keeps_the_last_five_and_reaches_the_founder(self):
        for who, emoji in [(SOMEONE, "👍"), (ME, "👀"), (SOMEONE, "🙏"), (ME, "👍"),
                           (SOMEONE, "👀"), (SOMEONE, "🙏")]:
            self._say(who, emoji)
        # Someone not in the chat can neither report nor block it.
        self.assertEqual(self._as(OTHER, "POST", f"/v2/chats/{self.thread}/report", {"block": True}).status_code, 404)
        self.assertEqual(self._as(OTHER, "POST", f"/v2/chats/{self.thread}/block").status_code, 404)
        self.assertEqual(self.store.count("chat_reports"), 0)

        answer = self._as(ME, "POST", f"/v2/chats/{self.thread}/report", {"block": True}).get_json()
        self.assertEqual(answer, {"reported": True, "blocked": True})
        self.assertTrue(self._read(ME)["blocked"])
        self.assertEqual(len(self.emails), 1)
        self.assertEqual(self.emails[0]["to"], "founder@example.com")
        self.assertIn("Artur reported Ariel and blocked them.", self.emails[0]["text"])

        # Only the founder reads the list.
        self.assertEqual(self._as(ME, "GET", "/v2/admin/chat-reports").status_code, 403)
        self.admin = True
        listed = self._as(ME, "GET", "/v2/admin/chat-reports").get_json()["reports"]
        self.assertEqual(len(listed), 1)
        report = listed[0]
        self.assertEqual((report["reporter"], report["reported"], report["blocked"]), ("Artur", "Ariel", True))
        self.assertEqual([(m["author"], m["body"]) for m in report["messages"]],
                         [("Artur", "👀"), ("Ariel", "🙏"), ("Artur", "👍"), ("Ariel", "👀"), ("Ariel", "🙏")])
        self.assertIsNone(report["handled_at"])
        done = self._as(ME, "POST", f"/v2/admin/chat-reports/{report['id']}/handled").get_json()
        self.assertTrue(done["handled_at"])
        self.assertTrue(self._as(ME, "GET", "/v2/admin/chat-reports").get_json()["reports"][0]["handled_at"])


if __name__ == "__main__":
    unittest.main()
