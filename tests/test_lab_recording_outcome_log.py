"""
STORY    As a developer on call, I want every upload answer and every early
         worker exit to leave one log line with its code, so that a Take
         that "never started" can be traced.
OUTCOME
  O1  A refused upload logs one WARNING line with its status and code=.
  O2  An accepted upload logs one line with code= and the session and job ids.
  O3  The worker's early exits (unknown job, lost claim) each log a line.
PROVES   O1 -> test_authorization_refusal_is_logged_with_its_code
         O2 -> test_accepted_upload_is_logged_with_its_ids
         O3 -> test_unknown_job_exit_is_logged,
               test_lost_claim_exit_is_logged
WHY      2026-09-28 "processing doesn't even start": the web log was empty.
"""
from __future__ import annotations

import io
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from flask import Flask

    from routes.v2 import lab_recording as v2_lab_recording
    from services import pipeline_jobs
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
    def _post(self, *patches, level="WARNING"):
        app = Flask(__name__)
        with app.test_request_context(
                method="POST", data={"audio_file": _file()},
                content_type="multipart/form-data"):
            for p in patches:
                p.start()
            try:
                with self.assertLogs("routes.v2.lab_recording",
                                     level=level) as logs:
                    _, status = v2_lab_recording.v2_lab_create_recording \
                        .__wrapped__()
            finally:
                for p in patches:
                    p.stop()
        lines = [line for line in logs.output if "lab/recordings POST" in line]
        return status, lines

    def test_authorization_refusal_is_logged_with_its_code(self):
        status, lines = self._post(patch(
            "routes.v2.lab_recording.resolve_take_project",
            side_effect=ProcessingAuthorizationError(
                code="PROCESSING_AUTHORIZATION_REQUIRED", message="nope")))
        self.assertEqual(status, 403)
        self.assertEqual(len(lines), 1)
        self.assertIn("lab/recordings POST 403", lines[0])
        self.assertIn("code=PROCESSING_AUTHORIZATION_REQUIRED", lines[0])

    def test_accepted_upload_is_logged_with_its_ids(self):
        project = SimpleNamespace(principal=SimpleNamespace(id="p1"),
                                  duplicate_take=None)
        status, lines = self._post(
            patch("routes.v2.lab_recording.resolve_take_project",
                  return_value=project),
            patch("routes.v2.lab_recording.ProcessingAuthorizationService",
                  return_value=MagicMock()),
            patch("routes.v2.lab_recording._prepare_lab_upload",
                  return_value=object()),
            patch("routes.v2.lab_recording._persist_lab_take",
                  return_value=SimpleNamespace(session_id="s-42")),
            patch("routes.v2.lab_recording._analysis_response",
                  return_value=({"state": "queued", "job_id": "j-7"}, 202)),
            level="INFO")
        self.assertEqual(status, 202)
        self.assertEqual(len(lines), 1)
        self.assertIn("lab/recordings POST 202 code=queued sid=s-42", lines[0])
        self.assertIn("job=j-7", lines[0])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class WorkerExitLogTests(unittest.TestCase):
    def _run(self, **db_returns):
        fake_db = MagicMock()
        for name, value in db_returns.items():
            getattr(fake_db, name).return_value = value
        with patch.object(pipeline_jobs, "db", fake_db), \
                self.assertLogs("services.pipeline_jobs", level="INFO") as logs:
            pipeline_jobs.run_processing_job("job-1")
        return "\n".join(logs.output), fake_db

    def test_unknown_job_exit_is_logged(self):
        out, _ = self._run(get_processing_job=None)
        self.assertIn("unknown job job-1", out)

    def test_lost_claim_exit_is_logged(self):
        out, fake_db = self._run(
            get_processing_job={"id": "job-1", "status": "queued",
                                "attempts": 0, "max_attempts": 3,
                                "kind": pipeline_jobs.KIND_SESSION_RECORDING},
            claim_processing_job=None)
        self.assertIn("job job-1 not claimed", out)
        fake_db.finish_processing_job.assert_not_called()


if __name__ == "__main__":
    unittest.main()
