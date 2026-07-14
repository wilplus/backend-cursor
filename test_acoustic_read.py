"""willab — the deterministic stress↔charisma read (founder 2026-07-14).

services/acoustic_read.py: the coach-only potentiometer + outside-normal-range
triage flag, and services/auto_comment.py: the per-piece qualitative comment.

FENCES tested here:
  * potentiometer ∈ [-1, 1], deterministic (same input → same output), no
    learned-model input anywhere in the composite;
  * the auto comment is digit-free + construct-safe (AC-9 guard) and the tone
    word is exactly the founder mapping (challenge→confident, threat→stressed).

Run: python3 -m unittest test_acoustic_read
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


def _metrics(f0_sd=30.0, pause_regularity=0.5, dynamic_db=12.0,
             voiced_ratio=0.7, **over):
    m = {"f0_sd": f0_sd, "pause_regularity": pause_regularity,
         "dynamic_db": dynamic_db, "voiced_ratio": voiced_ratio,
         "wpm": 140, "pause_ms": 300, "f0_mean": 160.0}
    m.update(over)
    return m


def _pieces(n=6, spread=False):
    out = []
    for i in range(n):
        # spread=True makes the last piece strongly atypical
        boost = 5.0 if (spread and i == n - 1) else (0.1 * i)
        out.append({
            "start_ms": i * 4000, "dur_ms": 3500,
            "metrics": _metrics(f0_sd=30.0 + boost * 10,
                                dynamic_db=12.0 + boost),
            "transcript": f"piece {i}",
        })
    return out


class AttachAcousticReadTests(unittest.TestCase):

    def _attach(self, pieces, baseline=None):
        from services.acoustic_read import attach_acoustic_read
        attach_acoustic_read(pieces, baseline=baseline)
        return pieces

    def test_potentiometer_bounded_and_stamped(self):
        pieces = self._attach(_pieces())
        for p in pieces:
            read = p["metrics"].get("acoustic_read")
            self.assertIsInstance(read, dict)
            self.assertGreaterEqual(read["potentiometer"], -1.0)
            self.assertLessEqual(read["potentiometer"], 1.0)
            self.assertIn(read["outside_normal_range"], (True, False))
            self.assertEqual(read["version"], "acoustic-read-v1")
            self.assertEqual(read["baseline"], "take")

    def test_deterministic_same_input_same_output(self):
        a = self._attach(_pieces())
        b = self._attach(_pieces())
        for pa, pb in zip(a, b):
            self.assertEqual(pa["metrics"]["acoustic_read"],
                             pb["metrics"]["acoustic_read"])

    def test_outlier_flags_outside_normal_range(self):
        pieces = self._attach(_pieces(n=8, spread=True))
        flags = [p["metrics"]["acoustic_read"]["outside_normal_range"]
                 for p in pieces]
        self.assertTrue(flags[-1])            # the injected outlier
        self.assertFalse(all(flags[:-1]))     # the pack isn't all-flagged

    def test_user_baseline_marks_source(self):
        baseline = {"f0_sd": (30.0, 5.0), "pause_regularity": (0.5, 0.1),
                    "dynamic_db": (12.0, 2.0), "voiced_ratio": (0.7, 0.05)}
        pieces = self._attach(_pieces(), baseline=baseline)
        self.assertEqual(
            pieces[0]["metrics"]["acoustic_read"]["baseline"], "user")

    def test_empty_metrics_gets_no_read(self):
        pieces = [{"start_ms": 0, "dur_ms": 500, "metrics": {},
                   "transcript": "too short"}]
        self._attach(pieces)
        self.assertNotIn("acoustic_read", pieces[0]["metrics"])

    def test_never_raises_on_garbage(self):
        from services.acoustic_read import attach_acoustic_read
        attach_acoustic_read(None)
        attach_acoustic_read([{"metrics": "not-a-dict"}, 42, None])


class ToneHintTests(unittest.TestCase):

    def test_founder_mapping(self):
        from services.acoustic_read import tone_hint
        self.assertEqual(tone_hint({"potentiometer": 0.6}), "confident")
        self.assertEqual(tone_hint({"potentiometer": -0.6}), "stressed")
        self.assertIsNone(tone_hint({"potentiometer": 0.1}))
        self.assertIsNone(tone_hint(None))
        self.assertIsNone(tone_hint({"potentiometer": "x"}))


class ToneWordResolutionTests(unittest.TestCase):
    """learned_tone_word (USER surface — the founder carve-out) vs
    acoustic_tone_word (COACH surface — model-free by fence)."""

    def _learned(self, metrics, shadow=None):
        from services import auto_comment as mod
        pred = ({"label": shadow[0], "confidence": shadow[1],
                 "model_version": "t"} if shadow else None)
        with patch("services.learning_serve.predict_direction",
                   return_value=pred):
            return mod.learned_tone_word(metrics)

    def test_learned_wins_when_confident(self):
        # Founder-locked carve-out: threat → "stressed" even when the
        # acoustic lean says otherwise.
        m = _metrics(acoustic_read={"potentiometer": 0.7,
                                    "outside_normal_range": False,
                                    "baseline": "take",
                                    "version": "acoustic-read-v1"})
        self.assertEqual(self._learned(m, shadow=("threat", 0.9)), "stressed")

    def test_low_confidence_falls_back_to_acoustic(self):
        m = _metrics(acoustic_read={"potentiometer": -0.7,
                                    "outside_normal_range": False,
                                    "baseline": "take",
                                    "version": "acoustic-read-v1"})
        self.assertEqual(self._learned(m, shadow=("challenge", 0.4)),
                         "stressed")  # acoustic lean won

    def test_coach_tone_is_model_free(self):
        # acoustic_tone_word must NEVER consult the model — even a confident
        # shadow read is invisible to it (BLIND COACH). Patch predict to
        # PROVE it isn't called.
        from services import auto_comment as mod
        m = _metrics(acoustic_read={"potentiometer": 0.7,
                                    "outside_normal_range": False,
                                    "baseline": "take",
                                    "version": "acoustic-read-v1"})
        with patch("services.learning_serve.predict_direction") as m_pred:
            out = mod.acoustic_tone_word(m)
        self.assertEqual(out, "confident")
        m_pred.assert_not_called()


class AutoCommentTests(unittest.TestCase):

    def _build(self, metrics, means, tone_word=None):
        from services import auto_comment as mod
        return mod.build_auto_comment(metrics, means, tone_word=tone_word)

    def test_tone_word_rides_the_sentence(self):
        out = self._build(_metrics(),
                          {"pace": 140.0, "pausing": 0.3, "energy": 12.0},
                          tone_word="confident")
        self.assertIsNotNone(out)
        self.assertIn("sounded rather confident", out)

    def test_no_tone_no_observations_is_none(self):
        out = self._build(_metrics(), {})  # no means, no tone → silence
        self.assertIsNone(out)

    def test_observations_without_tone_still_speak(self):
        # pace 140 vs mean 100 → "faster than your average" observation.
        out = self._build(_metrics(wpm=140), {"pace": 100.0})
        self.assertIsNotNone(out)
        self.assertIn("faster than your average", out)
        self.assertNotIn("sounded rather", out)

    def test_ac9_no_digits_no_construct(self):
        import re
        means = {"pace": 100.0, "pausing": 0.2, "energy": 10.0}
        out = self._build(_metrics(), means, tone_word="stressed")
        self.assertIsNotNone(out)
        self.assertIsNone(re.search(r"\d", out))
        low = out.lower()
        for banned in ("charisma score", "stress score", "threat",
                       "classifier", "ratio"):
            self.assertNotIn(banned, low)


if __name__ == "__main__":
    unittest.main()
