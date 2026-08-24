"""Unit tests for Lab recording storage and database persistence."""
from __future__ import annotations

import io
import unittest
from unittest.mock import Mock, patch

from werkzeug.datastructures import FileStorage

from services.lab_recording_persistence import (
    RecordingPersistenceError,
    persist_recording_row,
    persist_session_metadata,
    store_recording_audio,
)


def _audio_file() -> FileStorage:
    return FileStorage(
        stream=io.BytesIO(b"audio"),
        filename="take.webm",
        content_type="audio/webm",
    )


class ParentAudioStorageTests(unittest.TestCase):

    def test_stores_audio_creates_session_and_stamps_upload_key(self):
        database = Mock()
        database.v2_get_session_by_id.return_value = None
        deadline = Mock()
        with patch(
            "services.lab_audio_storage.put_lab_audio_bytes",
            return_value="bucket",
        ), patch(
            "services.lab_audio_storage.lab_audio_public_url",
            return_value="https://audio",
        ):
            result = store_recording_audio(
                _audio_file(),
                b"audio",
                upload_key="upload-1",
                owner_principal_id="owner-1",
                user_id="user-1",
                database=database,
                deadline=deadline,
                log=Mock(),
            )
        deadline.check.assert_called_once_with("store")
        self.assertEqual(result.audio_url, "https://audio")
        database.v2_create_recording_session.assert_called_once_with(
            result.session_id,
            owner_principal_id="owner-1",
            user_id="user-1",
        )
        database.v2_set_session_upload_key.assert_called_once_with(
            result.session_id,
            "upload-1",
        )

    def test_storage_failure_keeps_the_public_error(self):
        with patch(
            "services.lab_audio_storage.put_lab_audio_bytes",
            side_effect=RuntimeError("storage down"),
        ), self.assertRaises(RecordingPersistenceError) as raised:
            store_recording_audio(
                _audio_file(),
                b"audio",
                upload_key="upload-1",
                owner_principal_id="owner-1",
                user_id=None,
                database=Mock(),
                deadline=Mock(),
                log=Mock(),
            )
        self.assertEqual(raised.exception.message, "Failed to store recording")


class SessionMetadataTests(unittest.TestCase):

    def test_context_tags_duration_and_owner_are_persisted(self):
        database = Mock()
        context = {"topic": "Talk"}
        persist_session_metadata(
            "session-1",
            context,
            flow_tags={"named_emotion": "excited"},
            duration_seconds=15.2,
            user_id="user-1",
            database=database,
        )
        self.assertEqual(context["named_emotion"], "excited")
        database.set_session_intake_context.assert_called_once_with(
            "session-1",
            context,
        )
        database.set_session_user_id.assert_called_once_with(
            "session-1",
            "user-1",
        )


class RecordingRowTests(unittest.TestCase):

    def _persist(self, database):
        return persist_recording_row(
            form={"feeling": "nervous"},
            session_id="session-1",
            recording_id="recording-1",
            storage_key="key.webm",
            audio_url="https://audio",
            gate={"duration_sec": 12.6},
            user_id="user-1",
            arc_id="arc-1",
            take_index=2,
            database=database,
            log=Mock(),
        )

    def test_persists_private_signals_duration_origin_and_link(self):
        database = Mock()
        result = self._persist(database)
        self.assertEqual(result.duration_seconds, 13)
        payload = database.create_recording.call_args.args[0]
        self.assertEqual(payload["recording_origin"], "willab_lab")
        self.assertEqual(payload["duration"], 13)
        database.insert_recording_feeling.assert_called_once()
        database.v2_set_session_recording.assert_called_once_with(
            "session-1",
            "recording-1",
        )

    def test_old_schema_retries_without_recording_origin(self):
        database = Mock()
        database.create_recording.side_effect = [
            RuntimeError("PGRST204 recording_origin missing"),
            None,
        ]
        self._persist(database)
        self.assertEqual(database.create_recording.call_count, 2)
        fallback = database.create_recording.call_args_list[1].args[0]
        self.assertNotIn("recording_origin", fallback)

    def test_unrelated_recording_write_failure_does_not_use_fallback(self):
        database = Mock()
        database.create_recording.side_effect = RuntimeError("database down")
        with self.assertRaises(RecordingPersistenceError) as raised:
            self._persist(database)
        self.assertEqual(raised.exception.message, "Failed to create recording")
        self.assertEqual(database.create_recording.call_count, 1)


if __name__ == "__main__":
    unittest.main()
