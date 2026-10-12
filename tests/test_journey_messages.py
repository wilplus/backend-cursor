from __future__ import annotations

import unittest

from services.journey_messages import journey_message


class JourneyMessageTests(unittest.TestCase):

    def test_take_one_copy_and_action_are_locked(self):
        row = journey_message("u1", "a1", 1)
        self.assertEqual(row["kind"], "cadence")
        self.assertEqual(row["body"].split("\n\n"), [
            "We have successfully registered your first take 🎉",
            "You have recorded some of the helper words and recognized your "
            "confident moments.",
            "Use the helper words and record the second take of your presentation ⬇️",
        ])
        self.assertEqual(row["metadata"]["actions"],
                         ["prepare_take_2", "keep_practising"])


if __name__ == "__main__":
    unittest.main()
