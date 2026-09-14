"""Focused contracts for the canonical-piece analysis stage."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.recording_piece_analysis import (
    PiecesCanonicalUnavailable,
    analyze_canonical_pieces,
    build_canonical_pieces,
    enrich_canonical_pieces,
    prepare_canonical_pieces,
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

    @patch("services.recording_piece_analysis._attach_voice_confidence")
    @patch("services.recording_piece_analysis._refresh_acoustic_baseline")
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
        baseline,
        _confidence,
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

        original = _state()

        result = analyze_canonical_pieces(original)

        self.assertIsNot(result, original)
        self.assertEqual(original.analyzed_pieces, ())
        self.assertNotIn("acoustic_read", result.raw_metrics_snapshot[0])
        self.assertNotIn("acoustic_read", result.analyzed_pieces[0]["metrics"])
        baseline.assert_called_once()
        self.assertEqual(result.llm_budget_indices, frozenset({0}))

    @patch("services.recording_piece_analysis._attach_voice_confidence")
    @patch("services.recording_piece_analysis._refresh_acoustic_baseline")
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
    ):
        analyze_canonical_pieces(_state(run_analytics=False))
        budget_indices.assert_called_once_with([], 0)

    @patch("services.recording_piece_analysis._budget_indices", return_value={0})
    @patch("services.recording_piece_analysis._core_metrics")
    @patch("services.recording_piece_analysis.build_canonical_pieces")
    def test_prepared_state_is_the_immutable_parallel_prerequisite(
        self,
        build_pieces,
        core_metrics,
        _budget,
    ):
        build_pieces.return_value = [{"transcript": "Hello"}]
        core_metrics.return_value = [{
            "idx": 1,
            "start_ms": 0,
            "dur_ms": 1000,
            "transcript": "Hello",
            "metrics": {"piece": {"index": 0}, "speech_rate": 120.0},
        }]

        prepared = prepare_canonical_pieces(_state())

        self.assertEqual(prepared.llm_budget_indices, frozenset({0}))
        self.assertEqual(prepared.raw_metrics_snapshot, ())
        self.assertEqual(
            prepared.analyzed_pieces[0]["metrics"]["speech_rate"],
            120.0,
        )

    @patch("services.recording_piece_analysis._attach_voice_confidence")
    @patch("services.recording_piece_analysis._refresh_acoustic_baseline")
    @patch("services.recording_piece_analysis._upgrade_budget_metrics")
    def test_enrichment_clones_metrics_before_derived_mutation(
        self,
        upgrade,
        _baseline,
        attach,
    ):
        prepared = RecordingState(
            **{
                **_state().__dict__,
                "analyzed_pieces": ({
                    "idx": 1,
                    "start_ms": 0,
                    "dur_ms": 1000,
                    "transcript": "Hello",
                    "metrics": {"piece": {"index": 0}},
                },),
                "llm_budget_indices": frozenset({0}),
            }
        )

        def _stamp(_state, analyzed, _budget):
            analyzed[0]["metrics"]["rich"] = True

        def _derive(_state, analyzed, *, log):
            analyzed[0]["metrics"]["acoustic_read"] = {"label": "x"}

        upgrade.side_effect = _stamp
        attach.side_effect = _derive

        enriched = enrich_canonical_pieces(prepared)

        self.assertNotIn("rich", prepared.analyzed_pieces[0]["metrics"])
        self.assertNotIn(
            "acoustic_read", prepared.analyzed_pieces[0]["metrics"]
        )
        self.assertTrue(enriched.raw_metrics_snapshot[0]["rich"])
        self.assertNotIn(
            "acoustic_read", enriched.raw_metrics_snapshot[0]
        )
        self.assertIn(
            "acoustic_read", enriched.analyzed_pieces[0]["metrics"]
        )


if __name__ == "__main__":
    unittest.main()
