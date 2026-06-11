"""UX Wave 4 — slide-deck capture (BE Phase 1).

Most of this runs locally: intake_context + deck_parser + the whisper-prime
merge are dependency-light (heavy parsers lazy-imported). The extract route
test mirrors the coach harness (skip without flask, run in CI).

Run: python3 -m unittest test_wave4_slides
"""
from __future__ import annotations

import unittest

from services.intake_context import (
    validate_intake_context_body, IntakeContextError,
    _norm_slides, _norm_slide_advances, _norm_presentation_ref,
)
from services.lab_recording import _merge_slide_vocab


class SlidesValidationTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(
            _norm_slides([{"title": "Intro", "body": "hi\nthere"}]),
            [{"title": "Intro", "body": "hi\nthere"}],
        )

    def test_drops_blank_rows(self):
        out = _norm_slides([{"title": "", "body": ""}, {"title": "A", "body": ""}])
        self.assertEqual(out, [{"title": "A", "body": ""}])

    def test_all_blank_collapses_none(self):
        self.assertIsNone(_norm_slides([{"title": "", "body": "  "}]))
        self.assertIsNone(_norm_slides([]))
        self.assertIsNone(_norm_slides(None))

    def test_body_must_be_string_not_array(self):
        # the §S silent-failure guard: FE must serialize bullets→string
        with self.assertRaises(IntakeContextError):
            _norm_slides([{"title": "A", "body": ["bullet 1", "bullet 2"]}])

    def test_caps(self):
        with self.assertRaises(IntakeContextError):
            _norm_slides([{"title": "x", "body": "y"}] * 61)
        with self.assertRaises(IntakeContextError):
            _norm_slides([{"title": "x" * 201, "body": "y"}])
        with self.assertRaises(IntakeContextError):
            _norm_slides([{"title": "x", "body": "y" * 2001}])

    def test_presentation_ref(self):
        self.assertEqual(
            _norm_presentation_ref("  https://x/y.pdf "), "https://x/y.pdf",
        )
        self.assertIsNone(_norm_presentation_ref(""))
        self.assertIsNone(_norm_presentation_ref(None))

    def test_slide_advances(self):
        self.assertEqual(
            _norm_slide_advances([{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}]),
            [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}],
        )

    def test_slide_advances_rejects_bad(self):
        with self.assertRaises(IntakeContextError):
            _norm_slide_advances([{"index": 0, "t_ms": True}])  # bool-is-int trap
        with self.assertRaises(IntakeContextError):
            _norm_slide_advances([{"index": -1, "t_ms": 0}])
        with self.assertRaises(IntakeContextError):
            _norm_slide_advances([{"index": "0", "t_ms": 0}])

    def test_validate_body_carries_slide_fields(self):
        cleaned = validate_intake_context_body({
            "topic": "Demo",
            "slides": [{"title": "A", "body": "b"}],
            "presentation_ref": "https://x/y.pdf",
            "slide_advances": [{"index": 0, "t_ms": 0}],
        }, require_topic=True)
        self.assertEqual(cleaned["slides"], [{"title": "A", "body": "b"}])
        self.assertEqual(cleaned["presentation_ref"], "https://x/y.pdf")
        self.assertEqual(cleaned["slide_advances"], [{"index": 0, "t_ms": 0}])

    def test_backcompat_no_slide_fields(self):
        cleaned = validate_intake_context_body({"topic": "Demo"}, require_topic=True)
        self.assertIsNone(cleaned["slides"])
        self.assertIsNone(cleaned["presentation_ref"])
        self.assertIsNone(cleaned["slide_advances"])


class WhisperVocabMergeTests(unittest.TestCase):
    def test_merges_titles_dedup_case_insensitive(self):
        out = _merge_slide_vocab({
            "domain_vocabulary": ["Foo"],
            "slides": [{"title": "Bar", "body": "x"}, {"title": "foo", "body": "y"}],
        })
        self.assertEqual(out, ["Foo", "Bar"])  # 'foo' deduped against 'Foo'

    def test_none_when_empty(self):
        self.assertIsNone(_merge_slide_vocab({}))
        self.assertIsNone(_merge_slide_vocab(None))


class DeckParserGuardTests(unittest.TestCase):
    def test_unsupported_type_raises(self):
        from services.deck_parser import extract_deck, DeckParseError
        with self.assertRaises(DeckParseError):
            extract_deck(b"hello", "notes.txt")

    def test_pptx_rejected_with_export_hint(self):
        # PDF-only pivot: PPTX is rejected with an export-to-PDF message.
        from services.deck_parser import extract_deck, DeckParseError, SUPPORTED_EXTS
        self.assertEqual(SUPPORTED_EXTS, (".pdf",))
        with self.assertRaises(DeckParseError) as ctx:
            extract_deck(b"PK\x03\x04fake", "deck.pptx")
        self.assertIn("PDF", str(ctx.exception))

    def test_ext_and_clip(self):
        from services.deck_parser import _ext, _clip
        self.assertEqual(_ext("a/b/Deck.PDF"), ".pdf")
        self.assertEqual(_clip("  hi  ", 10), "hi")
        self.assertEqual(_clip("abcdef", 3), "abc")


# ── extract route shape (skip without flask; run in CI) ──
try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _RT_ERR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _RT_ERR = e


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class ExtractRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_missing_file_400(self):
        with self.app.test_request_context(method="POST"):
            request.user_id = None
            resp, status = v2.v2_lab_presentation_extract.__wrapped__()
            self.assertEqual(status, 400)
            self.assertEqual(resp.get_json()["code"], "INVALID_INPUT")


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class LastSetupRouteTests(unittest.TestCase):
    """'Do the same as last time' — /v2/user/last-setup prefill."""

    def setUp(self):
        self.app = Flask(__name__)
        self._o = getattr(v2.db, "v2_list_user_lab_sessions", None)

    def tearDown(self):
        if self._o is not None:
            v2.db.v2_list_user_lab_sessions = self._o

    def _get(self, sessions):
        v2.db.v2_list_user_lab_sessions = lambda uid, **k: sessions
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_user_last_setup.__wrapped__()
            return status, resp.get_json()

    def test_returns_prefill_without_tap_timeline(self):
        status, data = self._get([{"intake_context": {
            "topic": "Q3 pitch", "audience": "leadership",
            "target_length_seconds": 120, "domain_vocabulary": ["ARR"],
            "slides": [{"title": "Intro", "body": "hi"}],
            "presentation_ref": "https://x/y.pdf",
            "slide_advances": [{"index": 0, "t_ms": 0}],  # must NOT prefill
        }}])
        self.assertEqual(status, 200)
        self.assertTrue(data["available"])
        self.assertEqual(data["topic"], "Q3 pitch")
        self.assertEqual(data["target_length_seconds"], 120)
        self.assertEqual(data["slides"][0]["title"], "Intro")
        self.assertEqual(data["presentation_ref"], "https://x/y.pdf")
        self.assertNotIn("slide_advances", data)  # tap timeline is per-recording

    def test_available_false_when_no_history(self):
        status, data = self._get([])
        self.assertEqual(status, 200)
        self.assertFalse(data["available"])


if __name__ == "__main__":
    unittest.main()
