"""Unit tests for the intake-context validator + snapshot helper.

Covers the acceptance shape from the FE spec:
  - validation bounds (200-char max on text, 30..7200 seconds on int)
  - whitespace normalisation (empty-after-trim → None)
  - bool sneaking in where int is expected
  - canonical 3-key shape on return
  - snapshot helper returns None gracefully when column unset
  - snapshot helper normalises away any extra keys from a poisoned blob

Stub services.db at import time so we don't need the supabase venv.

Run: python3 -m unittest test_intake_context
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# Stub services.db before importing the module under test.
_stub_db_module = types.ModuleType("services.db")
_stub_db_module.db = MagicMock()
sys.modules.setdefault("services.db", _stub_db_module)


class ValidatorTests(unittest.TestCase):

    def _validate(self, body):
        from services.intake_context import validate_intake_context_body
        return validate_intake_context_body(body)

    # ── Happy paths ────────────────────────────────────────────────

    def test_full_body_passes(self):
        out = self._validate({
            "topic": "Q3 product launch",
            "audience": "Engineering team",
            "target_length_seconds": 600,
        })
        self.assertEqual(out, {
            "topic": "Q3 product launch",
            "audience": "Engineering team",
            "target_length_seconds": 600,
        })

    def test_empty_body_returns_all_nulls(self):
        out = self._validate({})
        self.assertEqual(out, {
            "topic": None,
            "audience": None,
            "target_length_seconds": None,
        })

    def test_partial_body_fills_missing_with_null(self):
        out = self._validate({"topic": "hello"})
        self.assertEqual(out["topic"], "hello")
        self.assertIsNone(out["audience"])
        self.assertIsNone(out["target_length_seconds"])

    def test_explicit_null_passes_as_null(self):
        out = self._validate({"topic": None, "audience": None})
        self.assertIsNone(out["topic"])
        self.assertIsNone(out["audience"])

    def test_canonical_three_keys_always_present(self):
        """Even when the body has only one of three keys, the
        returned dict has all three."""
        out = self._validate({"target_length_seconds": 60})
        self.assertEqual(
            set(out.keys()),
            {"topic", "audience", "target_length_seconds"},
        )

    # ── Whitespace normalisation ───────────────────────────────────

    def test_whitespace_only_text_becomes_null(self):
        out = self._validate({"topic": "   ", "audience": "\n\t  "})
        self.assertIsNone(out["topic"])
        self.assertIsNone(out["audience"])

    def test_trims_outer_whitespace(self):
        out = self._validate({"topic": "  trimmed  "})
        self.assertEqual(out["topic"], "trimmed")

    # ── Bound checks ───────────────────────────────────────────────

    def test_topic_over_200_chars_rejected(self):
        from services.intake_context import IntakeContextError
        with self.assertRaises(IntakeContextError) as cm:
            self._validate({"topic": "x" * 201})
        self.assertIn("200 characters", str(cm.exception))
        self.assertIn("topic", str(cm.exception))

    def test_topic_exactly_200_chars_accepted(self):
        out = self._validate({"topic": "x" * 200})
        self.assertEqual(out["topic"], "x" * 200)

    def test_audience_over_200_chars_rejected(self):
        from services.intake_context import IntakeContextError
        with self.assertRaises(IntakeContextError):
            self._validate({"audience": "x" * 201})

    def test_target_seconds_at_min_accepted(self):
        out = self._validate({"target_length_seconds": 30})
        self.assertEqual(out["target_length_seconds"], 30)

    def test_target_seconds_at_max_accepted(self):
        out = self._validate({"target_length_seconds": 7200})
        self.assertEqual(out["target_length_seconds"], 7200)

    def test_target_seconds_below_min_rejected(self):
        from services.intake_context import IntakeContextError
        with self.assertRaises(IntakeContextError) as cm:
            self._validate({"target_length_seconds": 29})
        self.assertIn("30", str(cm.exception))
        self.assertIn("7200", str(cm.exception))

    def test_target_seconds_above_max_rejected(self):
        from services.intake_context import IntakeContextError
        with self.assertRaises(IntakeContextError):
            self._validate({"target_length_seconds": 7201})

    # ── Type rejection ─────────────────────────────────────────────

    def test_non_dict_body_rejected(self):
        from services.intake_context import IntakeContextError
        for bad in ["string", 42, [1, 2, 3], None]:
            with self.assertRaises(IntakeContextError):
                self._validate(bad)

    def test_topic_non_string_rejected(self):
        from services.intake_context import IntakeContextError
        with self.assertRaises(IntakeContextError):
            self._validate({"topic": 42})

    def test_target_seconds_non_int_rejected(self):
        from services.intake_context import IntakeContextError
        for bad in ["120", 60.5, [60]]:
            with self.assertRaises(IntakeContextError):
                self._validate({"target_length_seconds": bad})

    def test_target_seconds_bool_rejected(self):
        """Python's bool-is-int trick must not let True/False
        through as 1/0 — those would silently fall under the
        min-30 bound check and error out anyway, but reject up
        front so the error message is honest about the type."""
        from services.intake_context import IntakeContextError
        with self.assertRaises(IntakeContextError) as cm:
            self._validate({"target_length_seconds": True})
        self.assertIn("integer", str(cm.exception))


class SnapshotHelperTests(unittest.TestCase):

    def test_returns_none_when_column_unset(self):
        from services import intake_context as mod
        from services.db import db
        with patch.object(
            db, "get_session_intake_context", return_value=None,
        ):
            out = mod.snapshot_intake_context("sid-x")
        self.assertIsNone(out)

    def test_normalises_three_keys(self):
        """A poisoned blob with extra keys gets normalized down to
        the canonical 3-key shape — consumers can assume the
        contract holds regardless of what's in JSONB."""
        from services import intake_context as mod
        from services.db import db
        poisoned = {
            "topic": "real topic",
            "audience": None,
            "target_length_seconds": 120,
            "EXTRA_KEY": "should be dropped",
            "another": 42,
        }
        with patch.object(
            db, "get_session_intake_context", return_value=poisoned,
        ):
            out = mod.snapshot_intake_context("sid-x")
        self.assertEqual(set(out.keys()), {
            "topic", "audience", "target_length_seconds",
        })
        self.assertEqual(out["topic"], "real topic")
        self.assertIsNone(out["audience"])
        self.assertEqual(out["target_length_seconds"], 120)

    def test_missing_keys_normalize_to_none(self):
        """A row that only has `topic` set still returns the
        3-key dict with None for the other two."""
        from services import intake_context as mod
        from services.db import db
        with patch.object(
            db, "get_session_intake_context", return_value={"topic": "x"},
        ):
            out = mod.snapshot_intake_context("sid-x")
        self.assertEqual(out, {
            "topic": "x",
            "audience": None,
            "target_length_seconds": None,
        })


if __name__ == "__main__":
    unittest.main()
