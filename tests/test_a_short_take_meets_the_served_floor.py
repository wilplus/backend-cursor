"""
STORY    As a speaker, I want the recording screen to use the server's
         minimum-speech threshold, so that a short but valid Take is not
         rejected.
OUTCOME
  O1  /config/recording serves no minimum duration and 3 s of voiced
      speech: the same thresholds the upload gate enforces.
  O2  The upload gate passes a short, fully voiced Take and refuses the same
      length of silence.
PROVES   O1 -> test_serves_the_gate_s_own_thresholds
         O2 -> test_a_short_voiced_take_passes_and_silence_does_not
WHY      Founder 2026-07-15: the duration minimum was retired; the FE used to
         hardcode 60 s. (Formerly tests/test_wave2_be.py.)
"""
from __future__ import annotations

import unittest

try:
    import numpy as np
    from flask import Flask

    from routes.v2 import lab_recording as v2_lab_recording
    from services.audio_metrics import SAMPLE_RATE
    from services.min_content_gate import evaluate_min_content
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RecordingFloorTests(unittest.TestCase):

    def test_serves_the_gate_s_own_thresholds(self):
        with Flask(__name__).test_request_context():
            resp, status = v2_lab_recording.v2_config_recording.__wrapped__()
        data = resp.get_json()
        self.assertEqual(status, 200)
        self.assertEqual(data["min_duration_sec"], 0.0)
        self.assertEqual(data["min_voiced_sec"], 3.0)
        served = {k: data[k] for k in ("min_duration_sec", "min_voiced_sec")}
        self.assertEqual(served, evaluate_min_content(np.zeros(10))["thresholds"])

    def test_a_short_voiced_take_passes_and_silence_does_not(self):
        t = np.arange(2 * SAMPLE_RATE) / SAMPLE_RATE
        voiced = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
        self.assertTrue(evaluate_min_content(voiced)["ok"])
        silence = evaluate_min_content(np.zeros_like(voiced))
        self.assertEqual((silence["ok"], silence["reason"]), (False, "no_speech"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
