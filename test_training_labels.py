"""Unit tests for services.training_labels (design §14 private lane).

The direction-v1 validator + the §14 publish gate (every snippet
labeled). Pure module, no stubs.

Run: python3 -m unittest test_training_labels
"""
from __future__ import annotations

import unittest


class ValidatePublishLabelsTests(unittest.TestCase):

    def _v(self, labels, required):
        from services.training_labels import validate_publish_labels
        return validate_publish_labels(labels, set(required))

    def test_happy_every_snippet_labeled(self):
        out = self._v(
            [
                {"snippet_id": "a", "value": "challenge"},
                {"snippet_id": "b", "value": "threat",
                 "was_pre_filled": True, "was_overridden": True},
            ],
            {"a", "b"},
        )
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["schema_version"], "direction-v1")
        self.assertEqual(out[1]["value"], "threat")
        self.assertTrue(out[1]["was_overridden"])

    def test_flags_default_false(self):
        out = self._v([{"snippet_id": "a", "value": "ambiguous"}], {"a"})
        self.assertFalse(out[0]["was_pre_filled"])
        self.assertFalse(out[0]["was_overridden"])

    def test_all_three_values_valid(self):
        for v in ("threat", "ambiguous", "challenge"):
            out = self._v([{"snippet_id": "a", "value": v}], {"a"})
            self.assertEqual(out[0]["value"], v)

    # ── the §14 gate ──────────────────────────────────────────────

    def test_unlabeled_snippet_rejected(self):
        from services.training_labels import TrainingLabelError
        with self.assertRaises(TrainingLabelError) as cm:
            self._v([{"snippet_id": "a", "value": "threat"}], {"a", "b"})
        self.assertIn("every snippet", str(cm.exception).lower())

    def test_empty_session_empty_labels_ok(self):
        # no snippets → no labels required
        self.assertEqual(self._v([], set()), [])

    # ── per-entry validation ──────────────────────────────────────

    def test_bad_value_rejected(self):
        from services.training_labels import TrainingLabelError
        with self.assertRaises(TrainingLabelError):
            self._v([{"snippet_id": "a", "value": "stressed"}], {"a"})

    def test_non_bool_flag_rejected(self):
        from services.training_labels import TrainingLabelError
        with self.assertRaises(TrainingLabelError):
            self._v([{"snippet_id": "a", "value": "threat",
                      "was_overridden": "yes"}], {"a"})

    def test_label_for_unknown_snippet_rejected(self):
        from services.training_labels import TrainingLabelError
        with self.assertRaises(TrainingLabelError) as cm:
            self._v([{"snippet_id": "ghost", "value": "threat"}], {"a"})
        self.assertIn("not a snippet", str(cm.exception).lower())

    def test_duplicate_snippet_rejected(self):
        from services.training_labels import TrainingLabelError
        with self.assertRaises(TrainingLabelError) as cm:
            self._v([
                {"snippet_id": "a", "value": "threat"},
                {"snippet_id": "a", "value": "challenge"},
            ], {"a"})
        self.assertIn("duplicate", str(cm.exception).lower())

    def test_missing_snippet_id_rejected(self):
        from services.training_labels import TrainingLabelError
        with self.assertRaises(TrainingLabelError):
            self._v([{"value": "threat"}], {"a"})

    def test_non_list_rejected(self):
        from services.training_labels import TrainingLabelError
        for bad in (None, "x", 42, {"snippet_id": "a"}):
            with self.assertRaises(TrainingLabelError):
                self._v(bad, {"a"})

    def test_schema_version_constant(self):
        from services.training_labels import SCHEMA_VERSION, VALID_VALUES
        self.assertEqual(SCHEMA_VERSION, "direction-v1")
        self.assertEqual(set(VALID_VALUES), {"threat", "ambiguous", "challenge"})


if __name__ == "__main__":
    unittest.main()
