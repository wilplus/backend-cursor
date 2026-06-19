"""POST /v2/lab/presentation/extract — the deck-upload validation contract.

Focus: the early validation branches the FE's "too big" popup + type guard
read. These run before any parse/storage, so no DB/R2 mocks are needed.

The FILE_TOO_LARGE response is a CONTRACT the FE popup keys on: a stable
`code`, a human message, and `limit_mb` as a number (single source of truth
so the FE doesn't re-hardcode the cap).

Run: python3 -m unittest test_presentation_extract
"""
from __future__ import annotations

import io
import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
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
            resp, status = v2.v2_lab_presentation_extract.__wrapped__()
            return status, resp.get_json()

    def test_missing_file_400(self):
        status, body = self._post({})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INVALID_INPUT")

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
        big = b"\x00" * (v2._PRESENTATION_MAX_MB * 1024 * 1024 + 1)
        status, body = self._post({"file": (io.BytesIO(big), "deck.pdf")})
        self.assertEqual(status, 413)
        self.assertEqual(body["code"], "FILE_TOO_LARGE")
        # limit_mb is the single source of truth the FE renders.
        self.assertEqual(body["limit_mb"], v2._PRESENTATION_MAX_MB)
        # message names the limit (no silent compression — a lighter export).
        self.assertIn(str(v2._PRESENTATION_MAX_MB), body["error"])


if __name__ == "__main__":
    unittest.main()
