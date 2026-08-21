"""Focused contracts for the canonical-piece analysis stage."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.recording_piece_analysis import (
    PiecesCanonicalUnavailable,
    analyze_canonical_pieces,
    build_canonical_pieces,
)
from services.recording_state import RecordingState


def _state(*, run_analytics: bool = True) -> RecordingState:
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
        run_analytics=run_analytics,
        signal=object(),
        words_all=({"word": "Hello", "start": 0.0, "end": 1.0},),
    )


class CanonicalPieceAnalysisTests(unittest.TestCase):
    def test_missing_word_timestamps_fail_instead_of_selecting_a_fallback(self):
        with self.assertRaises(PiecesCanonicalUnavailable):
            build_canonical_pieces([], {})

    @patch("services.recording_piece_analysis._attach_user_tone")
    @patch("services.recording_piece_analysis._attach_voice_confidence")
    @patch("services.recording_piece_analysis._attach_acoustic_enrichment")
    @patch("services.recording_piece_analysis._upgrade_budget_metrics")
    @patch("services.recording_piece_analysis._budget_indices", return_value={0})
    @patch("services.recording_piece_analysis._core_metrics")
    @patch("services.recording_piece_analysis.build_canonical_pieces")
    def test_stage_returns_new_state_and_keeps_raw_snapshot_pre_enrichment(
        self,
        build_pieces,
        core_metrics,
        _budget,
        _upgrade,
        acoustic,
        _confidence,
        _tone,
    ):
        piece = {
            "index": 0,
            "transcript": "Hello",
            "start_offset_ms": 0,
            "duration_ms": 1000,
        }
        analyzed = {
            "idx": 1,
            "start_ms": 0,
            "dur_ms": 1000,
            "transcript": "Hello",
            "metrics": {"speech_rate": 120.0},
        }
        build_pieces.return_value = [piece]
        core_metrics.return_value = [analyzed]

        def attach_derived(_state, rows, *, log):
            rows[0]["metrics"]["acoustic_read"] = {"score": 0.8}

        acoustic.side_effect = attach_derived
        original = _state()

        result = analyze_canonical_pieces(original)

        self.assertIsNot(result, original)
        self.assertEqual(original.analyzed_pieces, ())
        self.assertNotIn("acoustic_read", result.raw_metrics_snapshot[0])
        self.assertEqual(
            result.analyzed_pieces[0]["metrics"]["acoustic_read"],
            {"score": 0.8},
        )
        self.assertEqual(result.llm_budget_indices, frozenset({0}))

    @patch("services.recording_piece_analysis._attach_user_tone")
    @patch("services.recording_piece_analysis._attach_voice_confidence")
    @patch("services.recording_piece_analysis._attach_acoustic_enrichment")
    @patch("services.recording_piece_analysis._upgrade_budget_metrics")
    @patch("services.recording_piece_analysis._budget_indices", return_value=set())
    @patch("services.recording_piece_analysis._core_metrics", return_value=[])
    @patch(
        "services.recording_piece_analysis.build_canonical_pieces",
        return_value=[{"transcript": "Hello"}],
    )
    def test_analytics_off_passes_zero_budget(
        self,
        _build,
        _core,
        budget_indices,
        _upgrade,
        _acoustic,
        _confidence,
        _tone,
    ):
        analyze_canonical_pieces(_state(run_analytics=False))
        budget_indices.assert_called_once_with([], 0)


if __name__ == "__main__":
    unittest.main()
