"""
STORY    As a speaker uploading a deck, I want a clear "too big" or "wrong
         type" answer before anything is stored, so that I know to export a
         lighter PDF.
OUTCOME
  O1  A file that is not a PDF is refused as an unsupported type.
  O2  An empty PDF is refused as invalid input.
  O3  A PDF over the size cap is refused as too large, with the limit in MB
      as a number and named in the message, so the screen can say it.
PROVES   O1 -> PresentationExtractValidationTests::test_non_pdf_415
         O2 -> PresentationExtractValidationTests::test_empty_pdf_400
         O3 -> PresentationExtractValidationTests::test_oversize_pdf_413_contract
"""
from __future__ import annotations

import io
import unittest

try:
    from flask import Flask, request

    from routes.v2 import common as v2_common
    from routes.v2 import lab_recording as v2_lab_recording
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PresentationExtractValidationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, data):
        # @optional_auth → guest allowed; no request.user_id needed.
        with self.app.test_request_context(
            method="POST", data=data, content_type="multipart/form-data"
        ):
            resp, status = v2_lab_recording.v2_lab_presentation_extract.__wrapped__()
            return status, resp.get_json()


    def test_non_pdf_415(self):
        status, body = self._post(
            {"file": (io.BytesIO(b"not a pdf"), "slides.pptx")}
        )
        self.assertEqual(status, 415)
        self.assertEqual(body["code"], "UNSUPPORTED_TYPE")

    def test_empty_pdf_400(self):
        status, body = self._post({"file": (io.BytesIO(b""), "deck.pdf")})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INVALID_INPUT")

    def test_oversize_pdf_413_contract(self):
        # One byte over the cap → the FE-popup contract.
        big = b"\x00" * (v2_common._PRESENTATION_MAX_MB * 1024 * 1024 + 1)
        status, body = self._post({"file": (io.BytesIO(big), "deck.pdf")})
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "FILE_TOO_LARGE")
        # limit_mb is the single source of truth the FE renders.
        self.assertEqual(body["limit_mb"], v2_common._PRESENTATION_MAX_MB)
        # message names the limit (no silent compression — a lighter export).
        self.assertIn(str(v2_common._PRESENTATION_MAX_MB), body["error"])


if __name__ == "__main__":
    unittest.main()
