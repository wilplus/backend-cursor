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


class ConfidenceGateTests(unittest.TestCase):
    # Readiness rig #3 — graduated autonomy (default-OFF).
    def test_no_gate_by_default_uses_shadow(self):
        # min_confidence=None → identical to before (shadow used regardless).
        self.assertEqual(resolve_direction(None, "challenge"), "challenge")
        self.assertEqual(
            resolve_direction(None, "challenge", shadow_confidence=0.1), "challenge")

    def test_high_confidence_shadow_passes_the_floor(self):
        self.assertEqual(
            resolve_direction(None, "challenge",
                              shadow_confidence=0.9, min_confidence=0.8),
            "challenge")

    def test_low_confidence_shadow_routes_to_human(self):
        # below the floor → None (no machine direction term; goes to the human).
        self.assertIsNone(
            resolve_direction(None, "challenge",
                              shadow_confidence=0.5, min_confidence=0.8))

    def test_missing_confidence_under_a_floor_is_dropped(self):
        self.assertIsNone(
            resolve_direction(None, "threat",
                              shadow_confidence=None, min_confidence=0.8))

    def test_coach_label_never_gated_by_confidence(self):
        # the coach always wins, regardless of any confidence floor.
        self.assertEqual(
            resolve_direction("challenge", "threat",
                              shadow_confidence=0.0, min_confidence=0.99),
            "challenge")


class IsChallengeTests(unittest.TestCase):
    def test_only_challenge_passes(self):
        self.assertTrue(is_challenge("challenge"))
        for d in ("threat", "ambiguous", None, ""):
            self.assertFalse(is_challenge(d), d)


class BreakthroughTests(unittest.TestCase):
    # founder 2026-06-26: a breakthrough = a coach `challenge` mark (the
    # threat→challenge-transition rule is retired). Every challenge counts.
    def test_every_challenge_is_a_breakthrough(self):
        snips = [
            {"id": "a", "start_offset_ms": 0, "direction": "threat"},
            {"id": "b", "start_offset_ms": 1000, "direction": "challenge"},
        ]
        self.assertEqual(detect_breakthroughs(snips), {"b"})

    def test_lone_challenge_with_no_prior_threat_now_counts(self):
        # the exact regression: a single coach challenge used to surface nothing.
        snips = [
            {"id": "a", "start_offset_ms": 0, "direction": "challenge"},
            {"id": "b", "start_offset_ms": 1000, "direction": "challenge"},
        ]
        self.assertEqual(detect_breakthroughs(snips), {"a", "b"})

    def test_threat_and_ambiguous_never_count(self):
        snips = [
            {"id": "a", "start_offset_ms": 0, "direction": "threat"},
            {"id": "x", "start_offset_ms": 1, "direction": "ambiguous"},
            {"id": "n", "start_offset_ms": 2, "direction": None},
            {"id": "b", "start_offset_ms": 3, "direction": "challenge"},
        ]
        self.assertEqual(detect_breakthroughs(snips), {"b"})

    def test_order_is_irrelevant(self):
        # no latch → input order has no effect.
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
