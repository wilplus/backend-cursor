"""Unit tests for Lab recording analysis execution modes."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from services.lab_analysis_dispatch import (
    AnalysisInputs,
    CompletedAnalysis,
    FailedIdealTextAnalysis,
    PendingAnalysis,
    dispatch_recording_analysis,
)
from services.ideal_text_confirmation import IdealTextUnconfirmedError


def _inputs() -> AnalysisInputs:
    return AnalysisInputs(
        session_id="session-1",
        user_id="user-1",
        recording_id="recording-1",
        audio_bytes=b"audio",
        filename="take.webm",
        session_context={"topic": "Talk"},
        parent_audio_url="https://audio",
        recording_kind="spoken",
        paired_session_id=None,
        arc_id="arc-1",
        take_index=2,
        arc_take_count=2,
        spark_enabled=True,
        bucket="audio-bucket",
        storage_key="take/key.webm",
        duration_seconds=601,
        canonical_attempt_registered=True,
    )


def _database() -> Mock:
    database = Mock()
    database.record_processing_transition.return_value = {
        "transition_id": "transition-1",
    }
    database.promote_recording_attempt_to_take.return_value = {
        "take_id": "session-1",
        "take_index": 1,
    }
    return database


class AnalysisDispatchTests(unittest.TestCase):

    def test_non_canary_analysis_never_writes_canonical_lifecycle(self):
        database = _database()
        inputs = AnalysisInputs(**{
            **_inputs().__dict__,
            "canonical_attempt_registered": False,
        })
        with patch(
            "services.analysis_worker.run_full_analysis",
            return_value=({"snippets": []}, False),
        ):
            result = dispatch_recording_analysis(
                inputs,
                database=database,
                queue_enabled=lambda: False,
                async_enabled=lambda: False,
                audit_paid_for_arc=lambda _a, _u: False,
                log=Mock(),
            )
        self.assertIsInstance(result, CompletedAnalysis)
        database.record_processing_transition.assert_not_called()
        database.promote_recording_attempt_to_take.assert_not_called()

    def test_durable_queue_returns_job_polling_payload(self):
        database = _database()
        worker = Mock()
        with patch(
            "services.pipeline_jobs.enqueue_session_recording_job",
            return_value={"id": "job-1"},
        ) as enqueue, patch(
            "services.analysis_worker.run_full_analysis",
            worker,
        ):
            result = dispatch_recording_analysis(
                _inputs(),
                database=database,
                queue_enabled=lambda: True,
                async_enabled=lambda: False,
                audit_paid_for_arc=lambda _a, _u: True,
                log=Mock(),
            )
        self.assertIsInstance(result, PendingAnalysis)
        self.assertEqual(result.payload["job_id"], "job-1")
        self.assertEqual(result.payload["job_status_url"], "/v2/jobs/job-1/status")
        self.assertEqual(result.payload["audits_needed"], 2)
        enqueue.assert_called_once()
        self.assertIs(
            enqueue.call_args.kwargs["canonical_attempt_registered"], True,
        )
        worker.assert_not_called()
        database.set_session_analysis_state.assert_called_once_with(
            "session-1",
            "processing",
        )

    def test_non_canary_queue_job_does_not_claim_attempt_contract(self):
        database = _database()
        inputs = AnalysisInputs(**{
            **_inputs().__dict__,
            "canonical_attempt_registered": False,
        })
        with patch(
            "services.pipeline_jobs.enqueue_session_recording_job",
            return_value={"id": "job-legacy"},
        ) as enqueue:
            result = dispatch_recording_analysis(
                inputs,
                database=database,
                queue_enabled=lambda: True,
                async_enabled=lambda: False,
                audit_paid_for_arc=lambda _a, _u: False,
                log=Mock(),
            )

        self.assertIsInstance(result, PendingAnalysis)
        self.assertIs(
            enqueue.call_args.kwargs["canonical_attempt_registered"], False,
        )
        database.record_processing_transition.assert_not_called()

    def test_queue_failure_preserves_the_sync_fallback(self):
        database = _database()
        log = Mock()
        with patch(
            "services.pipeline_jobs.enqueue_session_recording_job",
            side_effect=RuntimeError("broker down"),
        ), patch(
            "services.analysis_worker.run_full_analysis",
            return_value=({"snippets": []}, True),
        ) as worker:
            result = dispatch_recording_analysis(
                _inputs(),
                database=database,
                queue_enabled=lambda: True,
                async_enabled=lambda: False,
                audit_paid_for_arc=lambda _a, _u: False,
                log=log,
            )
        self.assertEqual(result, CompletedAnalysis({"snippets": []}, True))
        worker.assert_called_once()
        self.assertGreaterEqual(log.warning.call_count, 2)

    def test_daemon_returns_immediately_and_updates_state_when_run(self):
        database = _database()
        thread = Mock()
        with patch(
            "services.lab_analysis_dispatch.threading.Thread",
            return_value=thread,
        ) as thread_factory, patch(
            "services.analysis_worker.run_full_analysis",
        ) as worker:
            result = dispatch_recording_analysis(
                _inputs(),
                database=database,
                queue_enabled=lambda: False,
                async_enabled=lambda: True,
                audit_paid_for_arc=lambda _a, _u: False,
                log=Mock(),
            )
        self.assertIsInstance(result, PendingAnalysis)
        self.assertNotIn("job_id", result.payload)
        thread.start.assert_called_once()
        worker.assert_not_called()

        target = thread_factory.call_args.kwargs["target"]
        target()
        worker.assert_called_once()
        self.assertEqual(
            database.set_session_analysis_state.call_args_list[-1].args,
            ("session-1", "ready"),
        )

    def test_synchronous_mode_returns_worker_result(self):
        with patch(
            "services.analysis_worker.run_full_analysis",
            return_value=({"snippets": [{"id": "one"}]}, False),
        ) as worker:
            result = dispatch_recording_analysis(
                _inputs(),
                database=_database(),
                queue_enabled=lambda: False,
                async_enabled=lambda: False,
                audit_paid_for_arc=lambda _a, _u: False,
                log=Mock(),
            )
        self.assertEqual(
            result,
            CompletedAnalysis({"snippets": [{"id": "one"}]}, False),
        )
        self.assertEqual(worker.call_args.kwargs["recording_kind"], "spoken")

    def test_synchronous_take_one_timeout_is_not_reported_as_success(self):
        database = _database()
        database.set_session_analysis_state.return_value = True
        inputs = AnalysisInputs(**{**_inputs().__dict__, "take_index": 1})
        with patch(
            "services.analysis_worker.run_full_analysis",
            side_effect=IdealTextUnconfirmedError("arc-1"),
        ), patch(
            "services.arc_notifications.fire_ideal_text_unconfirmed"
        ):
            result = dispatch_recording_analysis(
                inputs,
                database=database,
                queue_enabled=lambda: False,
                async_enabled=lambda: False,
                audit_paid_for_arc=lambda _a, _u: False,
                log=Mock(),
            )
        self.assertIsInstance(result, FailedIdealTextAnalysis)
        self.assertEqual(
            result.payload["state"],
            "failed_ideal_text_unconfirmed",
        )
        self.assertIsNone(result.payload["readout"])
        self.assertNotIsInstance(result, CompletedAnalysis)


if __name__ == "__main__":
    unittest.main()
