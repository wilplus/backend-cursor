"""Unit tests for recording-time project identity and retry guards."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.lab_project_identity import (
    ProjectSelection,
    ensure_presentation_unchanged,
    find_duplicate_upload,
    validate_project_selection,
)
from services.lab_recording_intake import RecordingIntakeError


ARC = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
USER = "user-1"


def _valid_uuid(value: str) -> bool:
    return value == ARC


class ProjectSelectionTests(unittest.TestCase):

    def test_new_project_has_no_explicit_arc_and_does_not_touch_database(self):
        database = MagicMock()
        selection = validate_project_selection(
            {"project_intent": "new"},
            user_id=USER,
            database=database,
            is_valid_uuid=_valid_uuid,
        )
        self.assertEqual(selection.intent, "new")
        self.assertIsNone(selection.explicit_arc_id)
        self.assertEqual(selection.explicit_arc_sessions, ())
        database.get_arc_sessions.assert_not_called()

    def test_invalid_identity_contract_keeps_the_generic_client_error(self):
        with self.assertRaises(RecordingIntakeError) as raised:
            validate_project_selection(
                {"project_intent": "continue"},
                user_id=USER,
                database=MagicMock(),
                is_valid_uuid=_valid_uuid,
            )
        self.assertEqual(raised.exception.status, 400)
        self.assertEqual(raised.exception.message, "Something went wrong on our end.")

    def test_malformed_explicit_arc_is_rejected_before_database_lookup(self):
        database = MagicMock()
        with self.assertRaises(RecordingIntakeError) as raised:
            validate_project_selection(
                {"continue_arc_id": "bad"},
                user_id=USER,
                database=database,
                is_valid_uuid=_valid_uuid,
            )
        self.assertEqual(raised.exception.status, 400)
        database.get_arc_sessions.assert_not_called()

    def test_explicit_arc_requires_authenticated_ownership(self):
        for caller, owner in ((None, USER), (USER, "someone-else")):
            database = MagicMock()
            database.get_arc_sessions.return_value = [{"user_id": owner}]
            with self.subTest(caller=caller, owner=owner), self.assertRaises(
                RecordingIntakeError
            ) as raised:
                validate_project_selection(
                    {"continue_arc_id": ARC},
                    user_id=caller,
                    database=database,
                    is_valid_uuid=_valid_uuid,
                )
            self.assertEqual(raised.exception.code, "NOT_FOUND")
            self.assertEqual(raised.exception.status, 404)

    def test_owned_arc_carries_its_sessions_to_the_deck_guard(self):
        sessions = [{"id": "take-1", "user_id": USER}]
        database = MagicMock()
        database.get_arc_sessions.return_value = sessions

        selection = validate_project_selection(
            {"project_intent": "continue", "continue_arc_id": ARC},
            user_id=USER,
            database=database,
            is_valid_uuid=_valid_uuid,
        )

        self.assertEqual(selection.intent, "continue")
        self.assertEqual(selection.explicit_arc_id, ARC)
        self.assertEqual(selection.explicit_arc_sessions, tuple(sessions))


class PresentationLockTests(unittest.TestCase):

    def test_new_project_bypasses_the_existing_deck_guard(self):
        with patch(
            "services.presentation_change_intent.deck_matches_recorded_project"
        ) as matches:
            ensure_presentation_unchanged(
                ProjectSelection("new", None, ()),
                {"slides": [{"title": "new"}]},
            )
        matches.assert_not_called()

    def test_changed_deck_returns_the_locked_contract(self):
        selection = ProjectSelection(
            "continue",
            ARC,
            ({"id": "take-1"},),
        )
        with patch(
            "services.presentation_change_intent.deck_matches_recorded_project",
            return_value=False,
        ), self.assertRaises(RecordingIntakeError) as raised:
            ensure_presentation_unchanged(
                selection,
                {"slides": [{"title": "changed"}]},
            )
        self.assertEqual(raised.exception.code, "PRESENTATION_LOCKED")
        self.assertEqual(raised.exception.status, 409)


class DuplicateUploadTests(unittest.TestCase):

    def test_empty_key_skips_lookup(self):
        database = MagicMock()
        key, duplicate = find_duplicate_upload(
            {},
            database=database,
            context_document=None,
        )
        self.assertEqual(key, "")
        self.assertIsNone(duplicate)
        database.v2_find_session_by_upload_key.assert_not_called()

    def test_duplicate_heals_the_optional_context_document_gap(self):
        duplicate = {"id": "take-1", "arc_id": ARC, "take_index": 1}
        database = MagicMock()
        database.v2_find_session_by_upload_key.return_value = duplicate
        document = {
            "text": "brief",
            "pages": 2,
            "chars": 5,
            "filename": "brief.pdf",
            "truncated": False,
        }

        key, result = find_duplicate_upload(
            {"upload_idempotency_key": " retry-key "},
            database=database,
            context_document=document,
        )

        self.assertEqual(key, "retry-key")
        self.assertIs(result, duplicate)
        database.upsert_arc_context_document.assert_called_once_with(
            ARC,
            "brief",
            2,
            5,
            filename="brief.pdf",
            truncated=False,
        )


if __name__ == "__main__":
    unittest.main()
