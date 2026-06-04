"""Unit tests for services.next_session_icebreaker (Task 10).

Covers the validator + status-derivation logic that the admin
endpoints lean on. The LLM call is NOT exercised — that's the
integration-test surface, and it would require a real OpenAI key.
The generator's structural behaviour (overwrite short-circuit,
error tagging on missing signal) IS exercised via DB mocks.

Run: python3 -m unittest test_next_session_icebreaker
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
def setUpModule():
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    sys.modules.pop("services.db", None)


class ValidatorTests(unittest.TestCase):

    def _validate(self, body):
        from services.next_session_icebreaker import (
            validate_icebreaker_body,
        )
        return validate_icebreaker_body(body)

    # ── Happy paths ────────────────────────────────────────────────

    def test_well_formed_question_passes(self):
        out = self._validate({
            "question": "What surprised you about presenting last week?",
        })
        self.assertEqual(
            out, "What surprised you about presenting last week?",
        )

    def test_empty_string_returns_none_sentinel(self):
        """Empty save = skip signal (caller maps to status='skipped')."""
        self.assertIsNone(self._validate({"question": ""}))

    def test_whitespace_only_returns_none_sentinel(self):
        self.assertIsNone(self._validate({"question": "   \n\t  "}))

    def test_trims_outer_whitespace(self):
        out = self._validate({"question": "  Hello there?  "})
        self.assertEqual(out, "Hello there?")

    def test_collapses_newlines_to_spaces(self):
        """Single-line UX — internal newlines become single spaces."""
        out = self._validate({
            "question": "What did you\nthink of\nthat moment?",
        })
        self.assertEqual(out, "What did you think of that moment?")

    def test_collapses_runs_of_whitespace(self):
        out = self._validate({
            "question": "What   surprised\t\tyou   most?",
        })
        self.assertEqual(out, "What surprised you most?")

    # ── Bound checks ───────────────────────────────────────────────

    def test_under_min_length_rejected(self):
        from services.next_session_icebreaker import (
            IcebreakerValidationError,
        )
        with self.assertRaises(IcebreakerValidationError) as cm:
            self._validate({"question": "Hi?"})
        self.assertIn("5", str(cm.exception))

    def test_min_length_inclusive(self):
        # Below the floor: "Hey?" is 4 chars — raises.
        from services.next_session_icebreaker import (
            IcebreakerValidationError,
        )
        with self.assertRaises(IcebreakerValidationError):
            self._validate({"question": "Hey?"})
        # At the floor: 5 chars including the '?'.
        out = self._validate({"question": "Hey ?"})
        self.assertEqual(out, "Hey ?")

    def test_over_max_length_rejected(self):
        from services.next_session_icebreaker import (
            IcebreakerValidationError, MAX_QUESTION_LEN,
        )
        # 281 chars total: 280 'x' + '?' = 281 — but we need it to NOT
        # end with '?' validator-friendly. Build 281 chars ending '?'.
        long = ("x" * (MAX_QUESTION_LEN)) + "?"  # 281 chars
        with self.assertRaises(IcebreakerValidationError) as cm:
            self._validate({"question": long})
        self.assertIn(str(MAX_QUESTION_LEN), str(cm.exception))

    def test_at_max_length_accepted(self):
        from services.next_session_icebreaker import MAX_QUESTION_LEN
        # Exactly MAX_QUESTION_LEN chars ending '?'
        s = ("x" * (MAX_QUESTION_LEN - 1)) + "?"
        out = self._validate({"question": s})
        self.assertEqual(len(out), MAX_QUESTION_LEN)

    # ── Trailing '?' hard-fail ──────────────────────────────────────

    def test_missing_trailing_question_mark_rejected(self):
        """FE handoff Q4 — hard-fail 422."""
        from services.next_session_icebreaker import (
            IcebreakerValidationError,
        )
        with self.assertRaises(IcebreakerValidationError) as cm:
            self._validate({"question": "What did you think of that"})
        self.assertIn("?", str(cm.exception))

    def test_ends_with_period_rejected(self):
        from services.next_session_icebreaker import (
            IcebreakerValidationError,
        )
        with self.assertRaises(IcebreakerValidationError):
            self._validate({"question": "What did you think of that."})

    def test_question_mark_with_trailing_whitespace_accepted(self):
        """Trim happens before the '?' check — trailing whitespace
        after the question mark should still be accepted."""
        out = self._validate({"question": "What surprised you?   "})
        self.assertEqual(out, "What surprised you?")

    # ── Type rejection ─────────────────────────────────────────────

    def test_non_dict_body_rejected(self):
        from services.next_session_icebreaker import (
            IcebreakerValidationError,
        )
        for bad in ["string", 42, [1, 2, 3], None]:
            with self.assertRaises(IcebreakerValidationError):
                self._validate(bad)

    def test_missing_question_key_rejected(self):
        from services.next_session_icebreaker import (
            IcebreakerValidationError,
        )
        with self.assertRaises(IcebreakerValidationError) as cm:
            self._validate({"other_key": "hello?"})
        self.assertIn("required", str(cm.exception).lower())

    def test_question_non_string_rejected(self):
        from services.next_session_icebreaker import (
            IcebreakerValidationError,
        )
        for bad in [42, 60.5, ["q?"], {"nested": "q?"}, True]:
            with self.assertRaises(IcebreakerValidationError):
                self._validate({"question": bad})


class QueueStatusDerivationTests(unittest.TestCase):
    """The 5-state public enum vs the 3-state DB column + draft/error
    flags. The truth table the route layer relies on."""

    def _derive(self, **row):
        from services.next_session_icebreaker import derive_queue_status
        has_next = row.pop("_has_next", False)
        return derive_queue_status(row, has_next_session=has_next)

    def test_no_draft_no_error_is_not_yet_generated(self):
        self.assertEqual(self._derive(), "not_yet_generated")

    def test_no_draft_with_error_still_not_yet_generated(self):
        """The error flag is surfaced via generation_error in the GET
        payload — it doesn't get its own queue_status. FE renders the
        red banner when ai_draft IS NULL AND generation_error IS NOT
        NULL."""
        self.assertEqual(
            self._derive(
                next_session_icebreaker_generation_error="llm_unavailable",
            ),
            "not_yet_generated",
        )

    def test_draft_pending_no_next_session_is_pending_next(self):
        self.assertEqual(
            self._derive(
                next_session_icebreaker_ai_draft="What did you think?",
                next_session_icebreaker_status="pending",
            ),
            "pending_next_session",
        )

    def test_draft_pending_with_next_session_is_queued(self):
        self.assertEqual(
            self._derive(
                next_session_icebreaker_ai_draft="What did you think?",
                next_session_icebreaker_status="pending",
                _has_next=True,
            ),
            "queued",
        )

    def test_draft_skipped_is_skipped(self):
        self.assertEqual(
            self._derive(
                next_session_icebreaker_ai_draft="What did you think?",
                next_session_icebreaker_status="skipped",
            ),
            "skipped",
        )

    def test_draft_delivered_is_delivered(self):
        self.assertEqual(
            self._derive(
                next_session_icebreaker_ai_draft="What did you think?",
                next_session_icebreaker_status="delivered",
                _has_next=True,
            ),
            "delivered",
        )

    def test_whitespace_only_draft_treated_as_no_draft(self):
        self.assertEqual(
            self._derive(
                next_session_icebreaker_ai_draft="   \n  ",
                next_session_icebreaker_status="pending",
            ),
            "not_yet_generated",
        )

    def test_missing_status_defaults_to_pending(self):
        """Defensive — a row with ai_draft set but no status column
        value should still derive a useful state (not crash)."""
        self.assertEqual(
            self._derive(
                next_session_icebreaker_ai_draft="What did you think?",
            ),
            "pending_next_session",
        )


class GeneratorStructuralTests(unittest.TestCase):
    """Generator behaviour around the DB hooks. LLM call is mocked."""

    def test_existing_draft_short_circuits_when_overwrite_false(self):
        from services import next_session_icebreaker as mod
        from services.db import db

        # v2_get_session_by_id returns a row that already has a draft.
        with patch.object(
            db, "v2_get_session_by_id",
            return_value={
                "id": "sid-x",
                "next_session_icebreaker_ai_draft": "Existing question?",
            },
        ):
            out = mod.generate_next_session_icebreaker(
                "sid-x", overwrite=False,
            )
        self.assertEqual(out, "Existing question?")

    def test_existing_draft_overridden_when_overwrite_true(self):
        """overwrite=True triggers a fresh LLM call even when a draft
        already exists. We don't exercise the LLM — but we can verify
        the short-circuit path is NOT taken by checking that the LLM
        helper is called."""
        from services import next_session_icebreaker as mod
        from services.db import db

        with patch.object(
            db, "v2_get_session_by_id",
            return_value={
                "id": "sid-x",
                "user_id": "uid-1",
                "next_session_icebreaker_ai_draft": "Existing question?",
            },
        ), patch.object(
            db, "get_snippets_by_session",
            return_value=[
                {
                    "transcript": "I felt nervous about the demo.",
                    "admin_comment": "Solid pacing.",
                },
            ],
        ), patch.object(
            db, "clear_next_session_icebreaker_generation_error",
            return_value=True,
        ), patch.object(
            mod, "_llm_generate_question",
            return_value="What changed about the demo since then?",
        ), patch.object(
            db, "set_next_session_icebreaker_ai_draft",
            return_value=True,
        ):
            out = mod.generate_next_session_icebreaker(
                "sid-x", overwrite=True,
            )
        # The mocked LLM helper's return value wins, not the prior draft.
        self.assertEqual(out, "What changed about the demo since then?")

    def test_no_usable_signal_tags_transcript_too_short(self):
        from services import next_session_icebreaker as mod
        from services.db import db

        with patch.object(
            db, "v2_get_session_by_id",
            return_value={"id": "sid-x", "user_id": "uid-1"},
        ), patch.object(
            db, "get_snippets_by_session",
            return_value=[
                {"transcript": "", "admin_comment": ""},
                {"transcript": "   ", "admin_comment": "  "},
            ],
        ), patch.object(
            db, "set_next_session_icebreaker_generation_error",
            return_value=True,
        ) as mock_err_set:
            out = mod.generate_next_session_icebreaker("sid-x")

        self.assertIsNone(out)
        mock_err_set.assert_called_once()
        _, kwargs = mock_err_set.call_args
        self.assertEqual(kwargs.get("error_tag"), "transcript_too_short")

    def test_llm_failure_tags_llm_unavailable(self):
        from services import next_session_icebreaker as mod
        from services.db import db

        with patch.object(
            db, "v2_get_session_by_id",
            return_value={"id": "sid-x", "user_id": "uid-1"},
        ), patch.object(
            db, "get_snippets_by_session",
            return_value=[
                {
                    "transcript": "Some content.",
                    "admin_comment": "Coach observation.",
                },
            ],
        ), patch.object(
            mod, "_llm_generate_question", return_value=None,
        ), patch.object(
            db, "set_next_session_icebreaker_generation_error",
            return_value=True,
        ) as mock_err_set:
            out = mod.generate_next_session_icebreaker("sid-x")

        self.assertIsNone(out)
        mock_err_set.assert_called_once()
        _, kwargs = mock_err_set.call_args
        self.assertEqual(kwargs.get("error_tag"), "llm_unavailable")

    def test_session_not_found_returns_none(self):
        from services import next_session_icebreaker as mod
        from services.db import db

        with patch.object(
            db, "v2_get_session_by_id", return_value=None,
        ):
            self.assertIsNone(
                mod.generate_next_session_icebreaker("sid-missing"),
            )

    def test_oversized_llm_output_clamped(self):
        """Defensive — model occasionally exceeds maxLength despite
        the schema. The clamp should cut at the last space before
        the cap and re-append '?'."""
        from services import next_session_icebreaker as mod
        from services.db import db

        # Build a fake LLM output that exceeds MAX_QUESTION_LEN.
        overflow = (
            "What did you think about the moment when you started "
            "to feel more confident "
            * 10
        ) + "?"
        self.assertGreater(len(overflow), mod.MAX_QUESTION_LEN)

        with patch.object(
            db, "v2_get_session_by_id",
            return_value={"id": "sid-x", "user_id": "uid-1"},
        ), patch.object(
            db, "get_snippets_by_session",
            return_value=[
                {
                    "transcript": "ok.",
                    "admin_comment": "ok.",
                },
            ],
        ), patch.object(
            mod, "_llm_generate_question", return_value=overflow,
        ), patch.object(
            db, "set_next_session_icebreaker_ai_draft",
            return_value=True,
        ):
            out = mod.generate_next_session_icebreaker("sid-x")

        self.assertIsNotNone(out)
        self.assertLessEqual(len(out), mod.MAX_QUESTION_LEN)
        self.assertTrue(out.endswith("?"))


if __name__ == "__main__":
    unittest.main()
