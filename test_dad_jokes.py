"""Founder dad-joke set + rotation (BE-owned). Pure — no network.

Run: python3 -m unittest test_dad_jokes
"""
from __future__ import annotations

import unittest

import services.dad_jokes as dj


class DadJokesTests(unittest.TestCase):
    def test_set_is_the_ten_founder_jokes(self):
        self.assertEqual(len(dj.DAD_JOKES), 10)
        self.assertTrue(all(isinstance(j, str) and j.strip() for j in dj.DAD_JOKES))

    def test_no_em_dashes_house_rule(self):
        for j in dj.DAD_JOKES:
            self.assertNotIn("—", j, j)   # em dash
            self.assertNotIn(" - ", j, j)      # spaced hyphen as separator

    def test_rotation_never_repeats_back_to_back(self):
        dj._last = -1  # deterministic start
        seen = [dj.next_dad_joke() for _ in range(50)]
        for a, b in zip(seen, seen[1:]):
            self.assertNotEqual(a, b)          # no immediate repeat

    def test_random_reaches_all_over_many_calls(self):
        # random selection — every joke should appear at least once over enough
        # draws (no permanently-unreachable index).
        dj._last = -1
        seen = {dj.next_dad_joke() for _ in range(300)}
        self.assertEqual(seen, set(dj.DAD_JOKES))

    def test_returns_a_known_joke(self):
        self.assertIn(dj.next_dad_joke(), dj.DAD_JOKES)


if __name__ == "__main__":
    unittest.main()
