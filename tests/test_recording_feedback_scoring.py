"""Focused contracts for the recording feedback-scoring stage."""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from services.recording_feedback_scoring import (
    join_recording_feedback,
    score_recording_feedback,
)
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

    def test_join_keeps_enriched_metrics_and_scoring_outputs(self):
        prepared = _state()
        enriched = RecordingState(**{
            **prepared.__dict__,
            "analyzed_pieces": ({
                **prepared.analyzed_pieces[0],
                "metrics": {
                    **prepared.analyzed_pieces[0]["metrics"],
                    "rich": True,
                },
            },),
            "raw_metrics_snapshot": ({"rich": True},),
        })
        scored = RecordingState(**{
            **prepared.__dict__,
            "stickiness": ({"composite": 0.8},),
            "slide_scores": ({"composite": 0.4},),
            "overall_by_index": {0: 0.6},
            "rank_by_index": {0: 1},
        })

        joined = join_recording_feedback(enriched, scored)

        self.assertTrue(joined.analyzed_pieces[0]["metrics"]["rich"])
        self.assertEqual(joined.stickiness, ({"composite": 0.8},))
        self.assertEqual(joined.rank_by_index, {0: 1})

    def test_join_rejects_outputs_from_different_recordings(self):
        enriched = _state()
        scored = RecordingState(**{
            **_state().__dict__,
            "recording_id": "different-recording",
        })

        with self.assertRaisesRegex(ValueError, "do not share identity"):
            join_recording_feedback(enriched, scored)


if __name__ == "__main__":
    unittest.main()
