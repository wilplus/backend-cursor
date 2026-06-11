"""UX Wave 4 Phase 2 — snippet→slide alignment (BE-S4). Pure, runs everywhere.

Run: python3 -m unittest test_wave4_phase2
"""
from __future__ import annotations

import unittest

from services.slide_alignment import (
    slide_index_for_offset, slide_for_snippet,
    on_slide_score, abstain_reason, roll_up_coverage, _lexical_verdict,
)

UID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

SLIDES = [
    {"title": "Intro", "body": "welcome"},
    {"title": "Problem", "body": "the pain point"},
    {"title": "Solution", "body": "our fix"},
]
ADV = [  # tap timeline: slide 0 from 0, →1 at 5s, →2 at 10s, BACK to 1 at 15s
    {"index": 0, "t_ms": 0},
    {"index": 1, "t_ms": 5000},
    {"index": 2, "t_ms": 10000},
    {"index": 1, "t_ms": 15000},
]


class OffsetMappingTests(unittest.TestCase):
    def test_greatest_t_le_offset(self):
        self.assertEqual(slide_index_for_offset(0, ADV), 0)
        self.assertEqual(slide_index_for_offset(4999, ADV), 0)
        self.assertEqual(slide_index_for_offset(5000, ADV), 1)
        self.assertEqual(slide_index_for_offset(12000, ADV), 2)

    def test_back_navigation_is_real(self):
        # after the back-tap at 15s, a later snippet maps to the EARLIER index 1
        self.assertEqual(slide_index_for_offset(16000, ADV), 1)

    def test_before_first_or_empty(self):
        self.assertIsNone(slide_index_for_offset(0, []))
        self.assertIsNone(slide_index_for_offset(0, None))


class SlideForSnippetTests(unittest.TestCase):
    def test_timeline_exact(self):
        sl = slide_for_snippet(
            {"start_offset_ms": 11000, "transcript": "anything"}, ADV, SLIDES)
        self.assertEqual(sl, {"index": 2, "title": "Solution", "body": "our fix"})

    def test_fallback_text_overlap_when_no_timeline(self):
        # no advances → best text overlap; "pain point" → slide 1 (Problem)
        sl = slide_for_snippet(
            {"start_offset_ms": 0, "transcript": "let me describe the pain point here"},
            None, SLIDES)
        self.assertEqual(sl["index"], 1)

    def test_no_slides_returns_none(self):
        self.assertIsNone(slide_for_snippet({"start_offset_ms": 0}, ADV, None))

    def test_out_of_range_index_guarded(self):
        # an advance pointing past the slide list → no slide, not a crash
        bad = [{"index": 9, "t_ms": 0}]
        self.assertIsNone(
            slide_for_snippet({"start_offset_ms": 1000, "transcript": ""}, bad, SLIDES))


class ClaimLedgerScoringTests(unittest.TestCase):
    """Pure scoring / rollup / abstain / lexical-fallback for Stickiness #2."""

    def test_on_slide_score_is_max_strength(self):
        # (ii): strongest single verdict, NOT averaged over all slide claims.
        self.assertEqual(on_slide_score(["not", "covered", "partial"]), 1.0)
        self.assertEqual(on_slide_score(["not", "partial"]), 0.5)
        self.assertEqual(on_slide_score(["not", "not"]), 0.0)
        self.assertEqual(on_slide_score([]), 0.0)

    def test_lexical_verdict_bands(self):
        self.assertEqual(
            _lexical_verdict("we cut onboarding from nine days to two",
                             "onboarding cut to two days"), "covered")
        self.assertEqual(
            _lexical_verdict("the team really clicked this quarter",
                             "revenue grew forty percent"), "not")

    def test_abstain_reasons(self):
        slide = {"title": "Revenue", "body": "grew 40%"}
        claims = ["revenue grew"]
        self.assertEqual(abstain_reason("plenty of words here ok", 8000, {}, claims), "null")
        self.assertEqual(abstain_reason("plenty of words here ok", 8000, slide, []), "null")
        self.assertEqual(abstain_reason("um yeah", 8000, slide, claims), "null")  # word floor
        self.assertEqual(abstain_reason("", 8000, slide, claims), "zero")         # silence
        self.assertEqual(abstain_reason("", 500, slide, claims), "null")          # too short
        self.assertIsNone(abstain_reason("revenue grew strongly this year", 8000, slide, claims))

    def test_roll_up_coverage(self):
        claims = ["revenue grew", "driven by enterprise", "margins improved"]
        per = [("s1", ["covered", "not", "partial"]),
               ("s2", ["not", "partial", "not"])]
        cov = roll_up_coverage(2, claims, per)
        self.assertEqual(cov["slide_index"], 2)
        self.assertEqual(cov["covered"], 1)   # claim0 covered by s1
        self.assertEqual(cov["partial"], 2)   # claim1 (s2), claim2 (s1)
        self.assertEqual(cov["total"], 3)
        self.assertEqual(cov["ledger"][0]["verdict"], "covered")
        self.assertEqual(cov["ledger"][0]["snippet_ref"], "s1")


# ── route shape (skip without flask; run in CI) ──
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
class SlideAlignmentRouteTests(unittest.TestCase):
    """/slide-alignment reads the PERSISTED coverage ledger (no live LLM)."""

    def setUp(self):
        self.app = Flask(__name__)
        self._o = getattr(v2.db, "v2_get_session_by_id", None)
        v2.db.v2_get_session_by_id = lambda sid: {"id": sid}

    def tearDown(self):
        if self._o is not None:
            v2.db.v2_get_session_by_id = self._o

    def _call(self, readout):
        import services.lab_recording as lab
        orig = lab.build_readout_from_session
        lab.build_readout_from_session = lambda sid, **k: readout
        try:
            with self.app.test_request_context():
                request.user_id = "coach-1"
                resp, status = v2.v2_coach_slide_alignment.__wrapped__(UID)
                return status, resp.get_json()
        finally:
            lab.build_readout_from_session = orig

    def test_returns_coverage(self):
        status, data = self._call({"slide_coverage": [
            {"slide_index": 0, "covered": 2, "partial": 1, "total": 3, "ledger": []}]})
        self.assertEqual(status, 200)
        self.assertEqual(data["slide_coverage"][0]["covered"], 2)

    def test_available_false_when_empty(self):
        status, data = self._call({"slide_coverage": []})
        self.assertEqual(status, 200)
        self.assertFalse(data["available"])


if __name__ == "__main__":
    unittest.main()
