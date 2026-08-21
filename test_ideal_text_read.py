"""Unit tests for typed Ideal Text source and history contracts."""
from unittest import TestCase
from unittest.mock import Mock, patch

from services.ideal_text_read import (
    resolve_historical_read,
    resolve_ideal_text_source,
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
