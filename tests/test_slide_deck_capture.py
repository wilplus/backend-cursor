"""UX Wave 4 — slide-deck capture (BE Phase 1).

Most of this runs locally: intake_context + deck_parser + the whisper-prime
merge are dependency-light (heavy parsers lazy-imported). The extract route
test mirrors the coach harness (skip without flask, run in CI).

Run: python3 -m unittest tests.test_wave4_slides
"""
from __future__ import annotations

import unittest

# ── extract route shape (skip without flask; run in CI) ──
try:
    from flask import Flask, request

    from routes.v2 import lab_recording as v2_lab_recording
    _RT_ERR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _RT_ERR = e


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class ExtractRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_missing_file_400(self):
        with self.app.test_request_context(method="POST"):
            request.user_id = None
            resp, status = v2_lab_recording.v2_lab_presentation_extract.__wrapped__()
            self.assertEqual(status, 400)
            self.assertEqual(resp.get_json()["code"], "INVALID_INPUT")


if __name__ == "__main__":
    unittest.main()
