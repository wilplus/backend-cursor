"""Validation of segment_into_snippets (willab Readout multi-snippet).

numpy-guarded: runs where numpy is installed, skips in the lean test
env. Exercises the VAD/pause carve on synthetic signals — multiple
speech blocks → multiple windows, continuous monologue → split by
max, silence/short → whole-recording fallback, top-N cap.

Run: python3 -m unittest test_segmentation
"""
from __future__ import annotations

import unittest

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_NUMPY, "numpy not installed in this env")
class SegmentationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from services.audio_metrics import SAMPLE_RATE
        cls.sr = SAMPLE_RATE

    def _tone(self, dur, f=150):
        t = np.arange(int(dur * self.sr)) / self.sr
        return (0.3 * np.sin(2 * np.pi * f * t)).astype(np.float32)

    def _sil(self, dur):
        return np.zeros(int(dur * self.sr), dtype=np.float32)

    def _seg(self, sig, **kw):
        from services.audio_metrics import segment_into_snippets
        return segment_into_snippets(sig, **kw)

    def test_three_blocks_separated_by_gaps_yield_three_windows(self):
        # 3 × 5s speech separated by 1s silences (> 0.6s gap)
        sig = np.concatenate([
            self._tone(5.0), self._sil(1.0),
            self._tone(5.0), self._sil(1.0),
            self._tone(5.0),
        ])
        out = self._seg(sig)
        self.assertEqual(len(out), 3, out)
        # chronological, non-overlapping
        for i in range(1, len(out)):
            self.assertLessEqual(out[i - 1][1], out[i][0] + 1)  # +pad tolerance
        # each window within sane duration
        for (s, e) in out:
            self.assertGreaterEqual(e - s, 3000)

    def test_short_gaps_do_not_split(self):
        # speech with only 0.3s gaps (< 0.6s) → one merged window.
        # Kept under SEGMENT_MAX_SEC (8s) so this isolates the GAP logic
        # — the separate max-length split is covered by
        # test_long_monologue_split_by_max.
        sig = np.concatenate([
            self._tone(2.0), self._sil(0.3),
            self._tone(2.0), self._sil(0.3),
            self._tone(2.0),
        ])
        out = self._seg(sig)
        self.assertEqual(len(out), 1, out)

    def test_long_monologue_split_by_max(self):
        # 40s continuous speech, no gaps → split into ceil(40/15)=3 chunks
        sig = self._tone(40.0)
        out = self._seg(sig, max_snippet_sec=15.0)
        self.assertGreaterEqual(len(out), 2)
        for (s, e) in out:
            # each chunk ≤ max (+ small pad tolerance)
            self.assertLessEqual(e - s, 15000 + 500)

    def test_top_n_cap(self):
        # 12 short-ish 4s blocks separated by gaps → capped to max_snippets
        blocks = []
        for _ in range(12):
            blocks.append(self._tone(4.0))
            blocks.append(self._sil(1.0))
        sig = np.concatenate(blocks)
        out = self._seg(sig, max_snippets=10)
        self.assertLessEqual(len(out), 10)

    def test_below_min_segment_dropped_then_whole_fallback(self):
        # two 1s blips (< 3s min), nothing qualifies → whole-recording fallback
        sig = np.concatenate([
            self._tone(1.0), self._sil(1.0), self._tone(1.0),
        ])
        out = self._seg(sig)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], 0)  # whole-recording window starts at 0

    def test_all_silence_returns_whole_recording(self):
        out = self._seg(self._sil(5.0))
        self.assertEqual(out, [(0, 5000)])

    def test_sub_one_second_returns_empty(self):
        out = self._seg(self._tone(0.5))
        self.assertEqual(out, [])

    def test_windows_within_recording_bounds(self):
        sig = np.concatenate([
            self._tone(5.0), self._sil(1.0), self._tone(5.0),
        ])
        total_ms = int(len(sig) / self.sr * 1000)
        out = self._seg(sig)
        for (s, e) in out:
            self.assertGreaterEqual(s, 0)
            self.assertLessEqual(e, total_ms)
            self.assertLess(s, e)


if __name__ == "__main__":
    unittest.main()
