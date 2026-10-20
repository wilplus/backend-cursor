"""
STORY    As a speaker, I want my first Ideal Text built from my first Take,
         retried after a dropped connection, and never undone by a failed
         notification, so that Take 1 always produces my text.
OUTCOME
  O1  A retry builds version 1 from the Take that created the document, not
      from a later Take.
  O2  One dropped database connection is retried instead of failing Take 1.
  O3  If the "ready" notification fails, the document still counts as
      confirmed.
  O4  A later Take may queue the retry too, and the retry job carries no
      audio, upload or transcription fields.
PROVES   O1 -> IdealTextConfirmationTests::test_exact_session_retry_persists_version_one_not_latest_take
         O2 -> IdealTextConfirmationTests::test_a_dropped_connection_is_retried_not_final
         O3 -> IdealTextRetryJobTests::test_ready_card_failure_cannot_reclassify_a_confirmed_document
         O4 -> TheRetryFollowsTheCreatingTakeTests::test_a_later_take_may_retry_creating_the_document
WHY      Founder 2026-09-26: one "Server disconnected" cost a whole Take 1.
"""
from __future__ import annotations

import sys
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


class IdealTextConfirmationTests(unittest.TestCase):

    def test_exact_session_retry_persists_version_one_not_latest_take(self):
        from services import ideal_text_block

        database = Mock()
        database.ideal_text.get_coach_arc_ideal_text.return_value = None
        database.takes.get_arc_sessions.return_value = [
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


    def test_a_dropped_connection_is_retried_not_final(self):
        """Founder 2026-09-26: one `Server disconnected` from the database
        client made the assembler return False and cost the whole Take 1."""
        database = Mock()
        document = {"arc_id": "arc-1", "auto_text": "Built on retry"}
        database.ideal_text.get_coach_arc_ideal_text.return_value = document
        with patch(
            "services.ideal_text_block.maybe_assemble_ideal_text",
            side_effect=[False, True],
        ) as assemble, patch.object(
            confirmation, "ASSEMBLY_RETRY_DELAYS_SECONDS", (0.0, 0.0),
        ):
            row = confirmation.build_initial_ideal_text_from_stored_artifacts(
                database, "arc-1", source_session_id=SID, timeout_seconds=30,
            )
        self.assertEqual(row["auto_text"], "Built on retry")
        self.assertEqual(assemble.call_count, 2)


class IdealTextRetryJobTests(unittest.TestCase):


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


class TheRetryFollowsTheCreatingTakeTests(unittest.TestCase):
    """Without this the recovery path rebuilds the dead end it removes: a
    terminal card offering a retry that the queue refuses."""

    def test_a_later_take_may_retry_creating_the_document(self):
        database = Mock()
        database.create_processing_job.return_value = {"id": "job-9"}
        with patch.object(pipeline_jobs, "db", database), patch.object(
            pipeline_jobs.job_queue, "queue_configured", return_value=True
        ), patch.object(
            pipeline_jobs.job_queue, "enqueue", return_value=True
        ):
            job = pipeline_jobs.enqueue_ideal_text_retry_job(
                session_id=SID, user_id="user-1", arc_id="arc-1", take_index=3,
            )
        self.assertEqual(job, {"id": "job-9"})
        payload = database.create_processing_job.call_args.kwargs["payload"]
        self.assertEqual(payload["take_index"], 3)
        # Still no way back into audio, upload or transcription.
        self.assertTrue({
            "audio_bytes", "bucket", "storage_key", "recording_id",
            "filename", "transcript",
        }.isdisjoint(payload))
