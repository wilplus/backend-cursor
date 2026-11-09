"""
STORY    As someone on the models page, I want "For you" to show the models
         that need what I know and the ones I teach, so that my answers go
         where they count (founder, 5 November 2026, N518 items 7 and 8,
         N520 item 7; App Model MOD-53).
OUTCOME
  O1  "For you" shows only the models whose words match the person's
      profile at the matching's threshold (2.0) or more, and the ones they
      teach, whatever their score; nothing else, and never a score.
  O2  An answer feeds the one model that fits the profile best at 2.0 or
      more; below it, no model.
PROVES   O1 -> ModelMatchTest::test_for_you_is_chosen_by_the_knowledge_score
         O2 -> ModelMatchTest::test_an_answer_feeds_the_best_model_or_none
WHY      The person-to-model matching reuses the score and threshold of the
         person-to-Take matching (N518 item 7: "Yes, reuse the score and
         threshold").
"""
import unittest

from services.model_match import feeds, for_you

MARTA = ("Media relations lead. I prepare executives for press interviews and "
         "handle crisis communication with journalists.")
MODELS = [
    {"id": "press", "words": "Press interviews: answering journalists in a crisis, "
                             "crisis communication for executives."},
    {"id": "hair", "words": "Hair care: scalp conditions, trichology, hair loss stages."},
    {"id": "code", "words": "Programming: Python code review, tests and debugging."},
    {"id": "speaking", "words": "Speaking: confident delivery, pauses and pace."},
]


class ModelMatchTest(unittest.TestCase):
    def test_for_you_is_chosen_by_the_knowledge_score(self):
        self.assertEqual(for_you(MARTA, MODELS), ["press"])
        self.assertEqual(for_you(MARTA, MODELS, teaches=["speaking"]), ["speaking", "press"])
        self.assertEqual(for_you("", MODELS, teaches=["hair"]), ["hair"])
        # One shared word is not enough: "journalists" alone is under 2.0.
        self.assertEqual(for_you("I read journalists.", MODELS), [])

    def test_an_answer_feeds_the_best_model_or_none(self):
        self.assertEqual(feeds(MARTA, MODELS), "press")
        self.assertIsNone(feeds("I grow tomatoes.", MODELS))


if __name__ == "__main__":
    unittest.main()
