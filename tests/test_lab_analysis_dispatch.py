"""
STORY    As a speaker, I want my Take processed even when the job queue is down,
         the upload to return without waiting, and a first Take that could not
         build its Ideal Text reported as failed, so that record -> process ->
         Ideal Text never lies about where it stands.
OUTCOME
  O1  If the queue fails, the Take is processed right away instead.
  O2  In background mode the upload answers "pending" at once, and the Take
      is marked ready when the work finishes.
  O3  A Take 1 whose Ideal Text could not be confirmed is reported as failed,
      never as complete.
PROVES   O1 -> AnalysisDispatchTests::test_queue_failure_preserves_the_sync_fallback
         O2 -> AnalysisDispatchTests::test_daemon_returns_immediately_and_updates_state_when_run
         O3 -> AnalysisDispatchTests::test_synchronous_take_one_timeout_is_not_reported_as_success
WHY      Never-rule 3: never break record -> process -> Ideal Text -> next Take.
"""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from services.ideal_text_confirmation import IdealTextUnconfirmedError
from services.lab_analysis_dispatch import (
    AnalysisInputs,
    CompletedAnalysis,
    FailedIdealTextAnalysis,
    PendingAnalysis,
    dispatch_recording_analysis,
)


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
    def setUp(self):
        # These pin the dispatch mechanics, not the confidence cutover: under
        # dark no source manifest is built. The flipped constant
        # (founder 2026-09-29) is pinned in its own suites, and the
        # founder_canary promote path in test_mlc2_confidence_cutover_integration.
        patcher = patch("config.Config.MLC2_CONFIDENCE_CUTOVER_MODE", "dark")
        patcher.start()
        self.addCleanup(patcher.stop)


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
            database.takes.set_session_analysis_state.call_args_list[-1].args,
            ("session-1", "ready"),
        )


    def test_synchronous_take_one_timeout_is_not_reported_as_success(self):
        database = _database()
        database.takes.set_session_analysis_state.return_value = True
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
