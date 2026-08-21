"""Unit tests for the completed Lab recording response boundary."""
from unittest import TestCase
from unittest.mock import Mock, patch

from services.lab_recording_response import (
    build_completed_recording_response,
    project_recording_progress,
    rederive_readout_with_slides,
)


class ProjectRecordingProgressTests(TestCase):
    def test_guest_has_no_projection(self):
        database = Mock()

        result = project_recording_progress(
            user_id=None,
            duration_seconds=30,
            session_id="session-1",
            database=database,
            log=Mock(),
        )

        self.assertIsNone(result)
        database.v2_get_cumulative_recorded_seconds.assert_not_called()

    def test_authenticated_projection_includes_the_current_take(self):
        database = Mock()
        database.v2_get_cumulative_recorded_seconds.return_value = 250

        with patch("services.user_audit.AUDIT_UNLOCK_SECONDS", 300):
            result = project_recording_progress(
                user_id="user-1",
                duration_seconds=60,
                session_id="session-1",
                database=database,
                log=Mock(),
            )

        self.assertEqual(result, {
            "recorded_seconds": 310,
            "threshold_seconds": 300,
            "unlocked": True,
        })

    def test_projection_failure_is_non_fatal(self):
        database = Mock()
        database.v2_get_cumulative_recorded_seconds.side_effect = RuntimeError(
            "unavailable"
        )
        log = Mock()

        result = project_recording_progress(
            user_id="user-1",
            duration_seconds=60,
            session_id="session-1",
            database=database,
            log=log,
        )

        self.assertIsNone(result)
        log.warning.assert_called_once()


class ReadoutRederivationTests(TestCase):
    @patch("services.lab_recording.build_readout_from_session")
    def test_uses_persisted_readout_when_it_has_snippets(self, build_readout):
        persisted = {"snippets": [{"slide": 2}]}
        build_readout.return_value = persisted

        result = rederive_readout_with_slides(
            {"snippets": [{"text": "fallback"}]},
            session_id="session-1",
            audit_paid=True,
        )

        self.assertIs(result, persisted)
        build_readout.assert_called_once_with(
            "session-1",
            audit_paid=True,
            include_upgrade_cards=False,
        )

    @patch("services.lab_recording.build_readout_from_session")
    def test_keeps_analysis_readout_when_persisted_one_has_no_snippets(
        self,
        build_readout,
    ):
        fallback = {"snippets": [{"text": "fallback"}]}
        build_readout.return_value = {"snippets": []}

        result = rederive_readout_with_slides(
            fallback,
            session_id="session-1",
            audit_paid=False,
        )

        self.assertIs(result, fallback)

    @patch("services.f1_observability.observe_f1_degrade")
    @patch("services.lab_recording.build_readout_from_session")
    def test_failure_is_observed_and_keeps_analysis_readout(
        self,
        build_readout,
        observe_degrade,
    ):
        fallback = {"snippets": [{"text": "fallback"}]}
        error = RuntimeError("read failure")
        build_readout.side_effect = error

        result = rederive_readout_with_slides(
            fallback,
            session_id="session-1",
            audit_paid=False,
        )

        self.assertIs(result, fallback)
        observe_degrade.assert_called_once_with(
            "readout_rederive_failed",
            exc=error,
            session_id="session-1",
        )


class CompletedRecordingResponseTests(TestCase):
    @patch("services.lab_recording_response.rederive_readout_with_slides")
    @patch("services.lab_recording_response.project_recording_progress")
    def test_builds_existing_wire_contract(
        self,
        project_progress,
        rederive_readout,
    ):
        project_progress.return_value = {"recorded_seconds": 700}
        rederive_readout.return_value = {"snippets": [{"slide": 1}]}
        audit_paid_for_arc = Mock(return_value=True)
        context = {"topic": "Launch"}

        result = build_completed_recording_response(
            session_id="session-1",
            recording_id="recording-1",
            session_context=context,
            readout={"snippets": [{"text": "fallback"}]},
            sent_to_coach=True,
            arc_id="arc-1",
            take_index=2,
            take_count=3,
            duration_seconds=601,
            user_id="user-1",
            database=Mock(),
            audit_paid_for_arc=audit_paid_for_arc,
            log=Mock(),
        )

        self.assertEqual(result, {
            "status": "ok",
            "session_id": "session-1",
            "recording_id": "recording-1",
            "duration_minutes": 10.0,
            "audits_needed": 2,
            "state": "review_pending",
            "session_context": context,
            "readout": {"snippets": [{"slide": 1}]},
            "arc_id": "arc-1",
            "take_index": 2,
            "take_count": 3,
            "audit_paid": True,
            "recording_progress": {"recorded_seconds": 700},
        })
        audit_paid_for_arc.assert_called_once_with("arc-1", "user-1")

    @patch("services.lab_recording_response.rederive_readout_with_slides")
    @patch("services.lab_recording_response.project_recording_progress")
    def test_unsent_take_stays_readout_ready_with_one_minimum_audit(
        self,
        project_progress,
        rederive_readout,
    ):
        project_progress.return_value = None
        rederive_readout.return_value = {"snippets": []}

        result = build_completed_recording_response(
            session_id="session-1",
            recording_id="recording-1",
            session_context={},
            readout={"snippets": []},
            sent_to_coach=False,
            arc_id=None,
            take_index=None,
            take_count=None,
            duration_seconds=0,
            user_id=None,
            database=Mock(),
            audit_paid_for_arc=Mock(return_value=False),
            log=Mock(),
        )

        self.assertEqual(result["state"], "readout_ready")
        self.assertEqual(result["audits_needed"], 1)
        self.assertEqual(result["duration_minutes"], 0.0)
