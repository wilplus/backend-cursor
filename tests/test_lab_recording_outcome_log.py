"""Every lab upload answer leaves one log line (2026-09-28).

A Take that "never started processing" left nothing in the web log: the
route's refusals returned without logging, and so did its success path. The
worker's early exits in run_processing_job were silent too. These tests pin
one line per answer, carrying the code, and a line for each worker exit.

Run: python3 -m unittest tests.test_lab_recording_outcome_log
"""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch

try:
    from flask import Flask

    from routes.v2 import lab_recording as v2_lab_recording
    from services.processing_authorization import ProcessingAuthorizationError
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    _IMPORT_ERROR = e


def _file():
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(b"x" * 32), filename="take.webm",
                       content_type="audio/webm")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RouteOutcomeLogTests(unittest.TestCase):
    def _post_raising(self, error):
        app = Flask(__name__)
        with app.test_request_context(
                method="POST", data={"audio_file": _file()},
                content_type="multipart/form-data"):
            with patch("routes.v2.lab_recording.resolve_take_project",
                       side_effect=error):
                with self.assertLogs("routes.v2.lab_recording",
                                     level="WARNING") as logs:
                    _, status = v2_lab_recording.v2_lab_create_recording \
                        .__wrapped__()
        return status, "\n".join(logs.output)

    def test_authorization_refusal_is_logged_with_its_code(self):
        status, out = self._post_raising(ProcessingAuthorizationError(
            code="PROCESSING_AUTHORIZATION_REQUIRED", message="nope"))
        self.assertEqual(status, 403)
        self.assertIn("lab/recordings POST 403", out)
        self.assertIn("code=PROCESSING_AUTHORIZATION_REQUIRED", out)


if __name__ == "__main__":
    unittest.main()
