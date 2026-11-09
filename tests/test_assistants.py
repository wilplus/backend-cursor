"""
STORY    As someone who invites people, I want my own chat answered by "{name}'s
         assistant", so that whoever joins through my link meets my chat, set
         up my way, and knows an AI answers for me (N578, N579, N580, N585,
         N586, N588).
OUTCOME
  O1  With the chat builder's ring, each chat with a person in my list says
      whose assistant answers there: "Tomek's assistant"; without the ring,
      nothing changes (N579 item 2, N580 items 1 and 3).
  O2  The join page of a tester's link says "Tomek's assistant" and "Will's
      chat is where you can set up a chat of your own."; anyone else's link
      shows only the name, as before (N586 item 2).
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
PROVES   O1 -> AssistantsTest::test_my_list_says_whose_assistant_answers
         O2 -> AssistantsTest::test_a_testers_join_page_names_the_assistant_and_wills_chat
         O3 -> RecipeTest::test_a_host_sets_welcome_questions_and_how_people_answer
         O4 -> RecipeTest::test_a_hosts_words_never_score_the_speaker
         O5 -> RecipeTest::test_a_recognizer_reads_on_one_line_with_two_cuts
         O6 -> RecipeTest::test_suggestions_are_sensible_and_anyone_can_still_be_asked
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

    def test_a_testers_join_page_names_the_assistant_and_wills_chat(self):
        token = self._link(TOMEK).get_json()["token"]
        with patch("services.rings.feature_is_on_for_user", _ring({TOMEK})):
            self.assertEqual(self._preview(token).get_json(), {
                "name": "Tomek", "assistant": "Tomek's assistant",
                "will_line": "Will's chat is where you can set up a chat of your own."})
        with patch("services.rings.feature_is_on_for_user", _ring(set())):
            self.assertEqual(self._preview(token).get_json(), {"name": "Tomek"})


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
