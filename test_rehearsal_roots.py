from __future__ import annotations

import unittest

from services.rehearsal_roots import rehearsal_root


class RehearsalRootTests(unittest.TestCase):
    def test_fallback_is_first_five_visible_words_and_neutral(self):
        self.assertEqual(
            rehearsal_root("**A clear opening** gives the audience direction."),
            {"text": "A clear opening gives the", "type": "neutral"},
        )

    def test_accepted_orange_span_becomes_the_only_flagship_root(self):
        self.assertEqual(
            rehearsal_root(
                "Start here, then {{orange:make the outcome feel inevitable today}}."
            ),
            {"text": "make the outcome feel inevitable", "type": "flagship"},
        )

    def test_short_paragraph_uses_available_words_without_inventing_any(self):
        self.assertEqual(
            rehearsal_root("One idea."),
            {"text": "One idea", "type": "neutral"},
        )

    def test_empty_text_stays_an_empty_neutral_root(self):
        self.assertEqual(rehearsal_root(None), {"text": "", "type": "neutral"})


if __name__ == "__main__":
    unittest.main()
