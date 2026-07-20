"""willab — quote narrowing for text-suggestion stars (founder 2026-07-20).

Gradual refinement, step 1: a star underlines the PHRASE it is about,
never the whole ~300-char piece. Pinned here:
  * diff_quote — prefix/suffix-trimmed changed span, word-boundary
    snapped, ALWAYS a substring of the original, None on no-change /
    empty / near-whole-piece degeneration;
  * profanity_sentence — the sentence carrying the FIRST hit;
  * find_profanity — offset twin of has_profanity.

Run: python3 -m unittest test_suggestion_quotes
"""
from __future__ import annotations

import unittest

from services.suggestion_quotes import diff_quote, profanity_sentence
from services.text_flags import find_profanity


class DiffQuoteTests(unittest.TestCase):
    def test_mid_change_trims_to_span(self):
        a = "we grew because the team kept showing up every day"
        b = "we grew because the team stayed relentless every day"
        q = diff_quote(a, b)
        self.assertEqual(q, "kept showing up")
        self.assertIn(q, a)

    def test_word_boundary_snap_never_mid_word(self):
        a = "the presenting was strong"
        b = "the presentation was strong"
        q = diff_quote(a, b)
        self.assertIn(q, a)
        self.assertIn(q, ("presenting",))   # whole word, not "ing" tail

    def test_pure_insertion_snaps_to_neighbour(self):
        a = "we shipped it and moved on"
        b = "we shipped it quickly and moved on"
        q = diff_quote(a, b)
        self.assertIsNotNone(q)
        self.assertIn(q, a)

    def test_no_change_or_empty_is_none(self):
        self.assertIsNone(diff_quote("same words", "same words"))
        self.assertIsNone(diff_quote("", "anything"))
        self.assertIsNone(diff_quote("anything", ""))
        self.assertIsNone(diff_quote(None, None))

    def test_whole_piece_change_degrades_to_icon_only(self):
        a = "alpha " * 40   # ~240 chars, everything different
        b = "omega " * 40
        self.assertIsNone(diff_quote(a, b))

    def test_quote_always_substring_of_original(self):
        cases = [
            ("I think this lands well", "I believe this lands well"),
            ("start changed here", "start altered here"),
            ("tail stays but the head moved", "tail stays but a head moved"),
        ]
        for a, b in cases:
            q = diff_quote(a, b)
            if q is not None:
                self.assertIn(q, a)


class ProfanitySentenceTests(unittest.TestCase):
    def test_first_sentence_hit(self):
        t = "This is fucking hard. But we kept going."
        self.assertEqual(profanity_sentence(t), "This is fucking hard.")

    def test_middle_sentence_hit(self):
        t = "We started small. Then shit happened fast. We recovered."
        self.assertEqual(profanity_sentence(t), "Then shit happened fast.")

    def test_no_hit_or_empty_is_none(self):
        self.assertIsNone(profanity_sentence("all clean words here."))
        self.assertIsNone(profanity_sentence(""))
        self.assertIsNone(profanity_sentence(None))

    def test_unpunctuated_piece_returns_whole_text(self):
        t = "and then the damn projector died on stage"
        self.assertEqual(profanity_sentence(t), t)

    def test_result_is_substring(self):
        t = "One clean line. A crappy second line! A clean third."
        q = profanity_sentence(t)
        self.assertIn(q, t)


class FindProfanityTests(unittest.TestCase):
    def test_offset_of_first_hit(self):
        t = "well shit happens"
        self.assertEqual(find_profanity(t), t.index("shit"))

    def test_no_hit_and_scunthorpe_guard(self):
        self.assertIsNone(find_profanity("the class assesses Scunthorpe"))
        self.assertIsNone(find_profanity(None))
        self.assertIsNone(find_profanity(""))


if __name__ == "__main__":
    unittest.main()
