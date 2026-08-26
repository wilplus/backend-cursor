"""Unit tests for the canonical RecordingAttempt -> Take boundary."""
from __future__ import annotations

import unittest
from unittest.mock import Mock

from services.take_lifecycle import (
    TakeLifecycleError,
    complete_attempt,
    register_attempt,
    transition_attempt,
)


class TakeLifecycleTests(unittest.TestCase):
    def test_registration_is_a_hard_boundary(self):
        database = Mock()
        database.register_recording_attempt.return_value = None

        with self.assertRaisesRegex(TakeLifecycleError, "durably registered"):
            register_attempt(
                database=database,
                attempt_id="attempt-1",
                owner_principal_id="owner-1",
                project_id="project-1",
                upload_idempotency_key="upload-1",
                recording_id="recording-1",
                storage_bucket="recordings",
                storage_key="owner/recording.webm",
                recording_kind="spoken",
            )

    def test_spoken_success_promotes_exactly_one_take(self):
        database = Mock()
        database.promote_recording_attempt_to_take.return_value = {
            "take_id": "attempt-1",
            "take_index": 2,
            "replayed": False,
        }

        result = complete_attempt(
            database=database,
            attempt_id="attempt-1",
            recording_kind="spoken",
            result={"snippet_count": 3},
            attempt_count=2,
            processing_job_id="job-1",
            input_provenance={"storage_key": "owner/recording.webm"},
        )

        self.assertEqual(result["take_index"], 2)
        call = database.promote_recording_attempt_to_take.call_args.kwargs
        self.assertEqual(call["recording_attempt_id"], "attempt-1")
        self.assertEqual(call["attempt_count"], 2)
        self.assertTrue(call["completion_hash"])
        self.assertTrue(call["idempotency_key"].startswith(
            "attempt-promotion:attempt-1:"))

    def test_read_success_completes_without_take_promotion(self):
        database = Mock()
        database.record_processing_transition.return_value = {
            "transition_id": "transition-1",
            "status": "succeeded",
        }

        complete_attempt(
            database=database,
            attempt_id="attempt-1",
            recording_kind="read",
            result={"readout": True},
        )

        database.promote_recording_attempt_to_take.assert_not_called()
        call = database.record_processing_transition.call_args.kwargs
        self.assertEqual(call["to_status"], "succeeded")
        self.assertEqual(call["stage"], "complete")

    def test_transition_failure_never_degrades_to_telemetry(self):
        database = Mock()
        database.record_processing_transition.return_value = None

        with self.assertRaisesRegex(TakeLifecycleError, "was not persisted"):
            transition_attempt(
                database=database,
                attempt_id="attempt-1",
                to_status="processing",
                stage="worker",
                attempt_count=1,
            )

    def test_transition_idempotency_key_is_stable(self):
        database = Mock()
        database.record_processing_transition.return_value = {
            "transition_id": "transition-1",
        }
        kwargs = {
            "database": database,
            "attempt_id": "attempt-1",
            "to_status": "retryable",
            "stage": "analysis",
            "attempt_count": 1,
            "processing_job_id": "job-1",
            "input_provenance": {"storage_key": "a.webm"},
            "error": RuntimeError("temporary"),
        }

        transition_attempt(**kwargs)
        first = database.record_processing_transition.call_args.kwargs[
            "idempotency_key"]
        transition_attempt(**kwargs)
        second = database.record_processing_transition.call_args.kwargs[
            "idempotency_key"]

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
