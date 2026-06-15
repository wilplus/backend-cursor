"""Pre-recording feeling taxonomy (willab U10). Pure validator — mirrors the
FE enum exactly.

Run: python3 -m unittest test_feelings
"""
from __future__ import annotations

import unittest

from services.feelings import VALID_FEELINGS, normalize_feeling


class FeelingTests(unittest.TestCase):
    def test_enum_matches_fe_exactly(self):
        # Lock-step with src/components/willab/willabFeelings.ts.
        self.assertEqual(
            set(VALID_FEELINGS), {"nervous", "excited", "calm", "unsure"},
        )

    def test_valid_values_pass(self):
        for v in VALID_FEELINGS:
            self.assertEqual(normalize_feeling(v), v)

    def test_case_and_whitespace_normalised(self):
        self.assertEqual(normalize_feeling("  Nervous "), "nervous")
        self.assertEqual(normalize_feeling("CALM"), "calm")

    def test_unknown_is_dropped_not_coerced(self):
        for v in ("happy", "anxious", "scared", "", "  ", "nervou"):
            self.assertIsNone(normalize_feeling(v), v)

    def test_non_string_is_none(self):
        for v in (None, 3, ["calm"], {"feeling": "calm"}):
            self.assertIsNone(normalize_feeling(v))


if __name__ == "__main__":
    unittest.main()
