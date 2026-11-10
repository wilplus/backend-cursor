"""
STORY    As a person in WillpowerLab, I want my own chat on my website, so that
         anyone there can write to me, I answer as in any chat, and they sign
         up after asking to get my answer (N591).
OUTCOME
  O1  Before the visitor writes, with no card in the way, the website chat
      learns only whose chat it is, my welcome and how a visitor may write,
      as my chat's setup says: no fixed questions; a wrong or replaced link,
      or the switch still off (the default), opens nothing, the same answer
      as the join page's.
  O2  The visitor's first message makes their own chat with me: in my list
      it is "Widget / Visitor 1" with "From {site}" under it, like any other
      chat, and it does not count toward the day's joins through my link;
      my welcome and my own questions come first, as for anyone who joins;
      a first message the chat does not take makes nothing.
  O3  The visitor taps my questions, then writes as my setup lets them:
      typed words when I allow typing, refused when I don't; no recording
      without an account.
  O4  I answer as in any chat, recorded or typed; the visitor gets my answer
      only after signing up, and nobody without the visitor's secret reads
      or plays anything.
  O5  Signing up after asking (phone, email, Google): the signed-in person
      takes the visitor's seat, my list names the chat after them, the chat
      is theirs in the app, their questions join their bundles, and the
      widget, in its own tab too, learns where the first notice goes.
  O6  The first answer after the sign-up goes once to the email they signed
      up with, in the signed words.
PROVES   O1 -> ChatWidgetTest::test_the_widget_learns_only_whose_chat_it_is_and_how_to_write
         O2 -> ChatWidgetTest::test_the_first_message_makes_a_chat_in_my_list_like_any_other
         O3 -> ChatWidgetTest::test_the_visitor_taps_my_questions_then_writes_as_my_setup_allows
         O4 -> ChatWidgetTest::test_my_answer_waits_for_the_sign_up_and_no_one_else_reads_it
         O5 -> ChatWidgetTest::test_signing_up_after_asking_makes_the_chat_theirs
         O6 -> ChatWidgetTest::test_the_first_answer_after_the_sign_up_is_noticed_once
WHY      The founder, 9 November 2026 (N591): "There's really no difference
         between the widget and the normal chat. It's just that the chat is
         placed on the public side."
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
TAKE = "44444444-4444-4444-8444-444444444444"


def _ring(feature, user_id, **_):
    return feature in ("chat_builder", "website_chat") and str(user_id) == TOMEK


def _collect_as(collect):
    """``question_bundles.collect`` stood in."""
    return patch("services.question_bundles.collect", collect)


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
                  patch("services.rings.feature_is_on_for_user", _ring),
                  patch.dict(os.environ, {"PLF1_PROCESSING_AUTHORIZATION_MODE": "off"})):
            p.start()
            self.addCleanup(p.stop)
        self.token = self.client.get("/v2/chats/link", headers=self._as(TOMEK)).get_json()["token"]

    def _as(self, who):
        self.who = who
        return {"Authorization": "Bearer t"}

    def _recipe(self, **answer_with):
        got = self.client.put("/v2/chats/recipe", headers=self._as(TOMEK), json={
            "welcome": ["Hi, I'm Tomek. Ask me anything about the spa."],
            "answer_with": {"tap": True, "type": True, "record": True, **answer_with}})
        self.assertEqual(got.status_code, 200, got.get_json())

    def _start(self, site="www.invitaheadspa.com", **first):
        got = self.client.post(f"/v2/chats/widget/{self.token}/start", json={"site": site, **first})
        self.assertEqual(got.status_code, 200, got.get_json())
        return got.get_json()

    def _guest(self, started):
        return {"X-Willab-Widget-Guest": started["guest"]}

    def _write(self, started, words):
        return self.client.post(f"/v2/chats/widget/{self.token}/messages",
                                json={"kind": "text", "body": words}, headers=self._guest(started))

    def _read(self, started):
        return self.client.get(f"/v2/chats/widget/{self.token}/messages",
                               headers=self._guest(started)).get_json()

    def _my_list(self):
        return self.client.get("/v2/chats", headers=self._as(TOMEK)).get_json()["chats"]

    def _sign_up(self, started, who=ANNA):
        return self.client.post(f"/v2/chats/widget/{self.token}/sign-up",
                                headers={**self._as(who), **self._guest(started)})

    def _answer_typed(self, chat, words):
        got = self.client.post(f"/v2/chats/{chat}/messages", json={"kind": "text", "body": words},
                               headers=self._as(TOMEK))
        self.assertEqual(got.status_code, 200, got.get_json())
        return got.get_json()["message"]

    def test_the_widget_learns_only_whose_chat_it_is_and_how_to_write(self):
        self._recipe(type=False)
        got = self.client.get(f"/v2/chats/widget/{self.token}").get_json()
        self.assertEqual(got, {"name": "Tomek", "welcome": ["Hi, I'm Tomek. Ask me anything about the spa."],
                               "writes": {"tap": True, "type": False, "record": False}})
        self.assertNotIn("asks", got)
        self.assertEqual(self.client.get("/v2/chats/widget/not-a-real-token-at-all").status_code, 404)
        with patch("services.rings.feature_is_on_for_user",
                   lambda feature, user_id, **kw: feature != "website_chat" and _ring(feature, user_id)):
            # The switch off (no ring row, the default): nothing opens.
            self.assertEqual(self.client.get(f"/v2/chats/widget/{self.token}").status_code, 404)
            self.assertEqual(self.client.post(f"/v2/chats/widget/{self.token}/start",
                                              json={"site": "a.com"}).status_code, 404)
        self.client.post("/v2/chats/link", headers=self._as(TOMEK))
        self.assertEqual(self.client.get(f"/v2/chats/widget/{self.token}").status_code, 404)

    def test_the_first_message_makes_a_chat_in_my_list_like_any_other(self):
        from services import membership
        self._recipe(type=False)
        refused = self.client.post(f"/v2/chats/widget/{self.token}/start",
                                   json={"site": "a.com", "kind": "text", "body": "Hello?"})
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(self.store.count("chat_threads"), 0)
        self._recipe()
        self.client.put("/v2/chats/join-questions", json=QUESTIONS, headers=self._as(TOMEK))
        started = self._start(kind="text", body="Do you open on Sundays?")
        self.assertEqual([m["body"] for m in started["messages"]],
                         ["Hi, I'm Tomek. Ask me anything about the spa.", "Which languages can we use?",
                          "Do you open on Sundays?"])
        self.assertTrue(started["sign_up"])
        row = self._my_list()[0]
        self.assertEqual((row["title"], row["subtitle"]), ("Widget / Visitor 1", "From invitaheadspa.com"))
        self.assertIsNone(self.store.tables["chat_threads"][0].get("link_id"))
        self.assertFalse(membership.link_is_full(db, TOMEK, ANNA))
        self._start(site="not a host")
        self.assertEqual(self._my_list()[0]["title"], "Widget / Visitor 2")

    def test_the_visitor_taps_my_questions_then_writes_as_my_setup_allows(self):
        self.client.put("/v2/chats/join-questions", json=QUESTIONS, headers=self._as(TOMEK))
        self._recipe()
        started = self._start()
        question = started["messages"][-1]
        tapped = self.client.post(f"/v2/chats/widget/{self.token}/setup/{question['id']}",
                                  json={"picked": ["English"]}, headers=self._guest(started))
        self.assertEqual(tapped.status_code, 200, tapped.get_json())
        self.assertEqual(tapped.get_json()["messages"][0]["body"], "English")
        self.assertFalse(self._read(started)["sign_up"])
        asked = self._write(started, "Do you open on Sundays?")
        self.assertEqual(asked.status_code, 200, asked.get_json())
        self.assertTrue(asked.get_json()["sign_up"])
        self.assertTrue(self._read(started)["sign_up"])
        chat = self._my_list()[0]["id"]
        mine = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(TOMEK)).get_json()["messages"]
        self.assertEqual(mine[-1]["body"], "Do you open on Sundays?")
        # Typed, it is still a question the host answers (N591 item 3).
        self.assertTrue(mine[-1]["meta"]["record_answer"])
        self._recipe(type=False)
        self.assertEqual(self._write(started, "And on Mondays?").status_code, 400)

    def test_my_answer_waits_for_the_sign_up_and_no_one_else_reads_it(self):
        started = self._start()
        self._write(started, "Can we talk?")
        chat = self._my_list()[0]["id"]
        self._answer_typed(chat, "Yes, any day after five.")
        self.store.tables.setdefault("recordings", []).append(
            {"id": "r1", "session_v2_id": TAKE, "user_id": TOMEK, "storage_path": "lab/t.webm",
             "duration_ms": 9000})
        # The host's recording consent is the answer route's own, proven in
        # tests/test_chats.py; here it is given.
        with patch("routes.v2.chats._recording_refused", return_value=None):
            sent = self.client.post(f"/v2/chats/{chat}/answer", json={"take": TAKE, "duration_ms": 9000},
                                    headers=self._as(TOMEK))
        self.assertEqual(sent.status_code, 200, sent.get_json())
        before = self._read(started)
        self.assertTrue(before["answered"])
        self.assertEqual([m["body"] for m in before["messages"]], ["Can we talk?"])
        answer = next(m for m in self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(TOMEK))
                      .get_json()["messages"] if m["meta"].get("answer"))
        audio = f"/v2/chats/widget/{self.token}/messages/{answer['id']}/audio"
        with patch("services.lab_audio_storage.get_lab_audio_bytes", return_value=b"voice"):
            self.assertEqual(self.client.get(audio, headers=self._guest(started)).status_code, 404)
            self._sign_up(started)
            after = self._read(started)
            self.assertFalse(after["answered"])
            self.assertEqual([m["body"] for m in after["messages"]][1], "Yes, any day after five.")
            self.assertTrue(after["messages"][-1]["meta"]["answer"])
            self.assertNotIn("take", after["messages"][-1]["meta"])
            self.assertEqual(self.client.get(audio, headers=self._guest(started)).data, b"voice")
            stranger = self.client.get(audio, headers={"X-Willab-Widget-Guest": started["guest"] + "x"})
            self.assertEqual(stranger.status_code, 404)
        self.assertEqual(self.client.get(f"/v2/chats/widget/{self.token}/messages").status_code, 404)

    def test_signing_up_after_asking_makes_the_chat_theirs(self):
        started = self._start()
        self._write(started, "Do you open on Sundays?")
        bundled = []

        def collect(_db, host, asker, thread, message, words):
            bundled.append((host, asker, words))
        with _collect_as(collect):
            signed = self._sign_up(started)
        self.assertEqual(signed.status_code, 200, signed.get_json())
        self.assertEqual(bundled, [(TOMEK, ANNA, "Do you open on Sundays?")])
        self.assertTrue(signed.get_json()["signed_up"])
        # "Signed up. The first notice of the answer comes to your email." (N595),
        # in the sign-up's answer and in the widget's own read, whose tab did
        # not sign up (it has no token): there, from the account.
        self.assertEqual(signed.get_json()["notice_to"], "email")
        from services import chat_widget
        chat_widget._NOTICE_TO.clear()
        with patch.object(db, "get_user_email_from_auth", lambda _u: None, create=True), \
                patch("services.admin_person.auth_user", lambda _u: {"phone": "48600100200"}):
            self.assertEqual(self._read(started)["notice_to"], "phone")
        self.assertTrue(signed.get_json()["writes"]["record"])
        row = self._my_list()[0]
        self.assertEqual((row["title"], row["subtitle"]), ("Widget / Anna", "From invitaheadspa.com"))
        hers = self.client.get("/v2/chats", headers=self._as(ANNA)).get_json()["chats"]
        self.assertEqual([c["id"] for c in hers], [signed.get_json()["chat"]["id"]])
        self.assertEqual(self._sign_up(started, who=TOMEK).status_code, 400)
        # A visitor who has not signed up: nowhere yet.
        self.assertIsNone(self._read(self._start(kind="emoji", body="👍"))["notice_to"])

    def test_the_first_answer_after_the_sign_up_is_noticed_once(self):
        from services import chat_widget
        started = self._start()
        self._write(started, "Can we talk?")
        self._sign_up(started)
        chat = self._my_list()[0]["id"]
        mails = []
        with patch.object(db, "get_user_email_from_auth", lambda _u: "anna@example.com", create=True), \
                patch("services.email_service.send_email_resend", lambda **kw: mails.append(kw)), \
                patch("config.Config.SEND_EMAILS", True):
            self._answer_typed(chat, "Yes.")
            self._answer_typed(chat, "Any day after five.")
            self.assertEqual(chat_widget.first_notice(db, chat, "x", "y", ANNA, "Tomek"),
                             "not_a_signed_up_visitor")
        self.assertEqual([m["to"] for m in mails], ["anna@example.com"])
        self.assertEqual(mails[0]["subject"], "Tomek answered your question.")
        self.assertTrue(mails[0]["text"].startswith("Tomek answered your question. Open it in WillpowerLab."))


if __name__ == "__main__":
    unittest.main()
