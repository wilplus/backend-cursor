"""Unit tests for the trivial-edit gate helper.

Covers every acceptance case from the FE handoff plus a handful of
property-style edges that have bitten gates like this before
(reordering, mixed casing, embedded punctuation, large drift).

Run: python3 -m unittest test_word_diff_gate
"""
from __future__ import annotations

import unittest

from services.utils import (
    TRIVIAL_EDIT_TOKEN_THRESHOLD,
    changed_word_tokens,
)


class WordDiffGateTests(unittest.TestCase):
    # ── Acceptance cases from the handoff ──────────────────────────

    def test_identical_strings_zero_diff(self):
        s = "This is exactly the same sentence."
        self.assertEqual(changed_word_tokens(s, s), 0)

    def test_single_word_substitution_counts_one(self):
        a = "The quick brown fox jumps over the lazy dog"
        b = "The slow brown fox jumps over the lazy dog"
        self.assertEqual(changed_word_tokens(a, b), 1)

    def test_reordered_phrases_counts_swaps_not_zero(self):
        # The brief explicitly calls out reordering as a Levenshtein-
        # vs-set-diff motivation. "brave and bold" → "bold and brave"
        # is two substitutions at the word level.
        a = "brave and bold"
        b = "bold and brave"
        self.assertEqual(changed_word_tokens(a, b), 2)

    def test_case_only_difference_returns_zero(self):
        self.assertEqual(
            changed_word_tokens("Hello World", "hello world"),
            0,
        )

    def test_punctuation_only_difference_returns_zero(self):
        # Trailing period, comma → both stripped before tokenising.
        self.assertEqual(
            changed_word_tokens("Hello, world!", "hello world"),
            0,
        )

    def test_case_and_punctuation_combined_returns_zero(self):
        self.assertEqual(
            changed_word_tokens(
                "AI! Is. This. THE. SAME?",
                "ai is this the same",
            ),
            0,
        )

    def test_empty_draft_returns_full_token_count(self):
        # Admin typed from scratch with no AI baseline → the entire
        # admin text counts toward the threshold. 7 words means the
        # gate (threshold > 5) lets it through cleanly.
        self.assertEqual(
            changed_word_tokens("", "one two three four five six seven"),
            7,
        )
        self.assertEqual(
            changed_word_tokens(None, "one two three four five six seven"),
            7,
        )

    def test_empty_admin_text_returns_full_draft_count(self):
        # Symmetric — should never realistically happen (admin
        # submits empty?) but we don't crash.
        self.assertEqual(changed_word_tokens("a b c", ""), 3)
        self.assertEqual(changed_word_tokens("a b c", None), 3)

    def test_both_empty_returns_zero(self):
        self.assertEqual(changed_word_tokens("", ""), 0)
        self.assertEqual(changed_word_tokens(None, None), 0)
        self.assertEqual(changed_word_tokens("", None), 0)

    # ── Threshold behaviour the gate actually depends on ───────────

    def test_threshold_constant_is_five(self):
        # The gate uses > THRESHOLD, so 5 = trivial, 6 = real.
        self.assertEqual(TRIVIAL_EDIT_TOKEN_THRESHOLD, 5)

    def test_five_word_swap_is_at_or_below_threshold(self):
        # Five substitutions → exactly at the threshold → trivial.
        a = "one two three four five six seven eight"
        b = "AAA BBB CCC DDD EEE six seven eight"
        self.assertEqual(changed_word_tokens(a, b), 5)
        self.assertLessEqual(
            changed_word_tokens(a, b),
            TRIVIAL_EDIT_TOKEN_THRESHOLD,
        )

    def test_six_word_swap_crosses_threshold(self):
        a = "one two three four five six seven eight"
        b = "AAA BBB CCC DDD EEE FFF seven eight"
        self.assertEqual(changed_word_tokens(a, b), 6)
        self.assertGreater(
            changed_word_tokens(a, b),
            TRIVIAL_EDIT_TOKEN_THRESHOLD,
        )

    # ── Edge cases that have broken gates like this before ─────────

    def test_whitespace_only_difference_returns_zero(self):
        # Double spaces, tabs, trailing newlines — all collapse.
        self.assertEqual(
            changed_word_tokens(
                "hello  world",
                "hello world\n",
            ),
            0,
        )
        self.assertEqual(
            changed_word_tokens(
                "hello\tworld",
                "hello world",
            ),
            0,
        )

    def test_insertion_at_start(self):
        a = "world"
        b = "hello world"
        self.assertEqual(changed_word_tokens(a, b), 1)

    def test_insertion_at_end(self):
        a = "hello"
        b = "hello world"
        self.assertEqual(changed_word_tokens(a, b), 1)

    def test_deletion(self):
        a = "remove this word entirely"
        b = "remove word entirely"
        self.assertEqual(changed_word_tokens(a, b), 1)

    def test_full_rewrite_long_diff(self):
        # Sanity: very different content reports a large diff (not
        # capped, not zero). Concrete value is implementation-defined
        # but must be at least the size of the shorter side.
        a = "alpha beta gamma delta epsilon"
        b = "one two three four five six seven"
        d = changed_word_tokens(a, b)
        self.assertGreaterEqual(d, max(len(a.split()), len(b.split())) - 2)


if __name__ == "__main__":
    unittest.main()
