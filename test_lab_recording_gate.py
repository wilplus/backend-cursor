"""Unit tests for the Lab upload minimum-content gate boundary."""
from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from services.lab_recording_gate import (
    RecordingRejected,
    require_analyzable_recording,
)


class RecordingGateTests(unittest.TestCase):

    def test_valid_audio_returns_the_original_gate_metrics(self):
        gate = {"ok": True, "duration_sec": 12.4, "voiced_sec": 8.1}
        database = Mock()
        with patch(
            "services.min_content_gate.evaluate_min_content_bytes",
            return_value=gate,
        ):
            result = require_analyzable_recording(
                b"audio",
                database=database,
                form={},
                user_id="user-1",
                log=Mock(),
            )
        self.assertIs(result, gate)
        database.insert_rejected_take.assert_not_called()

    def test_rejection_records_metrics_without_storing_audio(self):
        gate = {
            "ok": False,
            "reason": "no_speech",
            "duration_sec": 4.2,
            "voiced_sec": 0.0,
            "thresholds": {"min_voiced_sec": 0.5},
        }
        database = Mock()
        form = {
            "guest_session_id": "guest-1",
            "arc_id": "arc-1",
            "take_index": "2",
        }
        with patch(
            "services.min_content_gate.evaluate_min_content_bytes",
            return_value=gate,
        ), self.assertRaises(RecordingRejected) as raised:
            require_analyzable_recording(
                b"audio",
                database=database,
                form=form,
                user_id="user-1",
                log=Mock(),
            )

        self.assertIs(raised.exception.gate, gate)
        database.insert_rejected_take.assert_called_once_with(
            reason="no_speech",
            duration_sec=4.2,
            voiced_sec=0.0,
            thresholds={"min_voiced_sec": 0.5},
            user_id="user-1",
            guest_session_id="guest-1",
            arc_id="arc-1",
            take_index="2",
        )

    def test_metrics_write_failure_never_changes_the_user_rejection(self):
        gate = {"ok": False, "reason": "no_speech"}
        database = Mock()
        database.insert_rejected_take.side_effect = RuntimeError("db down")
        log = Mock()
        with patch(
            "services.min_content_gate.evaluate_min_content_bytes",
            return_value=gate,
        ), self.assertRaises(RecordingRejected) as raised:
            require_analyzable_recording(
                b"audio",
                database=database,
                form={},
                user_id=None,
                log=log,
            )
        self.assertIs(raised.exception.gate, gate)
        log.warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
