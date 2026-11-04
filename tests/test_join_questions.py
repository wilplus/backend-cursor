"""
STORY    As a person who shares what I know, I want everyone who joins through
         my link to answer a few practical questions by tapping, so that we
         start our knowledge base knowing the deadline and the language, and I
         read their answers on one card, not my own questions waiting (N487,
         words signed in N491, N496 and N502).
OUTCOME
  O1  My questions are kept and read back; a question without two to six
      answers is refused; an empty set means none.
  O2  Someone who joins me finds my first lines in our chat, as my
      messages, and is told a few questions come first; in my own view of
      the chat I see neither the questions nor their taps, only that they
      joined through my link.
  O3  They answer by tapping: "No" to "Are you in a hurry?" puts the
      deadline one step of my plan away and moves on; a question that takes
      more than one answer takes several; then my closing line; I see one
      card with the deadline and the languages.
  O4  A tap that is not one of the answers, two answers to a one-answer
      question, a second answer, or my tapping my own question is refused.
  O5  Joining someone with no questions posts nothing, and the line at the
      top says nothing about questions.
  O6  A question I type is kept only when it is practical and has answers
      to tap: Will gives a yes-or-no question its answers, and leaves out a
      question about the work itself and one he finds no answers for.
PROVES   O1 -> JoinQuestionsTest::test_my_questions_are_kept_and_checked
         O2 -> JoinQuestionsTest::test_whoever_joins_finds_my_first_lines_and_i_do_not
         O3 -> JoinQuestionsTest::test_they_answer_by_tapping_and_i_read_one_card
         O4 -> JoinQuestionsTest::test_a_tap_that_is_not_an_answer_is_refused
         O5 -> JoinQuestionsTest::test_joining_someone_with_no_questions_posts_nothing
         O6 -> ReadyTest::test_a_typed_question_is_kept_only_when_practical_with_answers
WHY      The founder, 4 November 2026, on the prototype "Asked When They
         Join": "in the user set up, we need to ask you the questions on what
         questions should be asked to the people that will ask you for the
         knowledge"; "they can only click through the answers they can not
         type".
"""
from __future__ import annotations

import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from services import join_questions as J
from services import plan as P
from services.db import db
from tests.test_chats import _Store

TOMEK = "11111111-1111-4111-8111-111111111111"
PIOTR = "22222222-2222-4222-8222-222222222222"
NAMES = {TOMEK: ("Tomek Nowak", "tomek@example.com"), PIOTR: ("Piotr Kowalski", "piotr@example.com")}
SET = {"plan": "month",
       "lines": [{"q": "Which languages can we use?", "answers": ["Polish", "English"], "multi": True}]}


class JoinQuestionsTest(unittest.TestCase):
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

    def _as(self, who):
        self.who = who
        return {"Authorization": "Bearer t"}

    def _set(self, who, body):
        return self.client.put("/v2/chats/join-questions", json=body, headers=self._as(who))

    def _join(self, owner, joiner):
        token = self.client.get("/v2/chats/link", headers=self._as(owner)).get_json()["token"]
        return self.client.post(f"/v2/chats/join/{token}", headers=self._as(joiner)).get_json()["chat"]["id"]

    def _read(self, who, chat):
        return self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(who)).get_json()

    def _tap(self, who, chat, message, picked, **more):
        return self.client.post(f"/v2/chats/{chat}/setup/{message}", json={"picked": picked, **more},
                                headers=self._as(who))

    def test_my_questions_are_kept_and_checked(self):
        self.assertEqual(self._set(TOMEK, SET).status_code, 200)
        kept = self.client.get("/v2/chats/join-questions", headers=self._as(TOMEK)).get_json()["questions"]
        self.assertEqual([line["q"] for line in kept["lines"]],
                         ["Let's build our knowledge base a month at a time.", "Are you in a hurry?",
                          "Which languages can we use?"])
        bad = self._set(TOMEK, {"lines": [{"q": "When are you free?", "answers": ["Evenings"]}]})
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (400, "NO_ANSWERS"))
        self.assertEqual(self._set(TOMEK, {"plan": None, "lines": []}).get_json(), {"questions": None})

    def test_whoever_joins_finds_my_first_lines_and_i_do_not(self):
        self._set(TOMEK, SET)
        chat = self._join(TOMEK, PIOTR)
        piotr = self._read(PIOTR, chat)
        self.assertEqual([m["body"] for m in piotr["messages"]],
                         ["Let's build our knowledge base a month at a time.", "Are you in a hurry?"])
        self.assertTrue(all(not m["mine"] for m in piotr["messages"]))
        self.assertEqual(piotr["messages"][-1]["meta"]["setup"]["answers"], ["No", "Yes"])
        self.assertEqual((piotr["joined_through"], piotr["joined_asks"]), ("Tomek", True))
        tomek = self._read(TOMEK, chat)
        self.assertEqual((tomek["messages"], tomek["joined_by"]), ([], "Piotr"))

    def test_they_answer_by_tapping_and_i_read_one_card(self):
        self._set(TOMEK, SET)
        chat = self._join(TOMEK, PIOTR)
        hurry = self._read(PIOTR, chat)["messages"][-1]["id"]
        got = self._tap(PIOTR, chat, hurry, ["No"]).get_json()["messages"]
        self.assertEqual([m["body"] for m in got], ["No", "Which languages can we use?"])
        due = date.today() + timedelta(days=30)
        self.assertEqual(got[0]["meta"]["setup_answer"]["deadline"], due.isoformat())
        languages = got[-1]["id"]
        end = self._tap(PIOTR, chat, languages, ["English", "Polish"]).get_json()["messages"]
        self.assertEqual([m["body"] for m in end], ["Polish, English", J.CLOSING])
        tomek = self._read(TOMEK, chat)["messages"]
        self.assertEqual([m["meta"].get("setup_card") for m in tomek],
                         [{"rows": [{"k": "Deadline", "v": P.fmt_day(due)},
                                    {"k": "Languages", "v": "Polish, English"}]}])
        self.assertNotIn("setup_card", str(self._read(PIOTR, chat)["messages"]))
        row = self.client.get("/v2/chats", headers=self._as(TOMEK)).get_json()["chats"][0]
        self.assertEqual(row["last"]["meta"], {"setup_card": True})
        piotr_row = self.client.get("/v2/chats", headers=self._as(PIOTR)).get_json()["chats"][0]
        self.assertEqual(piotr_row["last"]["body"], J.CLOSING)

    def test_a_tap_that_is_not_an_answer_is_refused(self):
        self._set(TOMEK, SET)
        chat = self._join(TOMEK, PIOTR)
        hurry = self._read(PIOTR, chat)["messages"][-1]["id"]
        self.assertEqual(self._tap(PIOTR, chat, hurry, ["Maybe"]).get_json()["code"], "PICK_ONE")
        self.assertEqual(self._tap(PIOTR, chat, hurry, ["No", "Yes"]).get_json()["code"], "PICK_ONE")
        self.assertEqual(self._tap(PIOTR, chat, hurry, ["Yes"], date="2000-01-01").get_json()["code"],
                         "INVALID_DATE")
        self.assertEqual(self._tap(TOMEK, chat, hurry, ["No"]).status_code, 404)
        self.assertEqual(self._tap(PIOTR, chat, hurry, ["No"]).status_code, 200)
        self.assertEqual(self._tap(PIOTR, chat, hurry, ["No"]).status_code, 409)

    def test_joining_someone_with_no_questions_posts_nothing(self):
        chat = self._join(TOMEK, PIOTR)
        piotr = self._read(PIOTR, chat)
        self.assertEqual((piotr["messages"], piotr["joined_asks"]), ([], False))


class ReadyTest(unittest.TestCase):
    def test_a_typed_question_is_kept_only_when_practical_with_answers(self):
        out = J.ready(["Is a video call OK?", "What are you preparing for?", "Which city are you in?",
                       "When are you free for a call? Weekdays / Weekends"], ["Polish", "English"])
        self.assertEqual([(line["q"], line["answers"]) for line in out["keep"]],
                         [("Is a video call OK?", ["No", "Yes"]),
                          ("When are you free for a call?", ["Weekdays", "Weekends"])])
        self.assertEqual(out["about"], ["What are you preparing for?"])
        self.assertEqual(out["open"], ["Which city are you in?"])
        self.assertTrue(out["added"])


if __name__ == "__main__":
    unittest.main()
