"""Unit tests for bounded Lab recording file intake."""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from werkzeug.datastructures import FileStorage

from services.lab_audio_intake import read_recording_upload
from services.lab_recording_intake import RecordingIntakeError


def _upload(
    body: bytes = b"recording",
    *,
    filename: str = "take.webm",
    content_type: str = "audio/webm",
) -> FileStorage:
    return FileStorage(
        stream=io.BytesIO(body),
        filename=filename,
        content_type=content_type,
    )


def _read(files, *, content_length=None):
    return read_recording_upload(
        files,
        content_length=content_length,
        max_audio_mb=1,
        context_max_mb=1,
        video_extensions={"mp4", "mov"},
    )


class RecordingAudioIntakeTests(unittest.TestCase):

    def test_missing_and_empty_audio_keep_the_public_errors(self):
        for files, code, status in (
            ({}, "AUDIO_FILE_REQUIRED", 400),
            ({"audio_file": _upload(b"")}, "INVALID_INPUT", 400),
        ):
            with self.subTest(code=code), self.assertRaises(
                RecordingIntakeError
            ) as raised:
                _read(files)
            self.assertEqual(raised.exception.code, code)
            self.assertEqual(raised.exception.status, status)

    def test_request_and_audio_parts_have_independent_size_guards(self):
        with self.assertRaises(RecordingIntakeError) as request_error:
            _read({"audio_file": _upload()}, content_length=2 * 1024 * 1024 + 1)
        self.assertEqual(request_error.exception.code, "FILE_TOO_LARGE")

        with self.assertRaises(RecordingIntakeError) as audio_error:
            _read({"audio_file": _upload(b"x" * (1024 * 1024 + 1))})
        self.assertEqual(audio_error.exception.code, "FILE_TOO_LARGE")
        self.assertIn("audio_file", audio_error.exception.message)

    def test_video_mimetype_or_extension_is_rejected_but_audio_webm_passes(self):
        for upload in (
            _upload(filename="take.webm", content_type="video/webm"),
            _upload(filename="take.mov", content_type="application/octet-stream"),
        ):
            with self.subTest(upload=upload), self.assertRaises(
                RecordingIntakeError
            ) as raised:
                _read({"audio_file": upload})
            self.assertEqual(raised.exception.code, "AUDIO_ONLY")
            self.assertEqual(raised.exception.status, 415)

        result = _read({"audio_file": _upload()})
        self.assertEqual(result.audio_bytes, b"recording")

    def test_context_is_extracted_and_returned_with_the_audio(self):
        result = _read({
            "audio_file": _upload(),
            "context_document": _upload(
                b"Board approval is the goal.",
                filename="brief.txt",
                content_type="text/plain",
            ),
        })
        self.assertEqual(
            result.context_document["text"],
            "Board approval is the goal.",
        )
        self.assertEqual(result.context_document["filename"], "brief.txt")

    def test_deadline_is_created_before_the_result_is_returned(self):
        sentinel = object()
        with patch(
            "services.lab_audio_intake.deadline_for",
            return_value=sentinel,
        ) as make_deadline:
            result = _read({"audio_file": _upload()})
        make_deadline.assert_called_once_with("lab-upload")
        self.assertIs(result.deadline, sentinel)


if __name__ == "__main__":
    unittest.main()
