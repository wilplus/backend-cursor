"""
STORY    As a speaker, I want to ask Will what he has noticed about me and get
         it in words, worked out from all my Takes and messages, only when I
         ask (founder, N691 item 4).
OUTCOME
  O1  An ask for insights is answered from Will's note, what Will said after
      Takes whose processing authorization is in force, and the speaker's
      own messages; a Take not in force is left out.
  O2  A question about one Take, or any other message, is not claimed.
  O3  A reply that puts a number on the speaker never reaches them.
PROVES   O1 -> test_an_ask_is_answered_from_the_authorized_record
         O2 -> test_other_questions_are_not_claimed
         O3 -> test_a_number_about_the_speaker_is_never_sent
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from services import speaker_insights


class _Db:
    def __init__(self):
        self.rows = [  # newest first, as the page returns them
            {"role": "user", "kind": "text", "body": "I always rush the ending."},
            {"role": "bot", "kind": "walk_step", "body": "Hidden Take praise.",
             "metadata": {"step": "praise", "take_session_id": "take-out"}},
            {"role": "bot", "kind": "walk_step", "body": "Your opening question pulled people in.",
             "metadata": {"step": "praise", "take_session_id": "take-in"}},
        ]

    def get_lounge_messages_page(self, user_id, *, limit):
        return list(self.rows)

    def list_user_arc_sessions(self, user_id):
        return [{"id": "take-in"}, {"id": "take-out"}]


class SpeakerInsights(unittest.TestCase):
    def setUp(self):
        self.calls = []
        patches = [
            mock.patch("services.speaker_lookup._takes_in_force", lambda _db, _takes: {"take-in"}),
            mock.patch("services.speaker_memory.note_for", lambda _db, _user: "Prefers short tips."),
            mock.patch("services.llm.chat_complete", self._complete),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.reply = "Your openings keep landing. Next Take, slow the last line."

    def _complete(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(text=self.reply)

    def test_an_ask_is_answered_from_the_authorized_record(self):
        text = speaker_insights.answer(_Db(), "user-1", "What insights do you have about me?")
        self.assertEqual(text, self.reply)
        system = self.calls[0]["system"]
        self.assertIn("Prefers short tips.", system)
        self.assertIn("Your opening question pulled people in.", system)
        self.assertIn("I always rush the ending.", system)
        self.assertNotIn("Hidden Take praise.", system)
        self.assertEqual(self.calls[0]["surface"], "speaker_insights")

    def test_other_questions_are_not_claimed(self):
        for question in ("How did my last Take go?", "Help me with my opening", "Hi Will"):
            self.assertFalse(speaker_insights.asks_for_insights(question), question)
            self.assertIsNone(speaker_insights.answer(_Db(), "user-1", question))
        self.assertTrue(speaker_insights.asks_for_insights("Jak mi idzie?"))
        self.assertEqual(self.calls, [])

    def test_a_number_about_the_speaker_is_never_sent(self):
        self.reply = "You are at 7/10 for confidence."
        self.assertIsNone(speaker_insights.answer(_Db(), "user-1", "How am I doing overall?"))


if __name__ == "__main__":
    unittest.main()
