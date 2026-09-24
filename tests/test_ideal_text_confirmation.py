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
from services import take_analysis_state as state


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
        database.ideal_text.get_coach_arc_ideal_text.return_value = {
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

    def test_requires_nonempty_text_read_back_from_database(self):
        database = Mock()
        database.ideal_text.get_coach_arc_ideal_text.side_effect = [
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
        database.ideal_text.get_coach_arc_ideal_text.return_value = None
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
        database.ideal_text.get_coach_arc_ideal_text.return_value = None
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
        database.ideal_text.get_coach_arc_ideal_text.side_effect = \
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

    def test_terminal_state_and_card_name_the_creating_take(self):
        database = Mock()
        database.takes.set_session_analysis_state.return_value = True
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
        database.takes.set_session_analysis_state.assert_called_once_with(
            SID,
            confirmation.FAILED_IDEAL_TEXT_UNCONFIRMED,
            "timed out",
        )
        fire.assert_called_once_with(
            database, "user-1", "arc-1", SID, 1)

        # NO LONGER TAKE 1 ONLY (Option A, 2026-09-22). A later Take that
        # found the Project with no document is creating it, so the same
        # terminal state and the same sentence are the true ones for it.
        # What still writes nothing is a value that is not a Take at all,
        # asserted in `TheTerminalStateBelongsToWhicheverTakeWasCreating`.
        database.reset_mock()
        self.assertFalse(confirmation.mark_ideal_text_unconfirmed(
            database,
            session_id=SID,
            user_id="user-1",
            arc_id="arc-1",
            take_index=0,
        ))
        database.takes.set_session_analysis_state.assert_not_called()


class IdealTextRetryJobTests(unittest.TestCase):
    def test_retry_job_payload_has_no_audio_or_transcription_inputs(self):
        database = Mock()
        database.create_processing_job.return_value = {"id": "job-1"}
        database.takes.set_session_analysis_state.return_value = True
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
        build.assert_called_once()
        _args, _kwargs = build.call_args
        self.assertEqual(_args, (database, "arc-1"))
        self.assertEqual(_kwargs["source_session_id"], SID)
        self.assertTrue(_kwargs["include_suggestion_anchors"])
        # The late-confirmation hook is the retry's own withdrawal path: a
        # document that lands after this attempt's deadline still has to
        # clear the terminal state and retract the card.
        self.assertTrue(callable(_kwargs["on_late_confirmation"]))
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


class WhichTakeCreatesTheDocumentTests(unittest.TestCase):
    """Option A, the founder's decision of 2026-09-22.

    A Project whose Take 1 never confirmed an Ideal Text could never recover:
    only Take 1 was allowed to create one, Take 1 was over, and every later
    Take was refused for the document's absence. One real Project sat like
    that for eleven days, showing "processing" the whole time.

    The question is now "does this Project still have no document" rather
    than "which Take is this" — and the read that answers it IS the L1
    guard, because the only path to yes for a later Take requires the
    canonical row to be absent.
    """

    @staticmethod
    def _db(row):
        database = Mock()
        database.ideal_text.get_coach_arc_ideal_text.return_value = row
        return database

    def test_take_one_creates_it_as_it_always_did(self):
        database = self._db(None)
        self.assertTrue(
            confirmation.take_creates_ideal_text(database, "arc-1", 1))
        # And without even asking: Take 1 is the creator by definition, so
        # a database that is down cannot stop it.
        database.ideal_text.get_coach_arc_ideal_text.assert_not_called()

    def test_a_later_take_creates_it_when_the_project_has_none(self):
        # THE RECOVERY. This is the case that was impossible before.
        self.assertTrue(confirmation.take_creates_ideal_text(
            self._db(None), "arc-1", 3))

    def test_a_later_take_creates_it_when_the_row_is_empty(self):
        # A row with no words is not a document — the same rule
        # `confirmed_ideal_text` has always applied.
        self.assertTrue(confirmation.take_creates_ideal_text(
            self._db({"auto_text": "   ", "text": ""}), "arc-1", 2))

    def test_a_later_take_NEVER_creates_it_when_one_exists(self):
        """THE L1 PROOF, and the reason this change is safe at all.

        L1 says a later Take may never rebuild or silently overwrite the
        canonical words. This says it in the one place that decides: a
        Project that has a document answers no, for every Take, forever.
        """
        for row in (
            {"auto_text": "Machine-made words"},
            {"text": "Coach-written words"},
            {"auto_text": "", "text": "The words the speaker edited"},
        ):
            with self.subTest(row=row):
                self.assertFalse(confirmation.take_creates_ideal_text(
                    self._db(row), "arc-1", 4))

    def test_a_read_that_fails_protects_the_document(self):
        # Conservative in the direction that cannot destroy anything: an
        # unreadable row answers no, which is exactly the behaviour every
        # later Take had before this existed.
        database = Mock()
        database.ideal_text.get_coach_arc_ideal_text.side_effect = \
            RuntimeError("database is down")
        self.assertFalse(
            confirmation.take_creates_ideal_text(database, "arc-1", 2))

    def test_a_take_with_no_project_creates_nothing(self):
        self.assertFalse(
            confirmation.take_creates_ideal_text(self._db(None), "", 2))

    def test_nonsense_take_indexes_create_nothing(self):
        for index in (0, -1, None, "1", True, False, 1.0):
            with self.subTest(index=index):
                self.assertFalse(confirmation.take_creates_ideal_text(
                    self._db(None), "arc-1", index))


class TheTerminalStateBelongsToWhicheverTakeWasCreatingTests(unittest.TestCase):
    """"We processed your take, but couldn't create your Ideal Text" is as
    true of the Take 3 that found the Project had none as it is of Take 1."""

    def test_a_recovering_later_take_gets_the_same_terminal_state(self):
        database = Mock()
        database.takes.set_session_analysis_state.return_value = True
        self.assertTrue(confirmation.mark_ideal_text_unconfirmed(
            database, session_id=SID, user_id="user-1", arc_id="arc-1",
            take_index=3,
        ))
        state = database.takes.set_session_analysis_state.call_args.args
        self.assertEqual(state[1], confirmation.FAILED_IDEAL_TEXT_UNCONFIRMED)

    def test_take_one_is_unchanged(self):
        database = Mock()
        database.takes.set_session_analysis_state.return_value = True
        self.assertTrue(confirmation.mark_ideal_text_unconfirmed(
            database, session_id=SID, user_id="user-1", arc_id="arc-1",
            take_index=1,
        ))

    def test_a_take_with_no_index_still_writes_nothing(self):
        database = Mock()
        for index in (0, None, True, "2"):
            with self.subTest(index=index):
                self.assertFalse(confirmation.mark_ideal_text_unconfirmed(
                    database, session_id=SID, user_id="u", arc_id="arc-1",
                    take_index=index,
                ))
        database.takes.set_session_analysis_state.assert_not_called()


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

    def test_a_take_index_that_is_not_a_take_still_queues_nothing(self):
        database = Mock()
        with patch.object(pipeline_jobs, "db", database), patch.object(
            pipeline_jobs.job_queue, "queue_configured", return_value=True
        ):
            for index in (0, -2, None, True, "1"):
                with self.subTest(index=index):
                    self.assertIsNone(
                        pipeline_jobs.enqueue_ideal_text_retry_job(
                            session_id=SID, user_id="u", arc_id="arc-1",
                            take_index=index,
                        ))
        database.create_processing_job.assert_not_called()


class AFailureMustNotOutliveTheFailureTests(unittest.TestCase):
    """Founder 2026-09-24: "Ideal text generation fails!" -- shown as a ready
    v1.0 card with "we couldn't create your Ideal Text" directly underneath.

    Generation had not failed. The 120-second deadline bounds the OWNER's
    wait, not the generation, so a document landing a moment later left a
    terminal state and a durable Lounge card that nothing on any path ever
    withdrew. These tests hold the three places the claim is now checked
    against the only evidence that counts: the document itself.
    """

    @staticmethod
    def _database(document: dict | None) -> Mock:
        database = Mock()
        database.ideal_text.get_coach_arc_ideal_text.return_value = document
        database.takes.set_session_analysis_state.return_value = True
        database.delete_lounge_message_by_client_id.return_value = True
        return database

    # -- 1. never claim a failure over a document that exists ---------------

    def test_no_terminal_state_is_written_when_the_document_is_there(self):
        database = self._database({"auto_text": "The document landed."})
        with patch(
            "services.arc_notifications.fire_ideal_text_unconfirmed"
        ) as fire:
            self.assertFalse(confirmation.mark_ideal_text_unconfirmed(
                database,
                session_id=SID,
                user_id="user-1",
                arc_id="arc-1",
                take_index=1,
                error="timed out",
            ))
        fire.assert_not_called()
        # The Take did not fail, so it is recorded as what it was -- and any
        # card an earlier writer already put in the thread is retracted.
        database.takes.set_session_analysis_state.assert_called_once_with(
            SID, "ready",
        )
        database.delete_lounge_message_by_client_id.assert_called_once_with(
            "user-1", SID,
        )

    def test_a_real_failure_is_still_recorded(self):
        """The guard reads evidence; it cannot talk a real failure away."""
        database = self._database(None)
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
        database.takes.set_session_analysis_state.assert_called_once_with(
            SID, confirmation.FAILED_IDEAL_TEXT_UNCONFIRMED, "timed out",
        )
        fire.assert_called_once()

    def test_an_empty_document_row_is_not_a_document(self):
        database = self._database({"auto_text": "   ", "text": ""})
        with patch("services.arc_notifications.fire_ideal_text_unconfirmed"):
            self.assertTrue(confirmation.mark_ideal_text_unconfirmed(
                database,
                session_id=SID, user_id="user-1", arc_id="arc-1",
                take_index=1,
            ))
        database.takes.set_session_analysis_state.assert_called_once()

    # -- 2. withdraw a failure the database no longer supports --------------

    def test_resolve_clears_the_state_and_retracts_the_card(self):
        database = self._database({"auto_text": "Ideal", "version": 1})
        row = confirmation.resolve_ideal_text_unconfirmed(
            database, session_id=SID, user_id="user-1", arc_id="arc-1",
        )
        self.assertEqual(row, {"auto_text": "Ideal", "version": 1})
        database.takes.set_session_analysis_state.assert_called_once_with(
            SID, "ready",
        )
        # The card's key is the Take's session UUID -- the one key every
        # writer of that card agrees on, which is what makes it retractable.
        database.delete_lounge_message_by_client_id.assert_called_once_with(
            "user-1", SID,
        )

    def test_resolve_changes_nothing_without_a_document(self):
        database = self._database(None)
        self.assertIsNone(confirmation.resolve_ideal_text_unconfirmed(
            database, session_id=SID, user_id="user-1", arc_id="arc-1",
        ))
        database.takes.set_session_analysis_state.assert_not_called()
        database.delete_lounge_message_by_client_id.assert_not_called()

    def test_resolve_never_writes_the_canonical_document(self):
        """L1: the withdrawal reads the document and never touches it."""
        database = self._database({"auto_text": "Ideal"})
        confirmation.resolve_ideal_text_unconfirmed(
            database, session_id=SID, user_id="user-1", arc_id="arc-1",
        )
        for banned in (
            "upsert_coach_arc_ideal_text",
            "set_coach_arc_ideal_text",
            "save_coach_arc_ideal_text",
        ):
            self.assertFalse(
                getattr(database.ideal_text, banned).called,
                f"resolve must never call {banned}",
            )

    def test_resolve_survives_a_card_that_will_not_delete(self):
        database = self._database({"auto_text": "Ideal"})
        database.delete_lounge_message_by_client_id.side_effect = \
            RuntimeError("lounge down")
        self.assertIsNotNone(confirmation.resolve_ideal_text_unconfirmed(
            database, session_id=SID, user_id="user-1", arc_id="arc-1",
        ))
        database.takes.set_session_analysis_state.assert_called_once_with(
            SID, "ready",
        )

    # -- 3. the late document announces itself ------------------------------

    def test_a_document_landing_after_the_deadline_is_announced(self):
        """The owner gives up at the deadline; the worker keeps running. The
        thread that makes the failure untrue is the one that must say so."""
        database = Mock()
        seen: list[dict] = []
        released = threading.Event()
        document = {"auto_text": "Late but real", "version": 1}

        def _slow_assemble(*_a, **_k):
            released.wait(2)
            return True

        database.ideal_text.get_coach_arc_ideal_text.return_value = document
        with patch(
            "services.ideal_text_block.maybe_assemble_ideal_text",
            side_effect=_slow_assemble,
        ):
            with self.assertRaises(confirmation.IdealTextUnconfirmedError):
                confirmation.build_initial_ideal_text_from_stored_artifacts(
                    database,
                    "arc-1",
                    timeout_seconds=0.02,
                    on_late_confirmation=seen.append,
                )
            released.set()
            for _ in range(200):
                if seen:
                    break
                time.sleep(0.01)
        self.assertEqual(seen, [document])

    def test_no_late_announcement_when_the_owner_did_not_give_up(self):
        database = Mock()
        seen: list[dict] = []
        database.ideal_text.get_coach_arc_ideal_text.return_value = {
            "auto_text": "In time",
        }
        with patch(
            "services.ideal_text_block.maybe_assemble_ideal_text",
            return_value=True,
        ):
            row = confirmation.build_initial_ideal_text_from_stored_artifacts(
                database, "arc-1", timeout_seconds=5,
                on_late_confirmation=seen.append,
            )
        self.assertEqual(row, {"auto_text": "In time"})
        time.sleep(0.05)
        self.assertEqual(seen, [])

    def test_the_deadline_stays_bounded_with_a_late_hook_attached(self):
        """The hook must not reintroduce an unbounded call inside the wait."""
        database = Mock()
        release = threading.Event()
        database.ideal_text.get_coach_arc_ideal_text.side_effect = \
            lambda *_a, **_k: release.wait(1)
        with patch(
            "services.ideal_text_block.maybe_assemble_ideal_text",
            return_value=True,
        ):
            started = time.monotonic()
            with self.assertRaises(confirmation.IdealTextUnconfirmedError):
                confirmation.build_initial_ideal_text_from_stored_artifacts(
                    database, "arc-1", timeout_seconds=0.02,
                    on_late_confirmation=lambda _row: None,
                )
            elapsed = time.monotonic() - started
        release.set()
        self.assertLess(elapsed, 0.2)


class EveryReadOfAFailedTakeWithdrawsAStaleFailureTests(unittest.TestCase):
    """The stuck state must not be OBSERVABLE.

    Both readout routes decide what to serve through one service function, so
    a document that landed after the deadline clears the failure on the very
    next read of the Take rather than waiting for the speaker to tap retry.
    """

    @staticmethod
    def _database(document: dict | None) -> Mock:
        database = Mock()
        database.ideal_text.get_coach_arc_ideal_text.return_value = document
        database.takes.set_session_analysis_state.return_value = True
        database.delete_lounge_message_by_client_id.return_value = True
        return database

    def _session(self, state: str) -> dict:
        return {
            "id": SID, "user_id": "user-1", "arc_id": "arc-1",
            "analysis_state": state,
        }

    def test_a_stale_failure_is_withdrawn_and_the_readout_serves(self):
        database = self._database({"auto_text": "Ideal", "version": 1})
        self.assertIsNone(state.served_analysis_state(
            database, self._session("failed_ideal_text_unconfirmed"),
        ))
        database.takes.set_session_analysis_state.assert_called_once_with(
            SID, "ready",
        )
        database.delete_lounge_message_by_client_id.assert_called_once_with(
            "user-1", SID,
        )

    def test_a_real_failure_is_still_served_as_a_failure(self):
        database = self._database(None)
        self.assertEqual(
            state.served_analysis_state(
                database, self._session("failed_ideal_text_unconfirmed")),
            "failed_ideal_text_unconfirmed",
        )
        database.takes.set_session_analysis_state.assert_not_called()

    def test_a_running_take_is_never_touched(self):
        """Only the Ideal Text failure is re-examined. A processing Take is
        served as-is -- reading the arc's document would say nothing about
        whether THIS Take has finished."""
        database = self._database({"auto_text": "Ideal"})
        self.assertEqual(
            state.served_analysis_state(database, self._session("processing")),
            "processing",
        )
        database.ideal_text.get_coach_arc_ideal_text.assert_not_called()
        database.takes.set_session_analysis_state.assert_not_called()

    def test_an_ordinary_failure_is_not_reinterpreted(self):
        database = self._database({"auto_text": "Ideal"})
        self.assertEqual(
            state.served_analysis_state(database, self._session("failed")),
            "failed",
        )
        database.ideal_text.get_coach_arc_ideal_text.assert_not_called()

    def test_a_finished_take_reads_normally(self):
        database = self._database(None)
        for finished in ("ready", None):
            self.assertIsNone(state.served_analysis_state(
                database, self._session(finished)))

    def test_both_readout_routes_go_through_it(self):
        from routes.v2 import lab_recording, user_sessions

        for module, name in (
            (lab_recording, "lab readout"),
            (user_sessions, "authed session readout"),
        ):
            self.assertIn(
                "served_analysis_state", inspect.getsource(module),
                f"the {name} must withdraw a failure the document disproves",
            )

    def test_the_retry_route_retracts_the_card_not_just_the_state(self):
        from routes.v2 import lab_recording

        source = inspect.getsource(lab_recording)
        # Clearing analysis_state alone is what left the card standing.
        self.assertNotIn(
            'set_session_analysis_state(session_id, "ready")', source,
        )


class TheRetryFindsTheDocumentAlreadyThereTests(unittest.TestCase):
    """The commonest shape of the 2026-09-24 bug: the deadline declared the
    document lost, it landed anyway, and the speaker taps "Try creating it
    again" on a card describing a failure that is already over."""

    @staticmethod
    def _database(document: dict | None) -> Mock:
        database = Mock()
        database.ideal_text.get_coach_arc_ideal_text.return_value = document
        database.takes.set_session_analysis_state.return_value = True
        database.delete_lounge_message_by_client_id.return_value = True
        return database

    def test_nothing_is_rebuilt_and_the_failure_is_withdrawn(self):
        database = self._database({"auto_text": "Ideal", "version": 1})
        with patch(
            "services.arc_notifications.fire_ideal_version_ready"
        ) as ready:
            row = confirmation.withdraw_and_announce_confirmed_document(
                database, session_id=SID, user_id="user-1", arc_id="arc-1",
                take_index=1,
            )
        self.assertEqual(row.get("version"), 1)
        database.takes.set_session_analysis_state.assert_called_once_with(
            SID, "ready",
        )
        database.delete_lounge_message_by_client_id.assert_called_once_with(
            "user-1", SID,
        )
        ready.assert_called_once_with(
            database, "user-1", "arc-1", 1, spoken_take_count=1)

    def test_a_recovery_take_omits_the_takes_one_and_two_nudge(self):
        database = self._database({"auto_text": "Ideal", "version": 2})
        with patch(
            "services.arc_notifications.fire_ideal_version_ready"
        ) as ready:
            confirmation.withdraw_and_announce_confirmed_document(
                database, session_id=SID, user_id="user-1", arc_id="arc-1",
                take_index=3,
            )
        ready.assert_called_once_with(database, "user-1", "arc-1", 2)

    def test_without_a_document_the_retry_proceeds_as_a_retry(self):
        database = self._database(None)
        self.assertIsNone(
            confirmation.withdraw_and_announce_confirmed_document(
                database, session_id=SID, user_id="user-1", arc_id="arc-1",
                take_index=1,
            ))
        database.takes.set_session_analysis_state.assert_not_called()
