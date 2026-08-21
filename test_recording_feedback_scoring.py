"""Focused contracts for the recording feedback-scoring stage."""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from services.recording_feedback_scoring import score_recording_feedback
from services.recording_state import RecordingState


def _state(*, run_analytics: bool = True) -> RecordingState:
    return RecordingState(
        session_id="session-1",
        user_id="user-1",
        recording_id="recording-1",
        audio_bytes=b"audio",
        filename="take.webm",
        session_context={"slides": [{"title": "One"}]},
        parent_audio_url="https://example.test/take.webm",
        recording_kind="spoken",
        paired_session_id=None,
        run_analytics=run_analytics,
        analyzed_pieces=(
            {
                "start_ms": 0,
                "dur_ms": 1000,
                "transcript": "Hello",
                "metrics": {"piece": {"index": 0, "slide_index": 0}},
            },
        ),
        llm_budget_indices=frozenset({0}),
    )


class FeedbackScoringStageTests(unittest.TestCase):
    @patch(
        "services.snippet_stickiness.score_snippets_stickiness",
        return_value=[{"composite": 0.8, "comment": "Clear"}],
    )
    @patch(
        "services.slide_alignment.compute_piece_slide_scores",
        return_value=[{"composite": 0.4}],
    )
    def test_stage_returns_ranked_state_without_mutating_input(
        self,
        _slides,
        _stickiness,
    ):
        original = _state()
        result = score_recording_feedback(original)

        self.assertIsNot(result, original)
        self.assertEqual(original.stickiness, ())
        self.assertEqual(result.stickiness[0]["composite"], 0.8)
        self.assertAlmostEqual(result.overall_by_index[0], 0.6)
        self.assertEqual(result.rank_by_index, {0: 1})

    @patch("services.snippet_stickiness.score_snippets_stickiness")
    @patch(
        "services.slide_alignment.compute_piece_slide_scores",
        side_effect=RuntimeError("model unavailable"),
    )
    def test_analytics_off_and_slide_failure_remain_nonfatal(
        self,
        _slides,
        stickiness,
    ):
        result = score_recording_feedback(
            _state(run_analytics=False),
            log=logging.getLogger("test"),
        )

        stickiness.assert_not_called()
        self.assertEqual(result.stickiness, ({},))
        self.assertEqual(result.slide_scores, ())
        self.assertEqual(result.overall_by_index, {0: 0.0})


if __name__ == "__main__":
    unittest.main()
