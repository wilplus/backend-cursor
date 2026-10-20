"""
STORY    As a speaker, I want my uploaded deck's slides captured into my
         take, so that the transcript splits into one paragraph per slide.
OUTCOME
  O1  The deck extract route answers 400 INVALID_INPUT when no file is
      sent, instead of failing the upload with a server error.
PROVES   O1 -> test_missing_file_400
WHY      UX Wave 4 slide-deck capture. The other extract outcomes (415, empty
         400, 413) live in tests/test_presentation_extract.py; this case
         belongs there too (not folded: outside this batch's files).
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
