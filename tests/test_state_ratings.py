"""willab — state-generic ternary ratings (SPEC.md v3 §3.2, §6, §17).

services/state_ratings.py.

WHAT THIS PINS DOWN:
  * the INSTRUMENT — three perceptual positions plus explicit uncertainty and
    technical-audio states, all stored without coercion;
  * STRICT TYPES — this is training data, so a truthy string is refused
    rather than coerced. A coerced value records a verdict no human gave and
    is indistinguishable from a real one afterwards;
  * the OPERATIONAL-DEFINITION GATE (§1.4) — a state with no written
    definition cannot be asked about, so validation refuses it;
  * LANE derivation — verified rating provenance, never clip source, decides
    whether a coach act is panel-grade. Seeded/historical rows remain
    `bootstrap` and cannot be reconstructed as human-panel evidence later;
  * AGGREGATION — bootstrap is excluded from the panel by default;
    `unrateable` rows are counted but never aggregated;
  * QUALITY — sample size DOMINATES agreement, by decision. A five-rater
    panel at 60% must outweigh a two-rater unanimous one, because the panel
    estimates a population percept and two people agreeing is a small sample,
    not a strong finding.

Run: python3 -m unittest tests.test_state_ratings
"""
from __future__ import annotations

import unittest

from services.state_ratings import (
    validate_rating,
)

if __name__ == "__main__":
    unittest.main()


class AnchoredSelfCheckTests(unittest.TestCase):
    """"Do you agree?" on the Confident Voice card (founder 2026-08-15).

    The card shows the machine's read and THEN asks. Its answer is routing to
    the Voice Album only; it must never enter the rating corpus."""

    def test_blind_is_the_DEFAULT_not_a_choice(self):
        # A caller that forgets gets the old, stricter behaviour. The only
        # way to record an anchored row is for a route to say so.
        row, err = validate_rating({"state_id": "confidence",
                                    "value": "yes"})
        self.assertIsNone(err)
        self.assertIs(row["saw_model_output"], False)
