"""Take 1 Ideal Text confirmation, timeout, and artifact-only retry."""
from __future__ import annotations

import inspect
import sys
import threading
import time
import types
import unittest
from unittest.mock import Mock, patch

for _module in ("supabase", "sentry_sdk"):
    if _module not in sys.modules:
        sys.modules[_module] = types.ModuleType(_module)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None
    sys.modules["supabase"].Client = object
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None

from services import ideal_text_confirmation as confirmation
from services import pipeline_jobs


SID = "77777777-7777-4777-8777-777777777777"


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class IdealTextConfirmationTests(unittest.TestCase):
    def test_builder_forwards_exact_take_one_session_provenance(self):
        database = Mock()
        database.get_coach_arc_ideal_text.return_value = {
            "auto_text": "Persisted document",
        }
        with patch(
            "services.ideal_text_block.maybe_assemble_ideal_text",
            return_value=True,
        ) as assemble:
            confirmation.build_initial_ideal_text_from_stored_artifacts(
                database,
                "arc-1",
                source_session_id=SID,
                timeout_seconds=1,
            )
        assemble.assert_called_once_with(
            "arc-1",
            database=database,
            require_target=False,
            include_suggestion_anchors=False,
            source_session_id=SID,
        )

    def test_exact_session_retry_persists_version_one_not_latest_take(self):
        from services import ideal_text_block

        database = Mock()
        database.get_coach_arc_ideal_text.return_value = None
        database.get_arc_sessions.return_value = [
            {"id": SID, "take_index": 1, "recording_kind": "spoken"},
            {"id": "later", "take_index": 2, "recording_kind": "spoken"},
        ]
        database.v2_get_session_by_id.return_value = {
            "id": SID,
            "arc_id": "arc-1",
            "take_index": 1,
            "recording_kind": "spoken",
        }
        database.persist_auto_ideal_text.return_value = True
        with patch.object(
            ideal_text_block,
            "assemble_transcript_document",
            return_value={
                "text": "Take one only",
                "ready": True,
                "polish": [],
                "document": {"pieces": [{"take_session_id": SID}]},
            },
        ) as assemble:
            self.assertTrue(ideal_text_block.maybe_assemble_ideal_text(
                "arc-1",
                database=database,
                require_target=False,
                source_session_id=SID,
            ))
        assemble.assert_called_once_with(
            "arc-1", database=database, session_id=SID)
        self.assertEqual(
            database.persist_auto_ideal_text.call_args.kwargs["take_count"],
            1,
        )

    def test_requires_nonempty_text_read_back_from_database(self):
        database = Mock()
        database.get_coach_arc_ideal_text.side_effect = [
            None,
            {"arc_id": "arc-1", "auto_text": "  "},
            {"arc_id": "arc-1", "auto_text": "Persisted document"},
        ]
        clock = _Clock()
        row = confirmation.wait_for_ideal_text_confirmation(
            database,
            "arc-1",
            timeout_seconds=120,
            poll_seconds=1,
            monotonic=clock.monotonic,
            sleep=clock.sleep,
        )
        self.assertEqual(row["auto_text"], "Persisted document")
        self.assertEqual(clock.now, 2.0)

    def test_exact_120_second_boundary_raises_typed_terminal_error(self):
        database = Mock()
        database.get_coach_arc_ideal_text.return_value = None
        clock = _Clock()
        with self.assertRaises(confirmation.IdealTextUnconfirmedError):
            confirmation.wait_for_ideal_text_confirmation(
                database,
                "arc-1",
                timeout_seconds=120,
                poll_seconds=7,
                monotonic=clock.monotonic,
                sleep=clock.sleep,
            )
        self.assertEqual(clock.now, 120.0)
        self.assertEqual(sum(clock.sleeps), 120.0)

    def test_generation_call_is_inside_the_timeout_boundary(self):
        database = Mock()
        database.get_coach_arc_ideal_text.return_value = None
        release = threading.Event()
        with patch(
            "services.ideal_text_block.maybe_assemble_ideal_text",
            side_effect=lambda *a, **k: release.wait(1),
        ):
            started = time.monotonic()
            with self.assertRaises(confirmation.IdealTextUnconfirmedError):
                confirmation.build_initial_ideal_text_from_stored_artifacts(
                    database,
                    "arc-1",
                    timeout_seconds=0.02,
                )
            elapsed = time.monotonic() - started
        release.set()
        self.assertLess(elapsed, 0.2)

    def test_database_confirmation_read_is_inside_the_timeout_boundary(self):
        database = Mock()
        release = threading.Event()
        database.get_coach_arc_ideal_text.side_effect = \
            lambda *_args, **_kwargs: release.wait(1)
        with patch(
            "services.ideal_text_block.maybe_assemble_ideal_text",
            return_value=True,
        ):
            started = time.monotonic()
            with self.assertRaises(confirmation.IdealTextUnconfirmedError):
                confirmation.build_initial_ideal_text_from_stored_artifacts(
                    database,
                    "arc-1",
                    timeout_seconds=0.02,
                )
            elapsed = time.monotonic() - started
        release.set()
        self.assertLess(elapsed, 0.2)

    def test_terminal_state_and_card_are_take_one_only(self):
        database = Mock()
        database.set_session_analysis_state.return_value = True
        with patch(
            "services.arc_notifications.fire_ideal_text_unconfirmed"
        ) as fire:
            self.assertTrue(confirmation.mark_ideal_text_unconfirmed(
                database,
                session_id=SID,
                user_id="user-1",
                arc_id="arc-1",
                take_index=1,
                error="timed out",
            ))
        database.set_session_analysis_state.assert_called_once_with(
            SID,
            confirmation.FAILED_IDEAL_TEXT_UNCONFIRMED,
            "timed out",
        )
        fire.assert_called_once_with(
            database, "user-1", "arc-1", SID, 1)

        database.reset_mock()
        self.assertFalse(confirmation.mark_ideal_text_unconfirmed(
            database,
            session_id=SID,
            user_id="user-1",
            arc_id="arc-1",
            take_index=2,
        ))
        database.set_session_analysis_state.assert_not_called()


class IdealTextRetryJobTests(unittest.TestCase):
    def test_retry_job_payload_has_no_audio_or_transcription_inputs(self):
        database = Mock()
        database.create_processing_job.return_value = {"id": "job-1"}
        database.set_session_analysis_state.return_value = True
        with patch.object(pipeline_jobs, "db", database), patch.object(
            pipeline_jobs.job_queue, "queue_configured", return_value=True
        ), patch.object(
            pipeline_jobs.job_queue, "enqueue", return_value=True
        ):
            job = pipeline_jobs.enqueue_ideal_text_retry_job(
                session_id=SID,
                user_id="user-1",
                arc_id="arc-1",
                take_index=1,
            )
        self.assertEqual(job, {"id": "job-1"})
        payload = database.create_processing_job.call_args.kwargs["payload"]
        self.assertEqual(payload, {
            "session_id": SID,
            "user_id": "user-1",
            "arc_id": "arc-1",
            "take_index": 1,
        })
        forbidden = {
            "audio_bytes", "bucket", "storage_key", "recording_id",
            "filename", "transcript",
        }
        self.assertTrue(forbidden.isdisjoint(payload))
        self.assertEqual(
            database.create_processing_job.call_args.kwargs["max_attempts"],
            1,
        )

    def test_retry_runner_calls_only_stored_artifact_builder(self):
        database = Mock()
        row = {"auto_text": "Ideal", "version": 1}
        job = {
            "id": "job-1",
            "user_id": None,
            "payload": {
                "session_id": SID,
                "user_id": None,
                "arc_id": "arc-1",
                "take_index": 1,
            },
        }
        with patch.object(pipeline_jobs, "db", database), patch.object(
            pipeline_jobs,
            "build_initial_ideal_text_from_stored_artifacts",
            return_value=row,
        ) as build:
            result = pipeline_jobs._run_ideal_text_retry(job)
        build.assert_called_once_with(
            database,
            "arc-1",
            source_session_id=SID,
            include_suggestion_anchors=True,
        )
        self.assertEqual(result, {
            "ideal_text_confirmed": True,
            "version": 1,
        })

        source = inspect.getsource(pipeline_jobs._run_ideal_text_retry)
        for forbidden in (
            "run_full_analysis", "get_lab_audio_bytes", "audio_bytes",
            "process_lab_recording",
        ):
            self.assertNotIn(forbidden, source)

    def test_ready_card_failure_cannot_reclassify_a_confirmed_document(self):
        database = Mock()
        row = {"auto_text": "Ideal", "version": 1}
        job = {
            "id": "job-1",
            "user_id": "user-1",
            "payload": {
                "session_id": SID,
                "user_id": "user-1",
                "arc_id": "arc-1",
                "take_index": 1,
            },
        }
        with patch.object(pipeline_jobs, "db", database), patch.object(
            pipeline_jobs,
            "build_initial_ideal_text_from_stored_artifacts",
            return_value=row,
        ), patch(
            "services.arc_notifications.fire_ideal_version_ready",
            side_effect=RuntimeError("message transport unavailable"),
        ):
            result = pipeline_jobs._run_ideal_text_retry(job)
        self.assertEqual(result, {
            "ideal_text_confirmed": True,
            "version": 1,
        })


if __name__ == "__main__":
    unittest.main()
