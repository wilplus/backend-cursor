"""Challenge-threat lane (willab Prompt D §3). Pure.

Run: python3 -m unittest test_challenge_threat
"""
from __future__ import annotations

import unittest

from services.challenge_threat import (
    detect_breakthroughs, is_challenge, resolve_direction,
)


class ResolveDirectionTests(unittest.TestCase):
    def test_coach_label_wins(self):
        self.assertEqual(resolve_direction("challenge", "threat"), "challenge")

    def test_falls_back_to_shadow(self):
        self.assertEqual(resolve_direction(None, "threat"), "threat")
        self.assertEqual(resolve_direction("garbage", "challenge"), "challenge")

    def test_none_when_neither_valid(self):
        self.assertIsNone(resolve_direction(None, None))
        self.assertIsNone(resolve_direction("nope", "alsonope"))


class IsChallengeTests(unittest.TestCase):
    def test_only_challenge_passes(self):
        self.assertTrue(is_challenge("challenge"))
        for d in ("threat", "ambiguous", None, ""):
            self.assertFalse(is_challenge(d), d)


class BreakthroughTests(unittest.TestCase):
    def test_challenge_after_threat_is_breakthrough(self):
        snips = [
            {"id": "a", "start_offset_ms": 0, "direction": "threat"},
            {"id": "b", "start_offset_ms": 1000, "direction": "challenge"},
        ]
        self.assertEqual(detect_breakthroughs(snips), {"b"})

    def test_challenge_without_prior_threat_is_not(self):
        snips = [
            {"id": "a", "start_offset_ms": 0, "direction": "challenge"},
            {"id": "b", "start_offset_ms": 1000, "direction": "challenge"},
        ]
        self.assertEqual(detect_breakthroughs(snips), set())

    def test_latch_resets_after_breakthrough(self):
        # threat → challenge (breakthrough) → challenge (NOT) → threat → challenge (breakthrough)
        snips = [
            {"id": "a", "start_offset_ms": 0, "direction": "threat"},
            {"id": "b", "start_offset_ms": 1, "direction": "challenge"},
            {"id": "c", "start_offset_ms": 2, "direction": "challenge"},
            {"id": "d", "start_offset_ms": 3, "direction": "threat"},
            {"id": "e", "start_offset_ms": 4, "direction": "challenge"},
        ]
        self.assertEqual(detect_breakthroughs(snips), {"b", "e"})

    def test_ambiguous_does_not_break_the_latch(self):
        # threat → ambiguous → challenge still counts the challenge.
        snips = [
            {"id": "a", "start_offset_ms": 0, "direction": "threat"},
            {"id": "x", "start_offset_ms": 1, "direction": "ambiguous"},
            {"id": "b", "start_offset_ms": 2, "direction": "challenge"},
        ]
        self.assertEqual(detect_breakthroughs(snips), {"b"})

    def test_sorts_by_time_not_input_order(self):
        snips = [
            {"id": "b", "start_offset_ms": 1000, "direction": "challenge"},
            {"id": "a", "start_offset_ms": 0, "direction": "threat"},
        ]
        self.assertEqual(detect_breakthroughs(snips), {"b"})

    def test_bad_input(self):
        self.assertEqual(detect_breakthroughs(None), set())
        self.assertEqual(detect_breakthroughs([]), set())


if __name__ == "__main__":
    unittest.main()
