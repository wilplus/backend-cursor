"""Force-alignment on reads (F1-CORE handoff §3, 2026-08-03).

A read has ground truth — the exact ideal-text version read. The aligner
matches the read's transcribed words against that script: matched words
take the SCRIPT surface (fidelity), off-script words stay verbatim (L1),
and every skip / substitution / insertion is a structured deviation.

Run: python3 -m unittest test_read_alignment
"""
from __future__ import annotations

import unittest

from services.read_alignment import (
    align_words_to_script,
    process_read_alignment,
)


def _w(word, start=None, end=None):
    return {"word": word, "start_ms": start, "end_ms": end}


class AlignerTests(unittest.TestCase):

    SCRIPT = "We started small. Then we grew fast."

    def test_perfect_read_aligns_word_for_word(self):
        hyp = [_w("we", 0, 200), _w("started", 200, 600),
               _w("small", 600, 900), _w("then", 1000, 1200),
               _w("we", 1200, 1300), _w("grew", 1300, 1600),
               _w("fast", 1600, 1900)]
        out = align_words_to_script(self.SCRIPT, hyp)
        self.assertEqual(out["deviations"], [])
        # Matched words take the SCRIPT's surface (casing preserved).
        self.assertEqual(out["aligned_transcript"],
                         "We started small Then we grew fast")
        self.assertEqual([w["script_index"] for w in out["words"]],
                         list(range(7)))
        self.assertEqual(out["words"][2]["start_ms"], 600)
        self.assertEqual(out["words"][2]["end_ms"], 900)

    def test_substitution_is_a_structured_delta(self):
        hyp = [_w("we", 0, 200), _w("started", 200, 600),
               _w("tiny", 600, 900), _w("then", 1000, 1200),
               _w("we", 1200, 1300), _w("grew", 1300, 1600),
               _w("fast", 1600, 1900)]
        out = align_words_to_script(self.SCRIPT, hyp)
        subs = [d for d in out["deviations"]
                if d["kind"] == "substitution"]
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["script_text"], "small")
        self.assertEqual(subs[0]["said_text"], "tiny")
        self.assertEqual(subs[0]["start_ms"], 600)
        # The spoken word stays VERBATIM in the transcript (L1 — never
        # silently corrected to the script).
        self.assertIn("tiny", out["aligned_transcript"])
        self.assertNotIn("small", out["aligned_transcript"])

    def test_skip_anchors_to_the_moment_passed_over(self):
        hyp = [_w("we", 0, 200), _w("started", 200, 600),
               _w("small", 600, 900),
               _w("fast", 1600, 1900)]   # "Then we grew" never spoken
        out = align_words_to_script(self.SCRIPT, hyp)
        skips = [d for d in out["deviations"] if d["kind"] == "skip"]
        self.assertEqual(len(skips), 1)
        self.assertEqual(skips[0]["script_text"], "Then we grew")
        self.assertEqual(skips[0]["said_text"], "")
        self.assertEqual(skips[0]["start_ms"], 1600)

    def test_insertion_is_kept_and_flagged(self):
        hyp = [_w("we", 0, 200), _w("started", 200, 600),
               _w("really", 600, 800), _w("really", 800, 950),
               _w("small", 950, 1200), _w("then", 1300, 1500),
               _w("we", 1500, 1600), _w("grew", 1600, 1900),
               _w("fast", 1900, 2100)]
        out = align_words_to_script(self.SCRIPT, hyp)
        ins = [d for d in out["deviations"] if d["kind"] == "insertion"]
        self.assertEqual(len(ins), 1)
        self.assertEqual(ins[0]["said_text"], "really really")
        self.assertIn("really really small", out["aligned_transcript"])

    def test_marker_syntax_never_pollutes_the_script_tokens(self):
        script = ("{{orange:We started}} **small**. "
                  "[[moment:aaaaaaaa-1111|bbbbbbbb-2222]]Then.[[/moment]]")
        hyp = [_w("we"), _w("started"), _w("small"), _w("then")]
        out = align_words_to_script(script, hyp)
        self.assertEqual(out["deviations"], [])
        joined = out["aligned_transcript"].lower()
        self.assertNotIn("orange", joined)
        self.assertNotIn("moment", joined)

    def test_empty_sides_return_none(self):
        self.assertIsNone(align_words_to_script("", [_w("hi")]))
        self.assertIsNone(align_words_to_script("Some script.", []))


class _AlignDB:
    """Fake db: one ideal-text read paired to version 2, with per-word
    Whisper timings (seconds, absolute) on its snippet rows."""

    def __init__(self, *, words=True, target="ideal_text"):
        self._words = words
        self._target = target
        self.saved = None

    def v2_get_session_by_id(self, sid):
        return {"id": sid, "arc_id": "a1", "recording_kind": "read",
                "intake_context": {"read_target": self._target,
                                   "ideal_version": 2}}

    def get_ideal_text_version(self, arc_id, version):
        if version == 2:
            return {"arc_id": arc_id, "version": 2,
                    "text": "We started small."}
        return None

    def get_coach_arc_ideal_text(self, arc_id):
        return {"arc_id": arc_id, "version": 3, "auto_text": "newer text"}

    def get_snippets_by_session(self, sid):
        row = {"id": "sn1", "start_offset_ms": 0,
               "transcript": "we started small"}
        if self._words:
            row["words"] = [{"word": "we", "start": 0.0, "end": 0.2},
                            {"word": "started", "start": 0.2, "end": 0.6},
                            {"word": "small", "start": 0.6, "end": 0.9}]
        return [row]

    def upsert_read_alignment(self, sid, fields):
        self.saved = (sid, fields)
        return True


class OrchestratorTests(unittest.TestCase):

    def test_read_aligns_against_its_version_snapshot(self):
        db = _AlignDB()
        self.assertTrue(process_read_alignment("r1", db))
        sid, fields = db.saved
        self.assertEqual(sid, "r1")
        self.assertEqual(fields["ideal_version"], 2)
        self.assertEqual(fields["aligned_transcript"], "We started small")
        # Whisper seconds → ms.
        self.assertEqual(fields["words"][1]["start_ms"], 200)
        self.assertEqual(fields["words"][1]["end_ms"], 600)
        self.assertEqual(fields["deviations"], [])

    def test_wordless_rows_degrade_to_transcript_tokens(self):
        db = _AlignDB(words=False)
        self.assertTrue(process_read_alignment("r1", db))
        _, fields = db.saved
        self.assertEqual(fields["aligned_transcript"], "We started small")
        self.assertIsNone(fields["words"][0]["start_ms"])

    def test_non_ideal_text_read_is_skipped(self):
        db = _AlignDB(target=None)
        self.assertFalse(process_read_alignment("r1", db))
        self.assertIsNone(db.saved)

    def test_missing_script_never_aligns_against_the_wrong_text(self):
        # Version 5 has no snapshot and the live row is version 3 — the
        # aligner must give up rather than align against different text.
        db = _AlignDB()
        db.v2_get_session_by_id = lambda sid: {
            "id": sid, "arc_id": "a1", "recording_kind": "read",
            "intake_context": {"read_target": "ideal_text",
                               "ideal_version": 5}}
        self.assertFalse(process_read_alignment("r1", db))
        self.assertIsNone(db.saved)


if __name__ == "__main__":
    unittest.main()
