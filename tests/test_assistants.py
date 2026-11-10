"""
STORY    As someone who invites people, I want my own chat answered by "{name}'s
         assistant", so that whoever joins through my link meets my chat, set
         up my way, and knows an AI answers for me (N578, N579, N580, N585,
         N586, N588).
OUTCOME
  O1  With the chat builder's ring, each chat with a person in my list says
      whose assistant answers there: "Tomek's assistant"; without the ring,
      nothing changes (N579 item 2, N580 items 1 and 3).
  O2  The join page of anyone's link is three lines: "Tomek invited you",
      one sentence of what you'll learn, "Only the two of you are in this
      chat."; Artur's link says his signed sentence; a tester's link also
      names "Tomek's assistant"; the old line about Will's chat is gone
      (N601).
  O3  A host sets the welcome, the first Take's questions and how people
      answer; the builder starts from Artur's five; a locked field (the
      Nevers, consent, the bar...) is refused (N578 item 5, N579 item 1).
  O4  A host's own words pass the checks Will's bubbles pass: a score or a
      verdict about the speaker is refused, their own numbers are not
      (N578 item 6, Never 1).
  O5  A simple recognizer reads on one line with two cuts: Yes past the
      upper, No below the lower, the queue between, coloured green, yellow
      or red, never a number (N580 item 3, N585 item 2).
  O6  A speaking coach is suggested only for a recording of you talking; a
      topic expert for their topic from any message; adding a coach your
      message doesn't suit brings one line with "Record" and "Send anyway"
      (N588).
  O7  As a tester I keep my chat's recipe and read it back, with Artur's
      five to start from; without the ring the builder is 404; a locked
      field is 400 RECIPE_LOCKED and nothing is kept.
  O8  Someone who joins through my link meets my welcome first, as my
      own words (no assistant's mark, N606), and my join page says who I am and what they
      can learn with me, in my own words (N586 item 1, N590 item 2).
  O9  In my chat, the person who joined reads whose assistant answers, my
      first Take's questions and how they may answer; a chat with someone
      who has no recipe is as it was.
  O10 In Will's chat, Will says what I know can earn tokens, with "Set up my
      chat"; then asks, one at a time, my welcome, how people answer, my
      specialization, what people learn, a skill or a topic and what I need
      to see, and "Do you want to automate your own chat?"; "Go live" keeps
      it, with the first Take's questions set in the builder, and the next
      person who joins meets it (N582 item 1, N586 item 5).
  O11 A welcome that scores people is not kept: Will says why and asks again.
PROVES   O1 -> AssistantsTest::test_my_list_says_whose_assistant_answers
         O2 -> AssistantsTest::test_the_join_page_is_three_lines
         O3 -> RecipeTest::test_a_host_sets_welcome_questions_and_how_people_answer
         O4 -> RecipeTest::test_a_hosts_words_never_score_the_speaker
         O5 -> RecipeTest::test_a_recognizer_reads_on_one_line_with_two_cuts
         O6 -> RecipeTest::test_suggestions_are_sensible_and_anyone_can_still_be_asked
         O7 -> AssistantsTest::test_a_tester_keeps_their_recipe
         O8 -> AssistantsTest::test_someone_who_joins_meets_my_welcome_and_who_i_am
         O9 -> AssistantsTest::test_the_joiner_reads_what_my_chat_is
         O10 -> SetupInWillsChatTest::test_will_sets_up_my_chat_one_question_at_a_time
         O11 -> SetupInWillsChatTest::test_a_welcome_that_scores_people_is_asked_again
WHY      Every inviter has a coach chat of their own (N578); the builder's MVP
         is for the founder and a few testers first (N579).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import assistants
from services.assistants import RecipeError
from tests import test_chat_links as TL
from tests.test_chat_links import PIOTR, TOMEK


def _ring(on_for):
    def check(feature, user_id, database=None):
        del database
        return feature == "chat_builder" and str(user_id) in on_for
    return check


class AssistantsTest(unittest.TestCase):
    setUp = TL.ChatLinksTest.setUp
    _as, _link, _join, _preview = (TL.ChatLinksTest._as, TL.ChatLinksTest._link,
                                   TL.ChatLinksTest._join, TL.ChatLinksTest._preview)

    def _list(self, who):
        return self.client.get("/v2/chats", headers=self._as(who)).get_json()["chats"]

    def test_my_list_says_whose_assistant_answers(self):
        token = self._link(TOMEK).get_json()["token"]
        self._join(PIOTR, token)
        with patch("services.rings.feature_is_on_for_user", _ring({PIOTR})):
            self.assertEqual([c["assistant"] for c in self._list(PIOTR)], ["Tomek's assistant"])
            self.assertEqual([c["assistant"] for c in self._list(TOMEK)], [None])

    def test_the_join_page_is_three_lines(self):
        token = self._link(TOMEK).get_json()["token"]
        with patch("services.rings.feature_is_on_for_user", _ring({TOMEK})):
            self.assertEqual(self._preview(token).get_json(), {
                "name": "Tomek", "invited": "Tomek invited you", "learn": None,
                "only_two": "Only the two of you are in this chat.",
                "assistant": "Tomek's assistant"})
        with patch("services.rings.feature_is_on_for_user", _ring(set())), \
                patch("config.Config.FOUNDER_CHAT_USER_ID", TOMEK):
            self.assertEqual(self._preview(token).get_json(), {
                "name": "Tomek", "invited": "Tomek invited you",
                "learn": "Record a short talk. He'll tell you what landed and what to try next.",
                "only_two": "Only the two of you are in this chat."})


    KASIA = {"welcome": ["Hi, I'm Kasia. Let's get you moving."],
             "questions": [{"q": "Which move do you want first?",
                            "answers": ["Handstand", "Cartwheel"]}],
             "answer_with": {"tap": True, "type": False, "record": True},
             "about": ["Your first handstand, step by step, at your own pace."],
             "fit": {"coaches": "skill", "needs": "moving", "skill": "gymnastics"}}

    def _keep(self, who, body):
        return self.client.put("/v2/chats/recipe", headers=self._as(who), json=body)

    def test_a_tester_keeps_their_recipe(self):
        with patch("services.rings.feature_is_on_for_user", _ring(set())):
            self.assertEqual(self.client.get("/v2/chats/recipe", headers=self._as(TOMEK)).status_code, 404)
            self.assertEqual(self._keep(TOMEK, self.KASIA).status_code, 404)
        with patch("services.rings.feature_is_on_for_user", _ring({TOMEK})):
            got = self.client.get("/v2/chats/recipe", headers=self._as(TOMEK)).get_json()
            self.assertEqual((got["assistant"], got["recipe"]), ("Tomek's assistant", None))
            self.assertEqual(got["starting_questions"][4]["q"],
                             "If they remember one sentence from you, what should it be?")
            refused = self._keep(TOMEK, {"consent": "off"})
            self.assertEqual((refused.status_code, refused.get_json()["code"]), (400, "RECIPE_LOCKED"))
            self.assertEqual(self._keep(TOMEK, self.KASIA).status_code, 200)
            kept = self.client.get("/v2/chats/recipe", headers=self._as(TOMEK)).get_json()["recipe"]
            self.assertEqual(kept["welcome"], ["Hi, I'm Kasia. Let's get you moving."])
            self.assertEqual(kept["fit"]["skill"], "gymnastics")

    def test_someone_who_joins_meets_my_welcome_and_who_i_am(self):
        token = self._link(TOMEK).get_json()["token"]
        with patch("services.rings.feature_is_on_for_user", _ring({TOMEK})):
            self._keep(TOMEK, self.KASIA)
            self.assertEqual(self._preview(token).get_json()["learn"],
                             "Your first handstand, step by step, at your own pace.")
            long = {**self.KASIA, "about": [" ".join(["word"] * 21)]}
            self.assertEqual(self._keep(TOMEK, long).get_json()["code"], "RECIPE_INVALID")
            chat = self._join(PIOTR, token).get_json()["chat"]["id"]
        seen = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(PIOTR)).get_json()["messages"]
        self.assertEqual([m["body"] for m in seen], ["Hi, I'm Kasia. Let's get you moving."])
        self.assertNotIn("assistant", seen[0]["meta"])  # N606: the host's own words
        mine = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(TOMEK)).get_json()["messages"]
        self.assertEqual(mine, [])

    def test_the_joiner_reads_what_my_chat_is(self):
        token = self._link(TOMEK).get_json()["token"]
        chat = self._join(PIOTR, token).get_json()["chat"]["id"]
        with patch("services.rings.feature_is_on_for_user", _ring({TOMEK})):
            host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]
            self.assertIsNone(host)
            self._keep(TOMEK, self.KASIA)
            host = self.client.get(f"/v2/chats/{chat}/host", headers=self._as(PIOTR)).get_json()["host"]
            self.assertEqual(host["assistant"], "Tomek's assistant")
            self.assertEqual(host["questions"][0]["answers"], ["Handstand", "Cartwheel"])
            self.assertEqual(host["answer_with"], {"tap": True, "type": False, "record": True})
            self.assertIsNone(self.client.get(f"/v2/chats/{chat}/host",
                                              headers=self._as(TOMEK)).get_json()["host"])


class SetupInWillsChatTest(unittest.TestCase):
    setUp_ = TL.ChatLinksTest.setUp
    _as, _link, _join = TL.ChatLinksTest._as, TL.ChatLinksTest._link, TL.ChatLinksTest._join

    def setUp(self):
        from services.db import db
        from tests.test_join_questions import _Lounge
        self.setUp_()
        self.lounge = _Lounge()
        for p in (patch.object(db, "insert_lounge_messages", self.lounge.insert),
                  patch.object(db, "get_lounge_messages_page", self.lounge.page),
                  patch.object(db, "get_lounge_message_by_client_id", self.lounge.one),
                  patch.object(db, "get_open_plan", lambda _u: {"facts": {"topic": "speaking"}},
                               create=True),
                  patch("services.rings.feature_is_on_for_user", _ring({TOMEK}))):
            p.start()
            self.addCleanup(p.stop)

    def _asked(self):
        return self.lounge.page(TOMEK)[0]

    def _say(self, **answer):
        got = self.client.post("/v2/chats/recipe/setup/answer", headers=self._as(TOMEK),
                               json={"to": self._asked()["client_id"], **answer})
        return [m["body"] for m in got.get_json()["messages"]] if got.status_code == 200 else got.status_code

    def _chips(self):
        return self._asked()["metadata"]["chat_setup"]["chips"]

    def test_will_sets_up_my_chat_one_question_at_a_time(self):
        from services import chat_setup as C
        self.client.post("/v2/chats/recipe/setup/offer", headers=self._as(TOMEK))
        self.assertEqual(self._asked()["body"], (
            "What you know can earn tokens: by teaching the models in your field, and you can spend "
            "them on a chat of your own that shares what you know while you're away, if you want it."))
        self.assertEqual(self._chips(), ["Set up my chat"])
        self.assertEqual(self._say(picked="Set up my chat"), [
            "Set up my chat", "Let's set up your chat. People who join through your link will meet it.",
            "What should people read first when they open your chat? Write it as you'd greet them."])
        self.assertEqual(self._say(said="Hi, I'm Tomek. Let's get you moving."),
                         ["Hi, I'm Tomek. Let's get you moving.", "How should people answer you in your chat?"])
        self.assertEqual(self._chips(), ["Record", "Type", "Tap answers", "Any of these"])
        self.assertEqual(self._say(picked="Record"), ["Record", "What is your specialization?"])
        self.assertEqual(self._chips(), ["Speaking", "Something else"])
        self.assertEqual(self._say(picked="Something else"), ["Something else", "What is your specialization?"])
        self.assertEqual(self._say(said="Gymnastics"),
                         ["Gymnastics", "What can people learn in your chat? One sentence."])
        self.assertEqual(self._say(said=" ".join(["handstand"] * 25)), [
            " ".join(["handstand"] * 25),
            "Shorter, please: one sentence of about fifteen words, for your join page.",
            "What can people learn in your chat? One sentence."])
        self.assertEqual(self._say(said="Your first handstand, step by step."), [
            "Your first handstand, step by step.",
            "Do people come to you to be coached on how they do something, or with questions on a topic?"])
        self.assertEqual(self._say(picked="How they do it"),
                         ["How they do it", "What do you need to see to coach them?"])
        self.assertEqual(self._say(picked="Them moving"), ["Them moving", C.AUTOMATE_WHY,
                                                           "Do you want to automate your own chat?"])
        self.assertEqual(self._chips(), ["Yes", "Not now", "Help train an existing model"])
        self.assertEqual(self._say(picked="Not now")[1].split("\n"), [
            "This is what someone new will meet in your chat:", "Tomek invited you",
            "Your first handstand, step by step.", "Only the two of you are in this chat.",
            "Hi, I'm Tomek. Let's get you moving."])
        self.client.put("/v2/chats/recipe", headers=self._as(TOMEK), json={
            "questions": [{"q": "Which move do you want first?", "answers": ["Handstand"]}]})
        self.assertEqual(self._say(picked="Go live"), [
            "Go live", "Your chat is live. Everyone who joins through your link meets it."])
        kept = self.client.get("/v2/chats/recipe", headers=self._as(TOMEK)).get_json()["recipe"]
        self.assertEqual((kept["answer_with"], kept["fit"], kept["model"]), (
            {"tap": False, "type": False, "record": True},
            {"coaches": "skill", "needs": "moving", "topics": [], "skill": "gymnastics"},
            {"automate": "no"}))
        self.assertEqual([q["q"] for q in kept["questions"]], ["Which move do you want first?"])
        token = self._link(TOMEK).get_json()["token"]
        chat = self._join(PIOTR, token).get_json()["chat"]["id"]
        seen = self.client.get(f"/v2/chats/{chat}/messages", headers=self._as(PIOTR)).get_json()["messages"]
        self.assertEqual([m["body"] for m in seen], ["Hi, I'm Tomek. Let's get you moving."])
        # The MVP's Will chat (N599): the setup writes nothing of principles,
        # the Sunday note or life goals.
        said = " ".join(r["body"] for r in self.lounge.rows.values())
        for gone in ("Your principles", "The Sunday note", "Your life goals"):
            self.assertNotIn(gone, said)

    def test_a_welcome_that_scores_people_is_asked_again(self):
        self.client.post("/v2/chats/recipe/setup", headers=self._as(TOMEK))
        self.assertEqual(self._say(said="I rate everyone out of 10 points."), [
            "I rate everyone out of 10 points.",
            "I can't put that in your chat: it reads like a score or a verdict about someone.",
            "What should people read first when they open your chat? Write it as you'd greet them."])
        self.assertEqual(self._say(picked="Record"), 400)


class RecipeTest(unittest.TestCase):
    def test_a_host_sets_welcome_questions_and_how_people_answer(self):
        start = assistants.starting_questions()
        self.assertEqual(len(start), 5)
        self.assertEqual(start[0]["q"], "What do you know better than most people you meet?")
        recipe = assistants.normalize({
            "welcome": ["Hi, I'm Kasia. I teach gymnastics to beginners."],
            "questions": [start[0], {"q": "Which move do you want first?",
                                     "answers": ["Handstand", "Cartwheel"]}],
            "answer_with": {"tap": True, "type": False, "record": True}})
        self.assertEqual(recipe["welcome"], ["Hi, I'm Kasia. I teach gymnastics to beginners."])
        self.assertEqual([q["q"] for q in recipe["questions"]],
                         ["What do you know better than most people you meet?",
                          "Which move do you want first?"])
        self.assertEqual(recipe["questions"][1]["answers"], ["Handstand", "Cartwheel"])
        self.assertEqual(recipe["answer_with"], {"tap": True, "type": False, "record": True})
        for locked in ("nevers", "consent", "bar", "walk_order", "recording_screens"):
            with self.assertRaises(RecipeError) as refused:
                assistants.normalize({locked: "mine"})
            self.assertEqual(refused.exception.code, "RECIPE_LOCKED")
        with self.assertRaises(RecipeError) as later:
            assistants.normalize({"model": "Speaking confidence"})
        self.assertEqual(later.exception.code, "RECIPE_INVALID")
        with self.assertRaises(RecipeError):
            assistants.normalize({"answer_with": {"tap": False, "type": False, "record": False}})

    def test_a_hosts_words_never_score_the_speaker(self):
        self.assertIsNone(assistants.check_host_words("Show me five minutes of your routine."))
        for refused in ("You scored 7/10 on balance.", "That's 80% there.",
                        "Your landing was wrong.", "Let's fix your posture."):
            self.assertIsNotNone(assistants.check_host_words(refused), refused)
        # A host's own words in their own chat may judge in words (N616 item 12);
        # a number about the person is still refused there.
        self.assertIsNone(assistants.check_host_words("I'll show you the one thing to fix.", verdicts=False))
        self.assertIsNotNone(assistants.check_host_words("You scored 7/10.", verdicts=False))
        with self.assertRaises(RecipeError) as words:
            assistants.normalize({"welcome": ["I rate you out of 10 points."]})
        self.assertEqual(words.exception.code, "RECIPE_WORDS")

    def test_a_recognizer_reads_on_one_line_with_two_cuts(self):
        read = assistants.read_line
        self.assertEqual(read(0.9, 0.3, 0.7, 0.1), {"answer": "yes", "mark": "green", "queue": False})
        self.assertEqual(read(0.75, 0.3, 0.7, 0.1), {"answer": "yes", "mark": "yellow", "queue": False})
        self.assertEqual(read(0.1, 0.3, 0.7, 0.1), {"answer": "no", "mark": "green", "queue": False})
        self.assertEqual(read(0.5, 0.3, 0.7, 0.1), {"answer": None, "mark": "red", "queue": True})

    def test_suggestions_are_sensible_and_anyone_can_still_be_asked(self):
        artur = {"coaches": "skill", "needs": "talking", "skill": "speaking"}
        gym = {"coaches": "skill", "needs": "moving", "skill": "gymnastics"}
        coder = {"coaches": "topic", "needs": "any", "topics": ["programming", "Python"]}
        self.assertTrue(assistants.suits(artur, {"kind": "voice"}))
        self.assertFalse(assistants.suits(artur, {"kind": "text"}))
        self.assertFalse(assistants.suits(gym, {"kind": "text", "topic": "gym advice"}))
        self.assertTrue(assistants.suits(gym, {"kind": "video"}))
        self.assertTrue(assistants.suits(coder, {"kind": "text", "topic": "a Python question"}))
        self.assertFalse(assistants.suits(coder, {"kind": "voice", "topic": "my wedding toast"}))
        self.assertEqual(assistants.nudge("Artur", artur, {"kind": "text"}), {
            "line": "Artur coaches speaking and will need to hear you. Record it instead?",
            "chips": ["Record", "Send anyway"]})
        self.assertEqual(assistants.nudge("Kasia", gym, {"kind": "text"})["line"],
                         "Kasia coaches gymnastics and will need to see you doing it. "
                         "Record a video instead?")
        self.assertIsNone(assistants.nudge("Artur", artur, {"kind": "take"}))
        self.assertIsNone(assistants.nudge("Ola", coder, {"kind": "text", "topic": "cooking"}))


if __name__ == "__main__":
    unittest.main()
