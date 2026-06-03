"""Validation of the willab Readout feature additions to audio_metrics.

The 6 features that completed the 10-feature Readout set (design §5):
f0_mean, f0_sd, f0_slope, f0_mid_end_delta, pause_ratio,
pause_regularity, intensity_envelope (+ a precise time-based
voiced_ratio).

numpy-guarded: skips entirely where numpy isn't installed (the
default lean test env), runs where it is. librosa is NOT required —
the librosa block in _analyze_pcm is best-effort and skips when
absent, which these tests also confirm.

Run (where numpy is present): python3 -m unittest test_audio_metrics_features
"""
from __future__ import annotations

import unittest

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_NUMPY, "numpy not installed in this env")
class ReadoutFeatureTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from services.audio_metrics import SAMPLE_RATE
        cls.sr = SAMPLE_RATE

    def _tone(self, f, dur):
        t = np.arange(int(dur * self.sr)) / self.sr
        return (0.3 * np.sin(2 * np.pi * f * t)).astype(np.float32)

    def _sil(self, dur):
        return np.zeros(int(dur * self.sr), dtype=np.float32)

    def _rising(self):
        # voiced 150Hz / pause / voiced 200Hz / pause
        return np.concatenate([
            self._tone(150, 1.0), self._sil(0.5),
            self._tone(200, 1.0), self._sil(0.5),
        ])

    def _analyze(self, sig, **kw):
        from services.audio_metrics import _analyze_pcm
        kw.setdefault("transcript", "one two three four five six")
        kw.setdefault("duration_sec", len(sig) / float(self.sr))
        return _analyze_pcm(sig, **kw)

    def test_all_ten_readout_features_present(self):
        out = self._analyze(self._rising())
        for k in ("f0_mean", "f0_sd", "speech_rate" if False else "wpm",
                  "pause_ms", "pause_ratio", "dynamic_db", "voiced_ratio",
                  "f0_slope", "pause_regularity", "intensity_envelope",
                  "f0_mid_end_delta"):
            self.assertIn(k, out, f"missing Readout feature: {k}")

    def test_f0_mean_in_expected_band(self):
        out = self._analyze(self._rising())
        self.assertIsNotNone(out["f0_mean"])
        self.assertTrue(100 < out["f0_mean"] < 260, out["f0_mean"])

    def test_f0_sd_positive_for_varying_pitch(self):
        out = self._analyze(self._rising())
        self.assertIsNotNone(out["f0_sd"])
        self.assertGreater(out["f0_sd"], 0)

    def test_f0_slope_positive_for_rising_pitch(self):
        """150Hz → 200Hz over the snippet ⇒ positive Hz/sec slope."""
        out = self._analyze(self._rising())
        self.assertIsNotNone(out["f0_slope"])
        self.assertGreater(out["f0_slope"], 0)

    def test_pause_ratio_in_unit_range(self):
        out = self._analyze(self._rising())
        self.assertIsNotNone(out["pause_ratio"])
        self.assertTrue(0.0 <= out["pause_ratio"] <= 1.0)

    def test_pause_regularity_high_for_equal_pauses(self):
        """Two equal 0.5s pauses ⇒ regularity ≈ 1.0."""
        out = self._analyze(self._rising())
        self.assertIsNotNone(out["pause_regularity"])
        self.assertGreater(out["pause_regularity"], 0.9)

    def test_pause_regularity_none_with_under_two_pauses(self):
        # one voiced block, one trailing pause → <2 pauses → None
        sig = np.concatenate([self._tone(150, 1.2), self._sil(0.5)])
        out = self._analyze(sig)
        self.assertIsNone(out["pause_regularity"])

    def test_voiced_ratio_in_unit_range(self):
        out = self._analyze(self._rising())
        self.assertIsNotNone(out["voiced_ratio"])
        self.assertTrue(0.0 <= out["voiced_ratio"] <= 1.0)

    def test_librosa_block_gracefully_absent(self):
        """When librosa isn't installed the librosa keys are simply
        absent — the base metrics still return (best-effort contract)."""
        out = self._analyze(self._rising())
        try:
            import librosa  # noqa: F401
            _has_librosa = True
        except ImportError:
            _has_librosa = False
        if not _has_librosa:
            self.assertNotIn("mfcc_mean", out)
        # base metrics present regardless
        self.assertIn("f0_mean", out)

    def test_short_signal_returns_none(self):
        out = self._analyze(self._tone(150, 0.5))  # < 1s → too short
        self.assertIsNone(out)


if __name__ == "__main__":
    unittest.main()
