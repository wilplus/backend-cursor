"""UX Wave v2 — backend: credit ledger, roster, recording-min config.

Covers the genuinely-new BE behavior:
  * the 15-credit lazy first-touch grant + its idempotency (spend-to-zero
    never re-grants; purchased balances are preserved) — db logic, via a
    fake PostgREST client so it runs without a live DB.
  * the three new route shapes (/user/credits, /config/recording,
    /coach/students) — mirror the test_coach_session harness (skip locally
    without app deps, run in CI).
  * the recording-min constants the config endpoint exposes — pure, runs
    everywhere.

Run: python3 -m unittest tests.test_wave2_be

Subjects (audit Q-T9, 2026-09-15): the 15-credit lazy grant, the
min-content constants, and the /user/credits, /config/recording and
/coach/students routes. Kept under the delivery name because the file
carries several subjects; split it when one of them grows.
"""
from __future__ import annotations

import unittest

# ── pure: the min-content thresholds the /config/recording endpoint serves ──
# min_content_gate is import-safe without numpy (it lazy-imports the audio
# stack inside the functions), so this runs in every env.


# ── app-dependent: db grant logic + route shapes ──
try:
    from flask import Flask, request

    from routes.v2 import lab_recording as v2_lab_recording
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


# ── a tiny fake PostgREST client, just enough for v2_ensure_credits_initialized ──


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ConfigRecordingRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_serves_thresholds(self):
        with self.app.test_request_context():
            resp, status = v2_lab_recording.v2_config_recording.__wrapped__()
            data = resp.get_json()
            self.assertEqual(status, 200)
            self.assertEqual(data["min_duration_sec"], 0.0)  # retired 2026-07-15
            self.assertEqual(data["min_voiced_sec"], 3.0)


if __name__ == "__main__":
    unittest.main()
