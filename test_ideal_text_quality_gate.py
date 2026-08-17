from __future__ import annotations

import unittest

from services.ideal_text_quality_gate import (
    prior_parts_text, validate_composed_text,
)


PARTS = [
    {"ord": 0, "text": "Locked opening stays exactly here.", "locked": True},
    {"ord": 1, "text": "An older unlocked middle paragraph.", "locked": False},
    {"ord": 2, "text": "A stable closing paragraph.", "locked": False},
]


class IdealTextQualityGateTests(unittest.TestCase):
    def test_a_clean_refresh_with_verbatim_lock_passes(self):
        text = ("Locked opening stays exactly here.\n\n"
                "A clearer unlocked middle paragraph.\n\n"
                "A stable closing paragraph.")
        self.assertTrue(validate_composed_text(text, PARTS)["ok"])

    def test_locked_text_change_fails(self):
        text = ("AI rewrote the locked opening.\n\n"
                "A clearer unlocked middle paragraph.\n\n"
                "A stable closing paragraph.")
        out = validate_composed_text(text, PARTS)
        self.assertFalse(out["ok"])
        self.assertIn("locked_text_changed", out["reasons"])

    def test_marker_leak_fails(self):
        text = ("Locked opening stays exactly here.\n\n"
                "{{orange:broken marker.\n\n"
                "A stable closing paragraph.")
        self.assertIn("marker_leak",
                      validate_composed_text(text, PARTS)["reasons"])

    def test_adjacent_duplicate_fails(self):
        text = ("Locked opening stays exactly here.\n\n"
                "Repeated paragraph words.\n\nRepeated paragraph words.")
        self.assertIn("adjacent_duplicate",
                      validate_composed_text(text, PARTS)["reasons"])

    def test_implausible_document_drift_fails(self):
        tiny = "Locked opening stays exactly here."
        self.assertIn("document_too_short",
                      validate_composed_text(tiny, PARTS)["reasons"])
        huge = "Locked opening stays exactly here.\n\n" + (
            "many generated words " * 30)
        self.assertIn("document_too_long",
                      validate_composed_text(huge, PARTS)["reasons"])

    def test_prior_fallback_preserves_order(self):
        shuffled = [PARTS[2], PARTS[0], PARTS[1]]
        self.assertEqual(
            prior_parts_text(shuffled),
            "\n\n".join(p["text"] for p in PARTS))

    def test_one_word_locked_paragraph_is_the_users_choice(self):
        parts = [{"ord": 0, "text": "Yes.", "locked": True},
                 {"ord": 1, "text": "Two words.", "locked": False}]
        self.assertTrue(validate_composed_text("Yes.\n\nTwo words.", parts)["ok"])


if __name__ == "__main__":
    unittest.main()
