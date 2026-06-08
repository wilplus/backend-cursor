"""f0 octave-outlier rejection (audio_metrics._reject_octave_outliers).

The bare autocorrelation pitch estimator emits sub-/super-harmonic frames
(≈2x / 0.5x the true pitch) that blow up f0_sd (the "mean pause 253.3s"
of pitch — an honest ~30 Hz SD became 114 Hz). This guards the median-
octave filter that removes them. numpy-guarded — skips in the lean env.

Run: python3 -m unittest test_f0_octave
"""
from __future__ import annotations

import unittest

try:
    import numpy as np  # noqa: F401
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_NUMPY, "numpy not installed in this env")
class OctaveRejectTests(unittest.TestCase):
    def _r(self, s):
        from services.audio_metrics import _reject_octave_outliers
        return _reject_octave_outliers(s)

    def test_rejects_octave_up_and_down(self):
        # true pitch ~110 Hz with octave-up (220) + octave-down (55) errors
        s = [110.0] * 20 + [220.0] * 4 + [55.0] * 2
        out = self._r(s)
        self.assertTrue(all(80.0 < f < 150.0 for f in out), out)
        self.assertNotIn(220.0, out)
        self.assertNotIn(55.0, out)

    def test_collapses_inflated_sd(self):
        from services.audio_metrics import _compute_f0_stats
        clean = self._r([110.0] * 20 + [220.0] * 4)
        sd = _compute_f0_stats(clean)[1]
        self.assertLess(sd, 25.0)   # tight, not the inflated 100+ Hz

    def test_keeps_genuine_half_octave_variation(self):
        # all within ~half an octave of the median → nothing pruned
        s = [100.0, 120.0, 140.0, 90.0, 110.0, 130.0]
        self.assertEqual(len(self._r(s)), len(s))

    def test_short_series_untouched(self):
        self.assertEqual(self._r([110.0, 220.0]), [110.0, 220.0])


if __name__ == "__main__":
    unittest.main()
