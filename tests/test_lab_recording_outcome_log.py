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
    from services import pipeline_jobs
    from services.create_take import CreateTakeError
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

    def test_create_take_refusal_is_logged_with_its_code(self):
        status, out = self._post_raising(
            CreateTakeError("PROJECT_ARCHIVED", "archived", 409))
        self.assertEqual(status, 409)
        self.assertIn("lab/recordings POST 409 code=PROJECT_ARCHIVED", out)

    def test_success_is_info_and_names_the_job(self):
        with self.assertLogs("routes.v2.lab_recording", level="INFO") as logs:
            v2_lab_recording._log_outcome(202, "sid-1", "processing",
                                          job="job-1")
        self.assertEqual(logs.records[0].levelname, "INFO")
        self.assertIn("POST 202 code=processing sid=sid-1 job=job-1",
                      logs.output[0])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class WorkerEarlyExitLogTests(unittest.TestCase):
    JOB = {"id": "job-1", "kind": pipeline_jobs.KIND_SESSION_RECORDING
           if _IMPORT_ERROR is None else "", "status": "pending",
           "attempts": 0, "max_attempts": 3}

    def test_lost_claim_is_logged(self):
        with patch.object(pipeline_jobs.db, "get_processing_job",
                          return_value=dict(self.JOB)), \
             patch.object(pipeline_jobs.db, "claim_processing_job",
                          return_value=None):
            with self.assertLogs("services.pipeline_jobs",
                                 level="WARNING") as logs:
                pipeline_jobs.run_processing_job("job-1")
        self.assertIn("job job-1 not claimed", "\n".join(logs.output))

    def test_live_elsewhere_is_logged(self):
        job = dict(self.JOB, status="processing")
        with patch.object(pipeline_jobs.db, "get_processing_job",
                          return_value=job), \
             patch.object(pipeline_jobs, "_worker_still_plausible",
                          return_value=True), \
             patch.object(pipeline_jobs.db, "claim_processing_job") as claim:
            with self.assertLogs("services.pipeline_jobs",
                                 level="INFO") as logs:
                pipeline_jobs.run_processing_job("job-1")
        claim.assert_not_called()
        self.assertIn("already running elsewhere", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
