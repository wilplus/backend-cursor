"""
STORY    As the founder, I want the message after a speaker's first Take to say
         exactly the words I signed off, with its two actions, so that no
         unapproved words reach a speaker.
OUTCOME
  O1  The Take 1 message's text and its two actions (prepare Take 2, keep
      practising) equal the locked copy.
PROVES   O1 -> JourneyMessageTests::test_take_one_copy_and_action_are_locked
WHY      Never-rule 4: no new words on screen without the founder's OK.
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


if __name__ == "__main__":
    unittest.main()
