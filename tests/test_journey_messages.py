"""
STORY    As the founder, I want the messages after a speaker's first three
         Takes to say exactly the words I signed off, with their two actions,
         so that no unapproved words reach a speaker.
OUTCOME
  O1  The Take 1 message's text and its two actions (prepare Take 2, keep
      practising) equal the locked copy.
  O2  The Take 2 message's text and its two actions (prepare Take 3, keep
      practising) equal the locked copy.
  O3  The Take 3 message's text and its two actions (export, keep
      practising) equal the locked copy.
PROVES   O1 -> JourneyMessageTests::test_take_one_copy_and_action_are_locked
         O2 -> JourneyMessageTests::test_take_two_copy_and_action_are_locked
         O3 -> JourneyMessageTests::test_take_three_copy_and_action_are_locked
WHY      Never-rule 4: no new words on screen without the founder's OK. All
         three simplified by the founder in chat, 2026-10-20.
"""

from __future__ import annotations

import unittest

from services.journey_messages import journey_message


class JourneyMessageTests(unittest.TestCase):

    def test_take_one_copy_and_action_are_locked(self):
        row = journey_message("u1", "a1", 1)
        self.assertEqual(row["kind"], "cadence")
        self.assertEqual(row["body"].split("\n\n"), [
            "Your first take is in 🎉",
            "Now record take 2 with your helper words ⬇️",
        ])
        self.assertEqual(row["metadata"]["actions"],
                         ["prepare_take_2", "keep_practising"])

    def test_take_two_copy_and_action_are_locked(self):
        row = journey_message("u1", "a1", 2)
        self.assertEqual(row["body"].split("\n\n"), [
            "Your second take is in 🎉",
            "Now record take 3. Use your helper words as anchors, not a script ⬇️",
        ])
        self.assertEqual(row["metadata"]["actions"],
                         ["prepare_take_3", "keep_practising"])

    def test_take_three_copy_and_action_are_locked(self):
        row = journey_message("u1", "a1", 3)
        self.assertEqual(row["body"].split("\n\n"), [
            "Your third take is in 🎉",
            "Your presentation is ready. Export your notes or keep practising ⬇️",
        ])
        self.assertEqual(row["metadata"]["actions"],
                         ["export", "keep_practising"])


if __name__ == "__main__":
    unittest.main()
