"""Focused contracts for canonical recording persistence."""
from __future__ import annotations

import logging
import unittest
from unittest.mock import MagicMock, patch

from services.recording_persistence import persist_recording_snippets
from services.recording_state import RecordingState


def _state() -> RecordingState:
    return RecordingState(
        session_id="session-1",
        user_id="user-1",
        recording_id="recording-1",
        audio_bytes=b"audio",
        filename="take.webm",
        session_context={},
        parent_audio_url="https://example.test/take.webm",
        recording_kind="spoken",
        paired_session_id=None,
        run_analytics=True,
        words_all=({"word": "Hello", "start": 0.0, "end": 1.0},),
        analyzed_pieces=(
            {
                "idx": 1,
                "start_ms": 0,
                "dur_ms": 1000,
                "transcript": "Hello",
                "metrics": {
                    "piece": {"index": 0},
                    "acoustic_read": {"score": 0.8},
                },
            },
        ),
        llm_budget_indices=frozenset({0}),
        raw_metrics_snapshot=(
            {"piece": {"index": 0}, "speech_rate": 120.0},
        ),
        stickiness=({"composite": 0.7, "comment": "Clear"},),
        slide_scores=({"composite": 0.5},),
        overall_by_index={0: 0.6},
        rank_by_index={0: 1},
    )


class RecordingPersistenceTests(unittest.TestCase):
    def test_bulk_rows_and_readout_ids_stay_in_piece_order(self):
        database = MagicMock()
        database.create_charisma_snippets_bulk.return_value = ["snippet-1"]
        database.insert_candidate_windows.return_value = 1

        result = persist_recording_snippets(_state(), database=database)

        row = database.create_charisma_snippets_bulk.call_args.args[0][0]
        self.assertEqual(row["transcript"], "Hello")
        self.assertEqual(row["metrics"]["rank"], 1)
        self.assertEqual(row["metrics"]["stickiness"]["composite"], 0.7)
        self.assertEqual(result.persisted_snippets[0]["id"], "snippet-1")
        self.assertEqual(
            result.stickiness_payload[0]["snippet_id"],
            "snippet-1",
        )

        candidate = database.insert_candidate_windows.call_args.args[0][0]
        encoded_features = str(candidate)
        self.assertNotIn("acoustic_read", encoded_features)
        self.assertNotIn("'piece'", encoded_features)

    @patch(
        "services.recording_persistence._raw_candidate_rows",
        side_effect=RuntimeError("candidate store unavailable"),
    )
    def test_candidate_capture_failure_never_loses_persisted_snippets(self, _rows):
        database = MagicMock()
        database.create_charisma_snippets_bulk.return_value = ["snippet-1"]

        result = persist_recording_snippets(
            _state(),
            database=database,
            log=logging.getLogger("test"),
        )

        self.assertEqual(result.persisted_snippets[0]["id"], "snippet-1")
        database.insert_candidate_windows.assert_not_called()


if __name__ == "__main__":
    unittest.main()
