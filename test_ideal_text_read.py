"""Unit tests for typed Ideal Text source and history contracts."""
from unittest import TestCase
from unittest.mock import Mock, patch

from services.ideal_text_read import (
    resolve_historical_read,
    resolve_live_text,
    resolve_ideal_text_source,
    resolve_suggestion_display,
)


class IdealTextSourceTests(TestCase):
    def test_auto_text_wins_and_keeps_version(self):
        result = resolve_ideal_text_source({
            "auto_text": " machine ",
            "text": "fallback",
            "version": 4,
        })

        self.assertEqual(result.machine_text, "machine")
        self.assertEqual(result.version, 4)

    def test_unowned_legacy_text_is_the_machine_fallback(self):
        result = resolve_ideal_text_source({"text": " legacy "})

        self.assertEqual(result.machine_text, "legacy")
        self.assertEqual(result.version, 1)

    def test_unverified_coach_work_never_becomes_machine_text(self):
        result = resolve_ideal_text_source({
            "text": "coach draft",
            "updated_by": "coach-1",
        })

        self.assertEqual(result.machine_text, "")
        self.assertIsNone(result.version)


class HistoricalIdealTextTests(TestCase):
    def test_absent_or_current_version_uses_live_view(self):
        database = Mock()

        self.assertIsNone(resolve_historical_read(
            "arc-1", None, 3, database=database
        ))
        self.assertIsNone(resolve_historical_read(
            "arc-1", "3", 3, database=database
        ))
        database.get_ideal_text_version.assert_not_called()

    def test_invalid_version_keeps_stable_error_contract(self):
        result = resolve_historical_read(
            "arc-1", "three", 3, database=Mock()
        )

        self.assertEqual(result.status, 400)
        self.assertEqual(result.payload, {
            "code": "INVALID_INPUT",
            "error": "version must be an integer",
        })

    def test_missing_snapshot_is_a_non_error_fallback(self):
        database = Mock()
        database.get_ideal_text_version.return_value = None

        result = resolve_historical_read(
            "arc-1", "2", 3, database=database
        )

        self.assertEqual(result.status, 200)
        self.assertEqual(result.payload, {
            "arc_id": "arc-1",
            "historical_unavailable": True,
            "requested_version": 2,
            "current_version": 3,
        })

    @patch("services.ideal_text_block.sanitize_markers")
    @patch("services.ideal_text_block.strip_moment_markers")
    @patch("services.ideal_text_block.extract_key_moments")
    def test_snapshot_preserves_only_frozen_anchor_metadata(
        self,
        extract_moments,
        strip_markers,
        sanitize_markers,
    ):
        database = Mock()
        database.get_ideal_text_version.return_value = {
            "text": "snapshot text",
            "created_at": "2026-08-01T10:00:00Z",
        }
        extract_moments.return_value = [{
            "snippet_id": "snippet-1",
            "anchor": "snapshot",
            "take_session_id": "session-1",
            "suggestion": {"kind": "replace"},
        }]
        strip_markers.return_value = "stripped"
        sanitize_markers.return_value = "sanitized"

        result = resolve_historical_read(
            "arc-1", "2", 3, database=database
        )

        self.assertEqual(result.status, 200)
        self.assertEqual(result.payload["text"], "sanitized")
        self.assertEqual(result.payload["key_moments"], [{
            "id": "snippet-1",
            "snippet_id": "snippet-1",
            "anchor": "snapshot",
            "take_session_id": "session-1",
        }])
        self.assertNotIn("suggestion", result.payload["key_moments"][0])


class LiveIdealTextTests(TestCase):
    def test_matching_coach_verification_wins_over_machine_copy(self):
        database = Mock()
        database.get_user_ideal_edit.return_value = None
        source = resolve_ideal_text_source({
            "auto_text": "machine",
            "version": 3,
            "verified_version": 3,
            "verified_text": " coach approved ",
        })

        result = resolve_live_text(
            "arc-1", "user-1", source, database=database
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.text, "coach approved")
        self.assertFalse(result.user_edited)

    def test_current_owner_edit_wins_without_changing_verified_status(self):
        database = Mock()
        database.get_user_ideal_edit.return_value = {
            "version": 3,
            "text": "my current wording",
        }
        source = resolve_ideal_text_source({
            "auto_text": "machine",
            "version": 3,
            "verified_version": 3,
            "verified_text": "coach approved",
        })

        result = resolve_live_text(
            "arc-1", "user-1", source, database=database
        )

        self.assertTrue(result.verified)
        self.assertTrue(result.user_edited)
        self.assertEqual(result.text, "my current wording")
        self.assertIsNone(result.prior_edit)

    def test_superseded_owner_edit_is_retained_for_legacy_reapply(self):
        database = Mock()
        database.get_user_ideal_edit.return_value = {
            "version": 2,
            "text": " my earlier wording ",
        }
        source = resolve_ideal_text_source({
            "auto_text": "new machine copy",
            "version": 3,
        })

        result = resolve_live_text(
            "arc-1", "user-1", source, database=database
        )

        self.assertFalse(result.user_edited)
        self.assertEqual(result.text, "new machine copy")
        self.assertEqual(result.prior_edit, {
            "text": "my earlier wording",
            "version": 2,
        })

    def test_boolean_edit_version_is_not_mistaken_for_integer_history(self):
        database = Mock()
        database.get_user_ideal_edit.return_value = {
            "version": True,
            "text": "legacy wording",
        }
        source = resolve_ideal_text_source({
            "auto_text": "machine",
            "version": 2,
        })

        result = resolve_live_text(
            "arc-1", "user-1", source, database=database
        )

        self.assertIsNone(result.prior_edit)

    def test_owner_edit_read_failure_remains_a_hard_read_failure(self):
        database = Mock()
        database.get_user_ideal_edit.side_effect = RuntimeError("db down")
        source = resolve_ideal_text_source({
            "auto_text": "machine",
            "version": 2,
        })

        with self.assertRaisesRegex(RuntimeError, "db down"):
            resolve_live_text(
                "arc-1", "user-1", source, database=database
            )


class SuggestionDisplayTests(TestCase):
    def test_disabled_lane_does_not_read_or_fold_suggestions(self):
        database = Mock()
        applied_lookup = Mock()
        fold_applied = Mock()

        result = resolve_suggestion_display(
            "arc-1",
            "original",
            False,
            database=database,
            suggestions_enabled=lambda: False,
            applied_lookup=applied_lookup,
            fold_applied=fold_applied,
        )

        self.assertFalse(result.enabled)
        self.assertEqual(result.text, "original")
        database.get_moment_suggestions_by_arc.assert_not_called()
        applied_lookup.assert_not_called()
        fold_applied.assert_not_called()

    @patch("services.ideal_text_block.extract_key_moments")
    def test_owner_whole_document_edit_remains_a_complete_star_fence(
        self,
        extract_moments,
    ):
        database = Mock()
        database.get_moment_suggestions_by_arc.return_value = {
            "snippet-1": {"kind": "replace", "replacement": "new"},
        }
        extract_moments.return_value = [{
            "snippet_id": "snippet-1",
            "take_session_id": "session-1",
        }]
        fold_applied = Mock()

        result = resolve_suggestion_display(
            "arc-1",
            "owner text",
            True,
            database=database,
            suggestions_enabled=lambda: True,
            applied_lookup=lambda _session_ids: {"snippet-1": True},
            fold_applied=fold_applied,
        )

        self.assertTrue(result.enabled)
        self.assertEqual(result.text, "owner text")
        fold_applied.assert_not_called()

    @patch(
        "services.ideal_decision_ledger.frozen_approved_replacement",
        return_value="frozen approved text",
    )
    @patch("services.ideal_decision_ledger.load_ledger")
    @patch("services.ideal_text_block.extract_key_moments")
    def test_applied_rewrite_folds_the_frozen_approved_version(
        self,
        extract_moments,
        load_ledger,
        frozen_replacement,
    ):
        database = Mock()
        suggestion = {"kind": "replace", "replacement": "latest draft"}
        database.get_moment_suggestions_by_arc.return_value = {
            "snippet-1": suggestion,
        }
        extract_moments.return_value = [{
            "snippet_id": "snippet-1",
            "take_session_id": "session-1",
        }]
        load_ledger.return_value = [{"decision": "approved"}]
        fold_applied = Mock(return_value="folded response")

        result = resolve_suggestion_display(
            "arc-1",
            "original",
            False,
            database=database,
            suggestions_enabled=lambda: True,
            applied_lookup=lambda _session_ids: {"snippet-1": True},
            fold_applied=fold_applied,
        )

        self.assertEqual(result.text, "folded response")
        frozen_replacement.assert_called_once_with(
            load_ledger.return_value, "snippet-1", suggestion
        )
        fold_applied.assert_called_once_with("original", [{
            "id": "snippet-1",
            "take_session_id": "session-1",
            "applied": True,
            "suggestion": {
                "kind": "replace",
                "replacement": "frozen approved text",
            },
        }])
