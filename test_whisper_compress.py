"""Regression for the HTTP 413 fix: oversized recordings compress for Whisper.

A multi-minute presentation recording exceeded the lab 25MB cap (413) and would
also exceed OpenAI Whisper's own 25MB limit. Fix: raise the upload cap +
compress oversized audio to a 16kHz mono mp3 before transcription.

Run: python3 -m unittest test_whisper_compress
"""
from __future__ import annotations

import unittest


class CompressForWhisperTests(unittest.TestCase):
    def test_garbage_returns_none(self):
        # ffmpeg rejects non-audio (or is absent) → None → caller falls back to
        # the original bytes; never raises.
        from services.audio_metrics import compress_audio_for_whisper
        self.assertIsNone(compress_audio_for_whisper(b"not audio at all"))

    def test_whisper_threshold_below_openai_limit(self):
        # compress kicks in below OpenAI Whisper's 25MB hard cap.
        from services.lab_recording import _WHISPER_MAX_BYTES
        self.assertLess(_WHISPER_MAX_BYTES, 25 * 1024 * 1024)
        self.assertGreaterEqual(_WHISPER_MAX_BYTES, 20 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
