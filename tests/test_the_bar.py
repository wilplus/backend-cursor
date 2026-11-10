"""
STORY    As someone in a host's chat, I want to type to them where their chat
         takes typing and to add the photo their chat asks for, so that the
         bar's middle is always the one thing to do now (N610).
OUTCOME
  O1  BAR-N610-1. Where my host's chat takes typing, I type to them and
      they type back; the three emoji stay as they are; what I type after
      they block me does not reach them. Where typing is off, typed words
      are refused, mine and the host's, and so they are in a chat that is
      nobody's own chat.
  O2  BAR-N610-2. Typed to the question that waits, my words are its
      answer: one of the host's own questions moves on to their next line
      and my words are on their card; a question a person sent is answered
      with a message that asks nothing back. A message that asks for
      nothing, or a second answer, is refused.
  O3  BAR-N610-3. A question of my recipe can ask for a photo: it takes no
      answers to tap, it is asked in the chat of whoever joins, after my
      own questions, and their read says so on the question that waits; it
      is not one of my first Take's questions. Without the chat builder's
      ring nothing is asked.
  O4  BAR-N610-4. The photo answers the question: it is kept as any photo,
      I (the host) see it and can open it, my next line follows; a file
      that is no photo, a tap, a second photo, or a photo for a question
      that asks for none is refused.
  O5  BAR-N610-5. Only a signed-in member with current processing authority
      adds the photo: a website visitor has no way to before signing up,
      nobody signed out does, and a refused authority writes nothing.
PROVES   O1 -> TheBarTest::test_people_type_only_where_the_hosts_chat_takes_typing
         O2 -> TheBarTest::test_typed_to_the_question_that_waits_my_words_are_its_answer
         O3 -> TheBarTest::test_a_question_of_my_recipe_asks_for_a_photo_and_the_read_says_so
         O4 -> TheBarTest::test_the_photo_answers_the_question_and_the_host_sees_it
         O5 -> TheBarTest::test_only_a_signed_in_member_with_authority_adds_the_photo
WHY      The founder, 10 November 2026 (N610): "if someone has typing on, then
         you can literally type to them thank you"; "A photo asked for: the
         middle is 'Add a photo'".
"""
from __future__ import annotations

import io
import os
import unittest
from unittest.mock import patch

from services.db import db
from services.canonical_product import OwnerPrincipal
from services.processing_authorization import ProcessingAuthorizationService
from services.project_repository import ProjectRepository
from tests.test_chats import _Store

TOMEK = "11111111-1111-4111-8111-111111111111"
ANNA = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
NAMES = {TOMEK: ("Tomek Nowak", "tomek@example.com"), ANNA: ("Anna Lis", "anna@example.com"),
         OTHER: ("Ola Kot", "ola@example.com")}
GATE = "PLF1_PROCESSING_AUTHORIZATION_MODE"
HAIR = "Send me a photo of your hair."
MORNINGS = {"plan": None, "lines": [{"q": "Do you train in the mornings?", "answers": ["No", "Yes"]}]}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _ring(feature, user_id, **_):
    return feature in ("chat_builder", "website_chat") and str(user_id) == TOMEK


class TheBarTest(unittest.TestCase):
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
        self.authority = {"authorized": True, "pooled_learning_eligible": False}

        def payload(_token):
            name, email = NAMES[self.who]
            return {"sub": self.who, "email": email, "user_metadata": {"full_name": name}}

        for p in (patch.object(auth, "verify_supabase_token", payload),
                  patch.object(db, "client", self.store),
                  patch("services.rings.feature_is_on_for_user", _ring),
                  patch.dict(os.environ, {GATE: "off"}),
                  patch.object(ProjectRepository, "owner_for_user",
                               lambda _repo, user: OwnerPrincipal(f"owner-{user}", user, False)),
                  patch.object(ProcessingAuthorizationService, "resolve_acquisition_principal",
                               lambda _service, owner, **_: owner),
                  patch.object(ProcessingAuthorizationService, "status",
                               lambda _service, _principal: dict(self.authority))):
            p.start()
            self.addCleanup(p.stop)
        self.token = self.client.get("/v2/chats/link", headers=self._as(TOMEK)).get_json()["token"]

    def _as(self, who):
        self.who = who
        return {"Authorization": "Bearer t"}

    def _recipe(self, questions=(), **answer_with):
        return self.client.put("/v2/chats/recipe", headers=self._as(TOMEK), json={
            "welcome": ["Hi, I'm Tomek."], "questions": list(questions),
            "answer_with": {"tap": True, "type": True, "record": True, **answer_with}})

    def _join(self, who=ANNA, token=None):
        got = self.client.post(f"/v2/chats/join/{token or self.token}", headers=self._as(who))
        self.assertEqual(got.status_code, 200, got.get_json())
        return got.get_json()["chat"]["id"]

    def _say(self, who, chat, **message):
        return self.client.post(f"/v2/chats/{chat}/messages", json=message, headers=self._as(who))

    def _type(self, who, chat, words, **more):
        return self._say(who, chat, kind="text", body=words, **more)

    def _read(self, who, chat):
        return self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(who)).get_json()["messages"]

    def _photo(self, who, chat, question, data=PNG, kind="image/png", headers=None):
        return self.client.post(
            f"/v2/chats/{chat}/setup/{question}/photo",
            headers=self._as(who) if headers is None else headers,
            data={"file": (io.BytesIO(data), "hair.png", kind)}, content_type="multipart/form-data")

    def test_people_type_only_where_the_hosts_chat_takes_typing(self):
        self._recipe()
        chat = self._join()
        asked = self._type(ANNA, chat, "  What should my first offer cost? ")
        self.assertEqual(asked.status_code, 200, asked.get_json())
        self.assertEqual(asked.get_json()["message"]["body"], "What should my first offer cost?")
        answered = self._type(TOMEK, chat, "Start with what one client would happily pay twice.")
        self.assertEqual(answered.status_code, 200, answered.get_json())
        self.assertEqual(self._type(ANNA, chat, "Thank you, that helps!").status_code, 200)
        self.assertEqual(self._say(ANNA, chat, kind="emoji", body="🙏").get_json()["message"]["meta"],
                         {"label": "thanks"})
        self.assertEqual([m["body"] for m in self._read(TOMEK, chat)][-3:],
                         ["Start with what one client would happily pay twice.",
                          "Thank you, that helps!", "🙏"])
        for nothing in ("   ", "x" * 2001):
            self.assertEqual(self._type(ANNA, chat, nothing).status_code, 400)
        # Blocked, what I type is sent and never reaches them (N466).
        self.client.post(f"/v2/chats/{chat}/block", headers=self._as(TOMEK))
        self.assertEqual(self._type(ANNA, chat, "Are you there?").status_code, 200)
        self.assertNotIn("Are you there?", [m["body"] for m in self._read(TOMEK, chat)])
        self.client.delete(f"/v2/chats/{chat}/block", headers=self._as(TOMEK))
        # Typing off: nobody types there; the emoji stay.
        self._recipe(type=False)
        before = self.store.count("chat_messages")
        for who in (ANNA, TOMEK):
            refused = self._type(who, chat, "Hello?")
            self.assertEqual((refused.status_code, refused.get_json()["code"]), (400, "NOT_ALLOWED"))
        self.assertEqual(self.store.count("chat_messages"), before)
        self.assertEqual(self._say(ANNA, chat, kind="emoji", body="👍").status_code, 200)
        # A chat through the link of someone without the chat builder: as it was.
        ola = self.client.get("/v2/chats/link", headers=self._as(OTHER)).get_json()["token"]
        plain = self._join(ANNA, ola)
        self.assertEqual(self._type(ANNA, plain, "Hello?").status_code, 400)

    def test_typed_to_the_question_that_waits_my_words_are_its_answer(self):
        self._recipe()
        self.client.put("/v2/chats/join-questions", json=MORNINGS, headers=self._as(TOMEK))
        chat = self._join()
        question = self._read(ANNA, chat)[-1]
        self.assertEqual(question["body"], "Do you train in the mornings?")
        got = self._type(ANNA, chat, "Only at weekends", to=question["id"])
        self.assertEqual(got.status_code, 200, got.get_json())
        after = got.get_json()
        self.assertEqual(after["message"]["body"], "Only at weekends")
        self.assertNotIn("question", after["message"]["meta"])
        self.assertEqual([m["body"] for m in after["messages"]][0], "Only at weekends")
        self.assertIn("that's everything", after["messages"][1]["body"])
        card = next(m for m in self._read(TOMEK, chat) if "setup_card" in m["meta"])
        self.assertEqual(card["meta"]["setup_card"]["rows"],
                         [{"k": "Do you train in the mornings", "v": "Only at weekends"}])
        again = self._type(ANNA, chat, "And Fridays", to=question["id"])
        self.assertEqual((again.status_code, again.get_json()["code"]), (409, "ANSWERED"))
        # A question a person sent: the answer names it and asks nothing back.
        mine = self._type(ANNA, chat, "What should my first offer cost?").get_json()["message"]
        self.assertTrue(self._read(TOMEK, chat)[-1]["meta"]["record_answer"])
        answer = self._type(TOMEK, chat, "Start low.", to=mine["id"]).get_json()["message"]
        self.assertEqual(answer["meta"], {"answer_to": mine["id"]})
        # Their answer asks for nothing; my own message is not mine to answer.
        self.assertEqual(self._type(ANNA, chat, "Thanks!", to=answer["id"]).status_code, 400)
        self.assertEqual(self._type(ANNA, chat, "Hm", to=mine["id"]).status_code, 404)

    def test_a_question_of_my_recipe_asks_for_a_photo_and_the_read_says_so(self):
        taps = self._recipe(questions=[{"q": HAIR, "photo": True, "answers": ["Yes"]}])
        self.assertEqual((taps.status_code, taps.get_json()["code"]), (400, "RECIPE_INVALID"))
        kept = self._recipe(questions=[{"q": "What is your talk about?"}, {"q": HAIR, "photo": True}])
        self.assertEqual(kept.status_code, 200, kept.get_json())
        self.assertTrue(kept.get_json()["recipe"]["questions"][1]["photo"])
        self.client.put("/v2/chats/join-questions", json=MORNINGS, headers=self._as(TOMEK))
        chat = self._join()
        first = self._read(ANNA, chat)[-1]
        self.assertEqual(first["body"], "Do you train in the mornings?")
        tapped = self.client.post(f"/v2/chats/{chat}/setup/{first['id']}", json={"picked": ["Yes"]},
                                  headers=self._as(ANNA))
        self.assertEqual(tapped.status_code, 200, tapped.get_json())
        waiting = self._read(ANNA, chat)[-1]
        self.assertEqual((waiting["body"], waiting["mine"]), (HAIR, False))
        self.assertEqual(waiting["meta"]["setup"]["kind"], "photo")
        self.assertEqual(waiting["meta"]["setup"]["answers"], [])
        # I never watch my own question wait (N487 item 7).
        self.assertNotIn(HAIR, [m["body"] for m in self._read(TOMEK, chat)])
        host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(ANNA)).get_json()["host"]
        self.assertEqual([q["q"] for q in host["questions"]], ["What is your talk about?"])
        # Without the ring, my recipe asks nothing.
        with patch("services.rings.feature_is_on_for_user", lambda *a, **k: False):
            other = self._join(OTHER)
        self.assertNotIn(HAIR, [m["body"] for m in self._read(OTHER, other)])

    def test_the_photo_answers_the_question_and_the_host_sees_it(self):
        self._recipe(questions=[{"q": HAIR, "photo": True}])
        self.client.put("/v2/chats/join-questions", json=MORNINGS, headers=self._as(TOMEK))
        chat = self._join()
        tap = self._read(ANNA, chat)[-1]
        # A photo for a question that asks for none.
        self.assertEqual(self._photo(ANNA, chat, tap["id"]).status_code, 404)
        self.client.post(f"/v2/chats/{chat}/setup/{tap['id']}", json={"picked": ["No"]},
                         headers=self._as(ANNA))
        question = self._read(ANNA, chat)[-1]["id"]
        before = self.store.count("chat_messages")
        refused = [self._photo(ANNA, chat, question, data=b"<svg/>", kind="image/svg+xml"),
                   self._photo(ANNA, chat, question, data=b""),
                   self.client.post(f"/v2/chats/{chat}/setup/{question}", json={"picked": ["Yes"]},
                                    headers=self._as(ANNA)),
                   self._type(ANNA, chat, "Here it is", to=question)]
        self.assertEqual([r.status_code for r in refused], [400, 400, 400, 400])
        self.assertEqual(self.store.count("chat_messages"), before)
        got = self._photo(ANNA, chat, question)
        self.assertEqual(got.status_code, 200, got.get_json())
        sent, closing = got.get_json()["messages"]
        self.assertEqual((sent["kind"], sent["mine"]), ("photo", True))
        self.assertIn("that's everything", closing["body"])
        theirs = next(m for m in self._read(TOMEK, chat) if m["kind"] == "photo")
        self.assertEqual((theirs["id"], theirs["kind"], theirs["meta"]["question"]),
                         (sent["id"], "photo", True))
        opened = self.client.get(f"/v2/chats/{chat}/messages/{sent['id']}/file", headers=self._as(TOMEK))
        self.assertEqual((opened.status_code, opened.data), (200, PNG))
        again = self._photo(ANNA, chat, question)
        self.assertEqual((again.status_code, again.get_json()["code"]), (409, "ANSWERED"))
        self.assertEqual(self.store.count("chat_message_files"), 1)

    def test_only_a_signed_in_member_with_authority_adds_the_photo(self):
        self._recipe(questions=[{"q": HAIR, "photo": True}])
        chat = self._join()
        question = self._read(ANNA, chat)[-1]["id"]
        self.assertEqual(self._photo(ANNA, chat, question, headers={}).status_code, 401)
        self.assertEqual(self._photo(OTHER, chat, question).status_code, 404)
        # The gate on, and no authority in force for the caller.
        with patch.dict(os.environ, {GATE: "enforce"}):
            self.authority = {"authorized": False, "code": "PROCESSING_AUTHORIZATION_REQUIRED"}
            res = self._photo(ANNA, chat, question)
            self.assertEqual((res.status_code, res.get_json()["code"]),
                             (403, "PROCESSING_AUTHORIZATION_REQUIRED"))
            self.assertEqual(self.store.count("chat_message_files"), 0)
            self.authority = {"authorized": True, "pooled_learning_eligible": False}
            self.assertEqual(self._photo(ANNA, chat, question).status_code, 200)
        # A website visitor is asked too, and has no way to add it before signing up.
        started = self.client.post(f"/v2/chats/widget/{self.token}/start",
                                   json={"site": "a.com"}).get_json()
        guest = {"X-Willab-Widget-Guest": started["guest"]}
        asked = started["messages"][-1]
        self.assertEqual((asked["body"], asked["meta"]["setup"]["kind"]), (HAIR, "photo"))
        widget = f"/v2/chats/widget/{self.token}/setup/{asked['id']}"
        self.assertEqual(self.client.post(widget, json={"picked": []}, headers=guest).status_code, 400)
        self.assertIn(self.client.post(f"{widget}/photo", headers=guest,
                                       data={"file": (io.BytesIO(PNG), "hair.png", "image/png")},
                                       content_type="multipart/form-data").status_code, (404, 405))
        visitor_chat = self.client.get("/v2/chats", headers=self._as(TOMEK)).get_json()["chats"][0]["id"]
        self.assertEqual(self._photo(None, visitor_chat, asked["id"], headers=guest).status_code, 401)
        self.assertEqual(self.store.count("chat_message_files"), 1)
