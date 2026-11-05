"""
STORY    As a person in WillpowerLab, I want my chat on my own website, so that
         a customer who taps "Ask {me}" asks me there, I answer here out loud,
         and they hear me there (N530).
OUTCOME
  O1  Before anything is agreed, the widget learns only whose chat it is
      and the three questions a visitor may ask; a wrong or replaced link
      opens nothing, the same answer as the join page's.
  O2  "Agree and start" makes the visitor's own chat with me: in my list it
      is "Widget / Visitor 1" with "From {site}" under it, and it does not
      count toward the day's joins through my link.
  O3  The visitor taps through my join questions (with no closing line
      about "+"), then one question, which reaches me marked for my spoken
      answer; a second question waits until I answer.
  O4  My answer reaches the visitor in the widget, and its voice plays for
      them; nobody without the visitor's secret reads or plays anything.
  O5  "Keep this chat": a signed-in person takes the visitor's seat, and my
      list names the chat after them, "Widget / {name}".
PROVES   O1 -> ChatWidgetTest::test_the_widget_learns_only_whose_chat_it_is
         O2 -> ChatWidgetTest::test_agreeing_makes_a_chat_of_the_visitors_own
         O3 -> ChatWidgetTest::test_the_visitor_taps_my_questions_then_asks_one
         O4 -> ChatWidgetTest::test_my_answer_plays_for_the_visitor_and_no_one_else
         O5 -> ChatWidgetTest::test_keeping_the_chat_names_it_after_them
WHY      The founder's prototype "Your chat, on any website" (5 November
         2026): one link, shared as a link or as a line of code.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from services.db import db
from tests.test_chats import _Store

TOMEK = "11111111-1111-4111-8111-111111111111"
ANNA = "22222222-2222-4222-8222-222222222222"
NAMES = {TOMEK: ("Tomek Nowak", "tomek@example.com"), ANNA: ("Anna Lis", "anna@example.com")}
QUESTIONS = {"plan": None,
             "lines": [{"q": "Which languages can we use?", "answers": ["Polish", "English"], "multi": True}]}


class ChatWidgetTest(unittest.TestCase):
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
        self.store = _Store()
        self.who = TOMEK

        def payload(_token):
            name, email = NAMES[self.who]
            return {"sub": self.who, "email": email, "user_metadata": {"full_name": name}}

        for p in (patch.object(auth, "verify_supabase_token", payload),
                  patch.object(db, "client", self.store),
                  patch.dict(os.environ, {"PLF1_PROCESSING_AUTHORIZATION_MODE": "off"})):
            p.start()
            self.addCleanup(p.stop)
        self.token = self.client.get("/v2/chats/link", headers=self._as(TOMEK)).get_json()["token"]

    def _as(self, who):
        self.who = who
        return {"Authorization": "Bearer t"}

    def _start(self, site="www.invitaheadspa.com"):
        got = self.client.post(f"/v2/chats/widget/{self.token}/start", json={"site": site})
        self.assertEqual(got.status_code, 200, got.get_json())
        return got.get_json()

    def _guest(self, guest):
        return {"X-Willab-Widget-Guest": guest}

    def _my_list(self):
        return self.client.get("/v2/chats", headers=self._as(TOMEK)).get_json()["chats"]

    def test_the_widget_learns_only_whose_chat_it_is(self):
        got = self.client.get(f"/v2/chats/widget/{self.token}")
        self.assertEqual(got.get_json(), {"name": "Tomek", "asks": [
            "What do you do?", "How do you work with people?", "Can we talk?"]})
        self.assertEqual(self.client.get("/v2/chats/widget/not-a-real-token-at-all").status_code, 404)
        self.client.post("/v2/chats/link", headers=self._as(TOMEK))
        self.assertEqual(self.client.get(f"/v2/chats/widget/{self.token}").status_code, 404)

    def test_agreeing_makes_a_chat_of_the_visitors_own(self):
        from services import membership
        started = self._start()
        self.assertEqual(started["name"], "Tomek")
        self.assertTrue(started["guest"])
        row = self._my_list()[0]
        self.assertEqual((row["title"], row["subtitle"]), ("Widget / Visitor 1", "From invitaheadspa.com"))
        self.assertIsNone(self.store.tables["chat_threads"][0].get("link_id"))
        self.assertFalse(membership.link_is_full(db, TOMEK, ANNA))
        self._start(site="not a host")
        self.assertEqual(self._my_list()[0]["title"], "Widget / Visitor 2")

    def test_the_visitor_taps_my_questions_then_asks_one(self):
        self.client.put("/v2/chats/join-questions", json=QUESTIONS, headers=self._as(TOMEK))
        started = self._start()
        guest = self._guest(started["guest"])
        question = started["messages"][-1]
        self.assertEqual(question["body"], "Which languages can we use?")
        tapped = self.client.post(f"/v2/chats/widget/{self.token}/setup/{question['id']}",
                                  json={"picked": ["English"]}, headers=guest)
        self.assertEqual(tapped.status_code, 200, tapped.get_json())
        bodies = [m["body"] for m in tapped.get_json()["messages"]]
        self.assertEqual(bodies[0], "English")
        self.assertNotIn("tap +", " ".join(bodies))
        asked = self.client.post(f"/v2/chats/widget/{self.token}/ask", json={"i": 2}, headers=guest)
        self.assertEqual(asked.status_code, 200, asked.get_json())
        chat = self._my_list()[0]["id"]
        mine = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(TOMEK)).get_json()["messages"]
        self.assertEqual((mine[-1]["body"], mine[-1]["meta"]["record_answer"]), ("Can we talk?", True))
        again = self.client.post(f"/v2/chats/widget/{self.token}/ask", json={"i": 0}, headers=guest)
        self.assertEqual(again.status_code, 409)

    def test_my_answer_plays_for_the_visitor_and_no_one_else(self):
        started = self._start()
        guest = self._guest(started["guest"])
        self.client.post(f"/v2/chats/widget/{self.token}/ask", json={"i": 0}, headers=guest)
        chat = self._my_list()[0]["id"]
        take = "44444444-4444-4444-8444-444444444444"
        self.store.tables.setdefault("recordings", []).append(
            {"id": "r1", "session_v2_id": take, "user_id": TOMEK, "storage_path": "lab/t.webm",
             "duration_ms": 9000})
        # The owner's recording consent is the answer route's own, proven in
        # tests/test_chats.py; here it is given.
        with patch("routes.v2.chats._recording_refused", return_value=None):
            sent = self.client.post(f"/v2/chats/{chat}/answer", json={"take": take, "duration_ms": 9000},
                                    headers=self._as(TOMEK))
        self.assertEqual(sent.status_code, 200, sent.get_json())
        seen = self.client.get(f"/v2/chats/widget/{self.token}/messages", headers=guest).get_json()
        answer = seen["messages"][-1]
        self.assertTrue(answer["meta"]["answer"])
        self.assertNotIn("take", answer["meta"])
        with patch("services.lab_audio_storage.get_lab_audio_bytes", return_value=b"voice"):
            played = self.client.get(f"/v2/chats/widget/{self.token}/messages/{answer['id']}/audio",
                                     headers=guest)
            self.assertEqual(played.data, b"voice")
            stranger = self.client.get(f"/v2/chats/widget/{self.token}/messages/{answer['id']}/audio",
                                       headers=self._guest(started["guest"] + "x"))
            self.assertEqual(stranger.status_code, 404)
        self.assertEqual(self.client.get(f"/v2/chats/widget/{self.token}/messages").status_code, 404)

    def test_keeping_the_chat_names_it_after_them(self):
        started = self._start()
        kept = self.client.post(f"/v2/chats/widget/{self.token}/keep",
                                headers={**self._as(ANNA), **self._guest(started["guest"])})
        self.assertEqual(kept.status_code, 200, kept.get_json())
        self.assertEqual(self._my_list()[0]["title"], "Widget / Anna")
        hers = self.client.get("/v2/chats", headers=self._as(ANNA)).get_json()["chats"]
        self.assertEqual([c["id"] for c in hers], [kept.get_json()["chat"]["id"]])
        own = self.client.post(f"/v2/chats/widget/{self.token}/keep",
                               headers={**self._as(TOMEK), **self._guest(started["guest"])})
        self.assertEqual(own.status_code, 400)


if __name__ == "__main__":
    unittest.main()
