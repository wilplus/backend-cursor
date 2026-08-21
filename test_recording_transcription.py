"""Regression contract for the extracted recording transcription stage."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from services.recording_state import RecordingState
from services import recording_transcription as rt


def _module(name: str, **members):
    module = types.ModuleType(name)
    for key, value in members.items():
        setattr(module, key, value)
    return module


class RecordingTranscriptionTests(unittest.TestCase):
    def _state(self, **overrides) -> RecordingState:
        values = {
            "session_id": "session-1",
            "user_id": "user-1",
            "recording_id": "recording-1",
            "audio_bytes": b"recording",
            "filename": "take.webm",
            "session_context": {
                "domain_vocabulary": ["Willab"],
                "slides": [{"title": "Opening"}],
                "language": " pl ",
            },
            "parent_audio_url": "https://audio.example/take.webm",
            "recording_kind": "spoken",
            "paired_session_id": None,
            "run_analytics": True,
            "signal": [0.0, 0.1],
        }
        values.update(overrides)
        return RecordingState(**values)

    def _dependencies(self, service, *, charge=None, band=None, split=None):
        charge = charge or MagicMock()
        band = band or MagicMock(return_value="take_medium")
        split = split or (lambda words: words)
        return {
            "services.openai_service": _module(
                "services.openai_service",
                OpenAIService=MagicMock(return_value=service),
            ),
            "services.token_account": _module(
                "services.token_account",
                charge=charge,
            ),
            "services.token_prices": _module(
                "services.token_prices",
                band_for_seconds=band,
            ),
            "services.slide_word_split": _module(
                "services.slide_word_split",
                restore_punctuation=lambda words, segments: words,
                runon_split_enabled=lambda: True,
                split_runon_sentences=split,
            ),
        }, charge, band

    def test_transcription_returns_new_state_without_mutating_input(self):
        service = MagicMock()
        service.client = True
        service.transcribe_audio.return_value = {
            "duration": 240,
            "segments": [{"text": "Clear opening."}],
            "words": [{"word": "Clear", "start": 0.0, "end": 0.4}],
        }
        modules, charge, band = self._dependencies(service)
        state = self._state()

        with patch.dict(sys.modules, modules):
            result = rt.transcribe_recording(state)

        self.assertIsNot(result, state)
        self.assertEqual(state.segments, ())
        self.assertEqual(state.words_all, ())
        self.assertEqual(result.segments, ({"text": "Clear opening."},))
        self.assertEqual(result.words_all[0]["word"], "Clear")
        _audio, name = service.transcribe_audio.call_args.args
        kwargs = service.transcribe_audio.call_args.kwargs
        self.assertEqual(_audio.read(), b"recording")
        self.assertEqual(name, "take.webm")
        self.assertEqual(kwargs["vocabulary"], ["Willab", "Opening"])
        self.assertEqual(kwargs["language"], "pl")
        self.assertEqual(kwargs["usage_surface"], "whisper_spoken")
        self.assertEqual(kwargs["usage_user_id"], "user-1")
        self.assertEqual(kwargs["usage_session_id"], "session-1")
        band.assert_called_once_with(240)
        charge.assert_called_once_with(
            "user-1", "take_medium", ref_id="recording-1",
        )

    def test_state_is_frozen(self):
        state = self._state()
        with self.assertRaises(FrozenInstanceError):
            state.session_id = "changed"  # type: ignore[misc]

    def test_reread_uses_reread_charge_without_duration_band(self):
        service = MagicMock()
        service.client = True
        service.transcribe_audio.return_value = {
            "duration": 10,
            "segments": [],
            "words": [{"word": "Again", "start": 0.0, "end": 0.2}],
        }
        modules, charge, band = self._dependencies(service)

        with patch.dict(sys.modules, modules):
            rt.transcribe_recording(self._state(recording_kind="read"))

        band.assert_not_called()
        charge.assert_called_once_with(
            "user-1", "reread", ref_id="recording-1",
        )

    def test_charge_failure_does_not_discard_transcription(self):
        service = MagicMock()
        service.client = True
        service.transcribe_audio.return_value = {
            "duration": 20,
            "segments": [],
            "words": [{"word": "Kept", "start": 0.0, "end": 0.2}],
        }
        charge = MagicMock(side_effect=RuntimeError("ledger unavailable"))
        modules, _, _ = self._dependencies(service, charge=charge)

        with patch.dict(sys.modules, modules):
            result = rt.transcribe_recording(self._state())

        self.assertEqual(result.words_all[0]["word"], "Kept")

    def test_provider_failure_returns_empty_transcription_state(self):
        service = MagicMock()
        service.client = True
        service.transcribe_audio.side_effect = RuntimeError("provider down")
        modules, _, _ = self._dependencies(service)
        log = MagicMock()

        with patch.dict(sys.modules, modules):
            result = rt.transcribe_recording(self._state(), log=log)

        self.assertEqual(result.segments, ())
        self.assertEqual(result.words_all, ())
        self.assertTrue(log.warning.called)

    def test_missing_client_preserves_the_existing_empty_result(self):
        service = MagicMock()
        service.client = None
        modules, charge, band = self._dependencies(service)

        with patch.dict(sys.modules, modules):
            result = rt.transcribe_recording(self._state())

        service.transcribe_audio.assert_not_called()
        charge.assert_not_called()
        band.assert_not_called()
        self.assertEqual(result.words_all, ())

    def test_oversized_audio_uses_smaller_mp3_only_for_whisper(self):
        service = MagicMock()
        service.client = True
        service.transcribe_audio.return_value = {
            "duration": 2,
            "segments": [],
            "words": [{"word": "Hi", "start": 0.0, "end": 0.1}],
        }
        modules, _, _ = self._dependencies(service)
        compressor = MagicMock(return_value=b"mp3")
        modules["services.audio_metrics"] = _module(
            "services.audio_metrics",
            compress_audio_for_whisper=compressor,
        )

        with patch.dict(sys.modules, modules), patch.object(
            rt, "WHISPER_MAX_BYTES", 3,
        ):
            rt.transcribe_recording(self._state(audio_bytes=b"large-audio"))

        audio_file, name = service.transcribe_audio.call_args.args
        self.assertEqual(audio_file.read(), b"mp3")
        self.assertEqual(name, "lab.mp3")
        compressor.assert_called_once_with(b"large-audio")


if __name__ == "__main__":
    unittest.main()

