"""Unit tests for the intake-context validator + snapshot helper.

Covers the acceptance shape from the FE spec:
  - validation bounds (200-char max on text, 30..7200 seconds on int)
  - whitespace normalisation (empty-after-trim → None)
  - bool sneaking in where int is expected
  - canonical 3-key shape on return
  - snapshot helper returns None gracefully when column unset
  - snapshot helper normalises away any extra keys from a poisoned blob

Stub services.db (in setUpModule) so we don't need the supabase venv.

Run: python3 -m unittest test_intake_context
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# services.db pulls in supabase/postgrest, which aren't in the test
# image, so we stub it — in setUpModule, NOT at import time. A stub
# left in sys.modules at import time leaks into sibling test modules:
# test_homework_regressions decides at import time whether the real
# services.db is importable, and a leaked stub makes it run against
# the fake instead of skipping. tearDownModule restores the state.
_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


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
            "domain_vocabulary": ["keynote", "podium"],
        })
        self.assertEqual(out, {
            "topic": "Q3 product launch",
            "audience": "Engineering team",
            "target_length_seconds": 600,
            "domain_vocabulary": ["keynote", "podium"],
            "slides": None,
            "presentation_ref": None,
            "slide_advances": None,
            "strategic_context": None,
        })

    def test_empty_body_returns_all_nulls(self):
        out = self._validate({})
        self.assertEqual(out, {
            "topic": None,
            "audience": None,
            "target_length_seconds": None,
            "domain_vocabulary": None,
            "slides": None,
            "presentation_ref": None,
            "slide_advances": None,
            "strategic_context": None,
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

    def test_canonical_keys_always_present(self):
        """Even when the body has only one key, the returned dict has all
        canonical keys (willab beta added domain_vocabulary; UX Wave 4 added
        slides / presentation_ref / slide_advances)."""
        out = self._validate({"target_length_seconds": 60})
        self.assertEqual(
            set(out.keys()),
            {"topic", "audience", "target_length_seconds", "domain_vocabulary",
             "slides", "presentation_ref", "slide_advances",
             "strategic_context"},
        )

    # ── strategic_context (④ step 5, 2026-07-24) ───────────────────

    def test_strategic_context_passes_and_trims(self):
        out = self._validate({"topic": "t",
                              "strategic_context": "  board wants the raise  "})
        self.assertEqual(out["strategic_context"], "board wants the raise")

    def test_strategic_context_absent_is_none(self):
        self.assertIsNone(self._validate({"topic": "t"})["strategic_context"])

    def test_strategic_context_whitespace_only_collapses_to_none(self):
        out = self._validate({"strategic_context": "   "})
        self.assertIsNone(out["strategic_context"])

    def test_strategic_context_allows_a_sentence_past_the_tag_cap(self):
        # Longer than the 200-char tag cap — it's a note, not a label.
        note = "x" * 500
        self.assertEqual(self._validate(
            {"strategic_context": note})["strategic_context"], note)

    def test_strategic_context_over_2000_chars_rejected(self):
        from services.intake_context import (
            validate_intake_context_body, IntakeContextError,
        )
        with self.assertRaises(IntakeContextError):
            validate_intake_context_body({"strategic_context": "x" * 2001})

    def test_strategic_context_non_string_rejected(self):
        from services.intake_context import (
            validate_intake_context_body, IntakeContextError,
        )
        with self.assertRaises(IntakeContextError):
            validate_intake_context_body({"strategic_context": 42})

    # ── domain_vocabulary (willab beta §4) ─────────────────────────

    def test_vocab_list_passes_and_dedupes(self):
        out = self._validate({"domain_vocabulary": [
            "keynote", "  podium ", "keynote", "Q&A",
        ]})
        # trimmed, case-insensitive de-dupe preserving order
        self.assertEqual(out["domain_vocabulary"], ["keynote", "podium", "Q&A"])

    def test_vocab_absent_is_none(self):
        out = self._validate({"topic": "x"})
        self.assertIsNone(out["domain_vocabulary"])

    def test_vocab_empty_list_collapses_to_none(self):
        out = self._validate({"domain_vocabulary": ["", "   "]})
        self.assertIsNone(out["domain_vocabulary"])

    def test_vocab_non_list_rejected(self):
        from services.intake_context import IntakeContextError
        with self.assertRaises(IntakeContextError):
            self._validate({"domain_vocabulary": "keynote"})

    def test_vocab_non_string_item_rejected(self):
        from services.intake_context import IntakeContextError
        with self.assertRaises(IntakeContextError):
            self._validate({"domain_vocabulary": ["ok", 42]})

    def test_vocab_too_many_terms_rejected(self):
        from services.intake_context import IntakeContextError, _MAX_VOCAB_TERMS
        with self.assertRaises(IntakeContextError):
            self._validate({"domain_vocabulary": [
                f"term{i}" for i in range(_MAX_VOCAB_TERMS + 1)
            ]})

    def test_vocab_over_long_term_rejected(self):
        from services.intake_context import (
            IntakeContextError, _MAX_VOCAB_TERM_LEN,
        )
        with self.assertRaises(IntakeContextError):
            self._validate({"domain_vocabulary": ["x" * (_MAX_VOCAB_TERM_LEN + 1)]})

    # ── require_topic (willab §3.2 / §5.10) ────────────────────────

    def test_require_topic_rejects_missing(self):
        from services.intake_context import (
            validate_intake_context_body, IntakeContextError,
        )
        with self.assertRaises(IntakeContextError) as cm:
            validate_intake_context_body({"audience": "team"}, require_topic=True)
        self.assertIn("topic", str(cm.exception))

    def test_require_topic_rejects_empty(self):
        from services.intake_context import (
            validate_intake_context_body, IntakeContextError,
        )
        with self.assertRaises(IntakeContextError):
            validate_intake_context_body({"topic": "   "}, require_topic=True)

    def test_require_topic_passes_with_topic(self):
        from services.intake_context import validate_intake_context_body
        out = validate_intake_context_body(
            {"topic": "Q3 launch"}, require_topic=True,
        )
        self.assertEqual(out["topic"], "Q3 launch")

    def test_require_topic_default_off_preserves_legacy(self):
        """Default (no require_topic) still accepts a topic-less body."""
        from services.intake_context import validate_intake_context_body
        out = validate_intake_context_body({"audience": "team"})
        self.assertIsNone(out["topic"])

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

    def test_normalises_canonical_keys(self):
        """A poisoned blob with extra keys gets normalized down to
        the canonical 4-key shape — consumers can assume the
        contract holds regardless of what's in JSONB."""
        from services import intake_context as mod
        from services.db import db
        poisoned = {
            "topic": "real topic",
            "audience": None,
            "target_length_seconds": 120,
            "domain_vocabulary": ["keynote"],
            "EXTRA_KEY": "should be dropped",
            "another": 42,
        }
        with patch.object(
            db, "get_session_intake_context", return_value=poisoned,
        ):
            out = mod.snapshot_intake_context("sid-x")
        self.assertEqual(set(out.keys()), {
            "topic", "audience", "target_length_seconds", "domain_vocabulary",
            "slides", "presentation_ref", "slide_advances",
            "strategic_context",
        })
        self.assertEqual(out["topic"], "real topic")
        self.assertIsNone(out["audience"])
        self.assertEqual(out["target_length_seconds"], 120)
        self.assertEqual(out["domain_vocabulary"], ["keynote"])

    def test_missing_keys_normalize_to_none(self):
        """A row that only has `topic` set still returns the full canonical
        dict with None for the others."""
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
            "domain_vocabulary": None,
            "slides": None,
            "presentation_ref": None,
            "slide_advances": None,
            "strategic_context": None,
        })


if __name__ == "__main__":
    unittest.main()
