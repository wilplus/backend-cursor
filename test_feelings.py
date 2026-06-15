"""Pre-recording feeling taxonomy (willab U10). Pure validator — mirrors the
FE enum exactly.

Run: python3 -m unittest test_feelings
"""
from __future__ import annotations

import unittest

from services.feelings import (
    VALID_FEELINGS, normalize_feeling, shape_coach_feelings,
)


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


class ShapeCoachFeelingsTests(unittest.TestCase):
    def test_shapes_and_strips_internals(self):
        rows = [{"feeling": "calm", "take_index": 1, "created_at": "t1",
                 "recording_id": "r1", "session_id": "s1"}]
        out = shape_coach_feelings(rows)
        self.assertEqual(out, [{"feeling": "calm", "take_index": 1,
                                "captured_at": "t1"}])
        # internal keys must not leak to the coach payload
        self.assertNotIn("recording_id", out[0])
        self.assertNotIn("session_id", out[0])

    def test_ordered_by_take_then_time(self):
        rows = [
            {"feeling": "calm", "take_index": 3, "created_at": "t3"},
            {"feeling": "nervous", "take_index": 1, "created_at": "t1"},
            {"feeling": "excited", "take_index": 2, "created_at": "t2"},
        ]
        order = [r["feeling"] for r in shape_coach_feelings(rows)]
        self.assertEqual(order, ["nervous", "excited", "calm"])

    def test_drops_invalid_feeling_rows(self):
        rows = [{"feeling": "happy", "take_index": 1},   # not in enum
                {"feeling": "calm", "take_index": 2}]
        out = shape_coach_feelings(rows)
        self.assertEqual([r["feeling"] for r in out], ["calm"])

    def test_bad_input_is_empty(self):
        self.assertEqual(shape_coach_feelings(None), [])
        self.assertEqual(shape_coach_feelings("nope"), [])
        self.assertEqual(shape_coach_feelings([]), [])


if __name__ == "__main__":
    unittest.main()
