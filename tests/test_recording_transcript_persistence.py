"""Focused contracts for processed-recording transcript persistence."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.recording_state import RecordingState
from services.recording_transcript_persistence import persist_recording_transcript


def _state(*, slides=None) -> RecordingState:
    context = {"slide_advances": [{"index": 0, "t_ms": 0}]}
    if slides is not None:
        context["slides"] = slides
    return RecordingState(
        session_id="session-1",
        user_id="user-1",
        recording_id="recording-1",
        audio_bytes=b"audio",
        filename="take.webm",
        session_context=context,
        parent_audio_url="https://example.test/take.webm",
        recording_kind="spoken",
        paired_session_id=None,
        run_analytics=True,
        words_all=({"word": "Hello", "start": 0.0, "end": 1.0},),
        canonical_pieces=(
            {"index": 0, "transcript": "Hello", "duration_ms": 1000},
        ),
    )


class RecordingTranscriptPersistenceTests(unittest.TestCase):
    def test_deckless_uses_the_exact_canonical_pieces(self):
        database = MagicMock()

        persist_recording_transcript(_state(), database=database)

        persisted = database.set_session_slide_transcripts.call_args.args[1]
        self.assertEqual(persisted[0]["transcript"], "Hello")

    @patch(
        "services.slide_boundary_metrics.boundary_metrics",
        return_value={"words_at_risk": 1},
    )
    def test_deck_persists_complete_transcript_and_boundary_metrics(self, _metrics):
        database = MagicMock()

        persist_recording_transcript(
            _state(slides=[{"title": "One"}]),
            database=database,
        )

        database.set_session_slide_transcripts.assert_called_once()
        database.set_session_boundary_metrics.assert_called_once_with(
            "session-1",
            {"words_at_risk": 1},
        )

    @patch("services.f1_observability.observe_f1_degrade")
    def test_persistence_failure_is_observed_and_never_raised(self, observe):
        database = MagicMock()
        database.set_session_slide_transcripts.side_effect = RuntimeError("down")

        persist_recording_transcript(_state(), database=database)

        observe.assert_called_once()
        self.assertEqual(observe.call_args.args[0], "slide_transcript_failed")


if __name__ == "__main__":
    unittest.main()
