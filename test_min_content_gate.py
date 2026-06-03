"""Validation of the willab Lab min-content gate (design §4 / §5.5).

numpy-guarded: runs where numpy is installed, skips in the lean env.
Confirms the salvaged content-validity rule (≥60s + has-speech, NO
contrast requirement).

Run: python3 -m unittest test_min_content_gate
"""
from __future__ import annotations

import unittest

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_NUMPY, "numpy not installed in this env")
class MinContentGateTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from services.audio_metrics import SAMPLE_RATE
        cls.sr = SAMPLE_RATE

    def _tone(self, dur, f=150):
        t = np.arange(int(dur * self.sr)) / self.sr
        return (0.3 * np.sin(2 * np.pi * f * t)).astype(np.float32)

    def _sil(self, dur):
        return np.zeros(int(dur * self.sr), dtype=np.float32)

    def _eval(self, sig):
        from services.min_content_gate import evaluate_min_content
        return evaluate_min_content(sig)

    def test_65s_voiced_passes(self):
        out = self._eval(self._tone(65.0))
        self.assertTrue(out["ok"], out)
        self.assertIsNone(out["reason"])
        self.assertGreaterEqual(out["duration_sec"], 60.0)

    def test_exactly_60s_passes(self):
        out = self._eval(self._tone(60.0))
        self.assertTrue(out["ok"], out)

    def test_30s_too_short(self):
        out = self._eval(self._tone(30.0))
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "too_short")

    def test_just_under_60s_too_short(self):
        out = self._eval(self._tone(59.0))
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "too_short")

    def test_60s_of_silence_no_speech(self):
        out = self._eval(self._sil(62.0))
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "no_speech")
        self.assertLess(out["voiced_sec"], 3.0)

    def test_60s_mostly_silence_with_brief_speech_no_speech(self):
        # 61s total, only ~1s of speech → fails has-speech floor
        sig = np.concatenate([self._tone(1.0), self._sil(60.0)])
        out = self._eval(sig)
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "no_speech")

    def test_empty_no_audio(self):
        out = self._eval(np.zeros(0, dtype=np.float32))
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "no_audio")

    def test_no_contrast_requirement(self):
        """The salvaged gate is content-validity ONLY — a 60s+ voiced
        recording passes regardless of charisma/stress balance (the
        old contrast requirement is gone)."""
        out = self._eval(self._tone(61.0))
        self.assertTrue(out["ok"])
        # nothing in the result references charisma/stress
        self.assertNotIn("charisma", out)
        self.assertNotIn("stress", out)

    def test_thresholds_echoed(self):
        out = self._eval(self._tone(61.0))
        self.assertEqual(out["thresholds"]["min_duration_sec"], 60.0)
        self.assertEqual(out["thresholds"]["min_voiced_sec"], 3.0)


if __name__ == "__main__":
    unittest.main()
