"""willab — context-document ingestion (X-1, founder 2026-07-24).

Pins the parser: text vs PDF detection, per-page PDF extraction with the page
cap, the char cap + truncated flag, and junk-safety (never raises).

Run: python3 -m unittest test_context_document
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import patch

import io

from services.context_document import (
    MAX_CHARS,
    MAX_PAGES,
    _looks_like_pdf,
    extract_context_text,
)

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _V2_ERR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _V2_ERR = e

ARC = "arc-1"
UID = "u1"


class _FakePage:
    def __init__(self, text):
        self._t = text

    def extract_text(self):
        if isinstance(self._t, Exception):
            raise self._t
        return self._t


class _FakeReader:
    def __init__(self, texts):
        self.pages = [_FakePage(t) for t in texts]


def _fake_pypdf(reader_factory):
    # pypdf is a prod-only dep; inject a stand-in so `from pypdf import
    # PdfReader` resolves in the local venv too.
    mod = types.ModuleType("pypdf")
    mod.PdfReader = reader_factory
    return patch.dict(sys.modules, {"pypdf": mod})


def _reader(texts):
    return _fake_pypdf(lambda _bio: _FakeReader(texts))


class DetectionTests(unittest.TestCase):
    def test_magic_bytes(self):
        self.assertTrue(_looks_like_pdf(b"%PDF-1.7 ...", None, None))
        self.assertFalse(_looks_like_pdf(b"hello", None, None))

    def test_content_type_and_extension(self):
        self.assertTrue(_looks_like_pdf(b"x", "application/pdf", None))
        self.assertTrue(_looks_like_pdf(b"x", None, "report.PDF"))
        self.assertFalse(_looks_like_pdf(b"x", "text/plain", "notes.txt"))


class TextPathTests(unittest.TestCase):
    def test_plain_text_extracted(self):
        out = extract_context_text(b"  Hello world.\n\nMore context.  ",
                                   content_type="text/plain")
        self.assertEqual(out["text"], "Hello world.\n\nMore context.")
        self.assertEqual(out["pages"], 1)
        self.assertEqual(out["chars"], len(out["text"]))
        self.assertFalse(out["truncated"])

    def test_char_cap(self):
        out = extract_context_text(b"x" * (MAX_CHARS + 500))
        self.assertEqual(out["chars"], MAX_CHARS)
        self.assertTrue(out["truncated"])

    def test_junk_is_safe(self):
        for bad in (None, b"", "not bytes", 123):
            self.assertEqual(extract_context_text(bad)["text"], "")


class PdfPathTests(unittest.TestCase):
    def test_joins_pages(self):
        with _reader(["Page one.", "", "Page three."]):
            out = extract_context_text(b"%PDF-fake", content_type="application/pdf")
        self.assertEqual(out["text"], "Page one.\n\nPage three.")   # empty skipped
        self.assertEqual(out["pages"], 3)
        self.assertFalse(out["truncated"])

    def test_page_cap_marks_truncated(self):
        with _reader([f"p{i}" for i in range(MAX_PAGES + 5)]):
            out = extract_context_text(b"%PDF-x", filename="deck.pdf")
        self.assertEqual(out["pages"], MAX_PAGES + 5)              # true count
        self.assertTrue(out["truncated"])
        # only the first MAX_PAGES pages contributed text
        self.assertIn("p0", out["text"])
        self.assertNotIn(f"p{MAX_PAGES}", out["text"])

    def test_bad_page_does_not_break_the_loop(self):
        with _reader(["good", ValueError("boom"), "also good"]):
            out = extract_context_text(b"%PDF-x", content_type="application/pdf")
        self.assertEqual(out["text"], "good\n\nalso good")

    def test_unparseable_pdf_returns_empty(self):
        def _raise(_bio):
            raise RuntimeError("corrupt")
        with _fake_pypdf(_raise):
            out = extract_context_text(b"%PDF-broken",
                                       content_type="application/pdf")
        self.assertEqual(out["text"], "")
        self.assertEqual(out["pages"], 0)


@unittest.skipIf(_V2_ERR is not None, f"needs app deps: {_V2_ERR}")
class UploadRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, data_bytes=b"  Hello context here.  ", *, owned=True,
              filename="notes.txt"):
        files = ({"file": (io.BytesIO(data_bytes), filename)}
                 if data_bytes is not None else {})
        with self.app.test_request_context(
                method="POST", data=files,
                content_type="multipart/form-data"):
            request.user_id = UID
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(owned, [])), \
                 patch.object(v2.db, "upsert_arc_context_document",
                              return_value=True) as m_up:
                out = v2.v2_explore_upload_context_document.__wrapped__(ARC)
        resp, status = out if isinstance(out, tuple) else (out, 200)
        return resp.get_json(), status, m_up

    def test_success_stores_extracted_text(self):
        body, status, m_up = self._post()
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["pages"], 1)
        m_up.assert_called_once()
        self.assertEqual(m_up.call_args.args[1], "Hello context here.")

    def test_not_owned_404(self):
        _b, status, _ = self._post(owned=False)
        self.assertEqual(status, 404)

    def test_missing_file_400(self):
        _b, status, _ = self._post(data_bytes=None)
        self.assertEqual(status, 400)


@unittest.skipIf(_V2_ERR is not None, f"needs app deps: {_V2_ERR}")
class GetRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, row):
        with self.app.test_request_context():
            request.user_id = UID
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch.object(v2.db, "get_arc_context_document",
                              return_value=row):
                out = v2.v2_explore_get_context_document.__wrapped__(ARC)
        resp, status = out if isinstance(out, tuple) else (out, 200)
        return resp.get_json(), status

    def test_no_document(self):
        body, _ = self._get(None)
        self.assertFalse(body["has_document"])

    def test_has_document_hides_the_text(self):
        body, _ = self._get({"text": "secret background", "pages": 5,
                             "chars": 100, "filename": "r.pdf",
                             "truncated": False})
        self.assertTrue(body["has_document"])
        self.assertEqual(body["pages"], 5)
        self.assertNotIn("text", body)       # background never leaked to user


if __name__ == "__main__":
    unittest.main()
