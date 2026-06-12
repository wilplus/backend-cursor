"""Regression: the snippet 'speed' (speech_rate) metric was always '—'.

Cause: process_lab_recording called analyze_pcm_window WITHOUT the transcript,
so wpm (= words / minutes) was never computed → speech_rate null → '—'. Fix:
slice the transcript first and pass it in.

Run: python3 -m unittest test_speed_metric
"""
from __future__ import annotations

import unittest


class SpeedMetricTests(unittest.TestCase):
    def test_speech_rate_maps_from_wpm(self):
        from services.lab_recording import build_readout_features
        self.assertEqual(build_readout_features({"wpm": 145.0}).get("speech_rate"), 145.0)
        # absent wpm → speech_rate None (the "—" the user saw)
        self.assertIsNone(build_readout_features({}).get("speech_rate"))

    def test_speech_rate_pct_scales_125wpm_to_100(self):
        from services.lab_recording import build_readout_features
        # 125 wpm = 100% (calm/clear public-speaking pace); proportional otherwise.
        self.assertEqual(build_readout_features({"wpm": 125}).get("speech_rate_pct"), 100)
        self.assertEqual(build_readout_features({"wpm": 90}).get("speech_rate_pct"), 72)
        self.assertEqual(build_readout_features({"wpm": 150}).get("speech_rate_pct"), 120)
        self.assertEqual(build_readout_features({"wpm": 100}).get("speech_rate_pct"), 80)
        # None-safe
        self.assertIsNone(build_readout_features({}).get("speech_rate_pct"))

    def test_window_with_transcript_yields_wpm(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy not installed")
        from services.audio_metrics import analyze_pcm_window
        sig = (0.05 * np.random.randn(16000 * 3)).astype("float32")  # 3s
        with_tx = analyze_pcm_window(
            sig, start_offset_ms=0, duration_ms=3000,
            transcript="one two three four five six",  # 6 words / 0.05 min = 120
        )
        self.assertIsNotNone((with_tx or {}).get("wpm"))
        # the bug: no transcript → wpm None
        without_tx = analyze_pcm_window(sig, start_offset_ms=0, duration_ms=3000)
        self.assertIsNone((without_tx or {}).get("wpm"))


if __name__ == "__main__":
    unittest.main()
