"""The noise meter, silent first (founder 2026-09-28; §3.5a).

Pins:
  * separation_db is the gap between the loud (voice) and quiet (room)
    frames: large for a clean recording, small for a noisy one;
  * too short to judge answers None, never a guess;
  * it is saved with every clip snapshot and practice attempt;
  * the noise rule ships OFF: while off, the eligibility verdict and
    practice-attempt validity are identical whatever the reading;
  * switched on (proven here with a patched cut-off), a noisy clip gets no
    exercise and a noisy practice try does not count, a recording with no
    reading is never skipped, and the rule in force is recorded in the trace
    and the learning counter.
"""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

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


def _snippet(noise):
    return {"transcript": "one two three four five six", "duration_ms": 4000,
            "audio_ref": "s3://x",
            "words": [{"word": w, "start": i * 0.4, "end": i * 0.4 + 0.3,
                       "probability": 0.95}
                      for i, w in enumerate("one two three four five six".split())],
            "metrics": {"wpm": 190, "voiced_ratio": 0.6, "pause_ratio": 0.02,
                        "noise_meter": noise}}


def _attempt(sep):
    return {"duration_ms": 4000, "audio_ref": "s3://x",
            "acoustic_metrics": {"aligned_words": 9, "confidence": 0.3,
                                 "voiced_ratio": 0.6, "noise_separation_db": sep}}


CLEAN = am._noise_meter(_clip(-60.0))     # 48 dB above the room
NOISY = am._noise_meter(_clip(-14.0))     # 2 dB above the room


class SwitchOffTests(unittest.TestCase):
    """The switch ships OFF: nothing decides anything on the reading."""

    def test_it_ships_off(self):
        self.assertIsNone(cvp.NOISE_GATE_MIN_SEPARATION_DB)
        self.assertEqual(cvp.noise_gate_version(), "noise-gate-v1:off")

    def test_the_clip_verdict_ignores_it(self):
        clean = cvp.exercise_eligibility(_snippet(CLEAN))
        noisy = cvp.exercise_eligibility(_snippet(NOISY))
        for key in ("eligible", "reason", "pattern", "signals"):
            self.assertEqual(clean.get(key), noisy.get(key), key)

    def test_attempt_validity_ignores_it(self):
        self.assertEqual(lr.attempt_is_valid(_attempt(48.0)),
                         lr.attempt_is_valid(_attempt(2.0)))

    def test_the_analysis_never_writes_the_old_key(self):
        # The gate also reads metrics["audio_quality"]; the analysis must not
        # write it, or that older check would switch on silently.
        self.assertNotIn('"audio_quality"', inspect.getsource(am._analyze_pcm))


class SwitchOnTests(unittest.TestCase):
    """What switching it on will do, proven now so the switch is one line."""

    def setUp(self):
        patcher = patch.object(cvp, "NOISE_GATE_MIN_SEPARATION_DB", 12.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_noisy_clip_gets_no_exercise(self):
        self.assertEqual(cvp.exercise_eligibility(_snippet(NOISY))["reason"],
                         "audio_quality")
        self.assertNotEqual(cvp.exercise_eligibility(_snippet(CLEAN))["reason"],
                            "audio_quality")

    def test_a_noisy_practice_try_does_not_count(self):
        self.assertFalse(lr.attempt_is_valid(_attempt(2.0)))
        self.assertTrue(lr.attempt_is_valid(_attempt(48.0)))

    def test_no_reading_is_never_skipped(self):
        self.assertTrue(lr.attempt_is_valid(_attempt(None)))
        self.assertNotEqual(cvp.exercise_eligibility(_snippet(None))["reason"],
                            "audio_quality")

    def test_the_rule_in_force_is_recorded(self):
        self.assertEqual(cvp.noise_gate_version(), "noise-gate-v1:12db")
        trace = cvp.build_match_trace(
            lane="v3_exercise_block", verdict={"pattern": "confident"},
            vocabulary=frozenset(), exercises=[], ranked=[], fit=None,
            snippet={}, take_session_id="t", snippet_id="s")
        self.assertEqual(trace["gate"]["noise_gate_version"], "noise-gate-v1:12db")
        out = lr.build_readiness(signal_rules_version="v", exposures=[],
                                 assignments={}, traces={}, practices={},
                                 attempts={})
        self.assertEqual(out["noise_gate_version"], "noise-gate-v1:12db")
