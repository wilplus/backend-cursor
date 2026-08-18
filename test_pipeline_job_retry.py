from __future__ import annotations

import unittest
from unittest.mock import patch

from services import pipeline_jobs


class ManualProcessingRetryTests(unittest.TestCase):
    def test_requeues_the_existing_failed_job_and_preserves_its_payload(self):
        failed = {
            "id": "job-1", "session_id": "session-1", "user_id": "user-1",
            "status": "failed", "payload": {"storage_key": "kept/audio.webm"},
        }
        reopened = {**failed, "status": "pending", "attempts": 0}
        with patch.object(pipeline_jobs.job_queue, "queue_configured",
                          return_value=True), \
             patch.object(pipeline_jobs.db,
                          "get_latest_processing_job_by_session",
                          return_value=failed), \
             patch.object(pipeline_jobs.db,
                          "reset_processing_job_for_manual_retry",
                          return_value=True) as reset, \
             patch.object(pipeline_jobs.job_queue, "enqueue",
                          return_value=True) as enqueue, \
             patch.object(pipeline_jobs.db, "set_session_analysis_state") \
                          as state, \
             patch.object(pipeline_jobs.db, "get_processing_job",
                          return_value=reopened):
            out = pipeline_jobs.retry_failed_session_job(
                "session-1", "user-1")
        self.assertEqual(out["payload"]["storage_key"], "kept/audio.webm")
        reset.assert_called_once_with("job-1")
        enqueue.assert_called_once_with(pipeline_jobs.TASK_PATH, "job-1")
        state.assert_called_once_with("session-1", "processing")

    def test_refuses_a_different_owner(self):
        with patch.object(pipeline_jobs.job_queue, "queue_configured",
                          return_value=True), \
             patch.object(pipeline_jobs.db,
                          "get_latest_processing_job_by_session",
                          return_value={"id": "job-1", "status": "failed",
                                        "user_id": "owner"}):
            self.assertIsNone(pipeline_jobs.retry_failed_session_job(
                "session-1", "intruder"))


if __name__ == "__main__":
    unittest.main()
