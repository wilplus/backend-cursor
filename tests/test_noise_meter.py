"""The noise meter, silent first (founder 2026-09-28; §3.5a).

Pins:
  * separation_db is the gap between the loud (voice) and quiet (room)
    frames: large for a clean recording, small for a noisy one;
  * too short to judge answers None, never a guess;
  * it is saved with every clip snapshot and practice attempt;
  * SILENT: no rule reads it — the clip gate, the eligibility verdict and
    the practice-attempt validity are unchanged by any noise reading, and
    it never uses the `audio_quality` key the clip gate reads.
"""
from __future__ import annotations

import inspect
import unittest

import numpy as np

from services import audio_metrics as am
from services import confident_voice_practice as cvp
from services import exercise_learning_readiness as lr


def _clip(noise_db: float, n: int = 200) -> np.ndarray:
    """Frame loudness: speech bursts at -12 dB over a room at `noise_db`."""
    frames = np.full(n, noise_db, dtype=np.float32)
    frames[::2] = -12.0
    return frames


class MeterTests(unittest.TestCase):
    def test_a_clean_recording_has_a_wide_gap(self):
        meter = am._noise_meter(_clip(-60.0))
        self.assertEqual(meter["version"], "noise-meter-v1")
        self.assertEqual((meter["voice_db"], meter["background_db"],
                          meter["separation_db"]), (-12.0, -60.0, 48.0))

    def test_a_noisy_recording_has_a_narrow_one(self):
        self.assertLess(am._noise_meter(_clip(-20.0))["separation_db"],
                        am._noise_meter(_clip(-60.0))["separation_db"])

    def test_too_short_to_judge_is_none(self):
        self.assertIsNone(am._noise_meter(_clip(-60.0, n=10)))
        self.assertIsNone(am._noise_meter(None))

    def test_it_is_part_of_every_analysis(self):
        self.assertIn('"noise_meter": _noise_meter(dbs)',
                      inspect.getsource(am._analyze_pcm))


class SavedTests(unittest.TestCase):
    def test_saved_with_the_snapshot(self):
        snap = cvp.acoustic_snapshot({"metrics": {"noise_meter":
                                                  am._noise_meter(_clip(-60.0))}})
        self.assertEqual((snap["noise_separation_db"], snap["noise_meter_version"]),
                         (48.0, "noise-meter-v1"))

    def test_an_older_recording_has_none(self):
        snap = cvp.acoustic_snapshot({"metrics": {}})
        self.assertIsNone(snap["noise_separation_db"])
        self.assertIsNone(snap["noise_meter_version"])


class SilentTests(unittest.TestCase):
    """Nothing decides anything on the noise reading yet."""

    def _snippet(self, noise):
        return {"transcript": "one two three four five six", "duration_ms": 4000,
                "audio_ref": "s3://x",
                "words": [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3,
                           "probability": 0.95}
                          for i, w in enumerate("one two three four five six".split())],
                "metrics": {"wpm": 190, "voiced_ratio": 0.6, "pause_ratio": 0.02,
                            "noise_meter": noise}}

    def test_the_clip_verdict_ignores_it(self):
        clean = cvp.exercise_eligibility(self._snippet(am._noise_meter(_clip(-60.0))))
        noisy = cvp.exercise_eligibility(self._snippet(am._noise_meter(_clip(-14.0))))
        for key in ("eligible", "reason", "pattern", "signals"):
            self.assertEqual(clean.get(key), noisy.get(key), key)

    def test_attempt_validity_ignores_it(self):
        def attempt(sep):
            return {"duration_ms": 4000, "audio_ref": "s3://x",
                    "acoustic_metrics": {"aligned_words": 9, "confidence": 0.3,
                                         "voiced_ratio": 0.6,
                                         "noise_separation_db": sep}}
        self.assertEqual(lr.attempt_is_valid(attempt(48.0)),
                         lr.attempt_is_valid(attempt(2.0)))

    def test_no_rule_reads_it(self):
        for fn in (cvp.exercise_eligibility, cvp.clip_signals, cvp._audio_reliable,
                   lr.attempt_is_valid):
            self.assertNotIn("noise_separation_db", inspect.getsource(fn))
            self.assertNotIn("noise_meter", inspect.getsource(fn))
        # The clip gate reads metrics["audio_quality"]; the analysis must not
        # write it, or the gate would switch on silently.
        self.assertNotIn('"audio_quality"', inspect.getsource(am._analyze_pcm))
