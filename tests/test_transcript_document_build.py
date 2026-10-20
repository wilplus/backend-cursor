"""
STORY    As a speaker, I want my transcript built into one paragraph per slide,
         so that my Ideal Text starts from what I said.
         (Critical path: process -> Ideal Text; Never-5: only my latest Take.)
OUTCOME
  O1  The document is built from my LATEST spoken Take only; an earlier Take
      or a read-aloud never supplies its words.
  O2  One paragraph per slide, in spoken order, and the coach's slide fix
      moves a piece to the slide the coach chose.
  O3  A document over the length cap is cut, keeping only whole pieces whose
      offsets still point at their own words.
  O4  No words, no document.
PROVES   O1 -> test_the_document_reads_only_the_latest_spoken_take
         O2 -> test_one_paragraph_per_slide_and_the_coachs_slide_fix_applies
         O3 -> test_a_document_over_the_cap_keeps_only_whole_pieces
         O4 -> test_no_words_builds_nothing
"""
from __future__ import annotations

import unittest

from services.transcript_document import build_transcript_document as build

ARC_SESSIONS = [
    {"id": "t1", "take_index": 1, "recording_kind": "spoken"},
    {"id": "t2", "take_index": 2, "recording_kind": "spoken"},
    {"id": "r2", "take_index": 3, "recording_kind": "read"},
]


class Db:
    """The reads build_transcript_document makes, keyed by session."""

    def __init__(self, snips_by_session, *, sessions=ARC_SESSIONS, fixes=None):
        self._snips, self._sessions, self._fixes = snips_by_session, sessions, fixes

    @property
    def takes(self):
        return self

    def get_arc_sessions(self, arc_id):
        return self._sessions

    def get_snippets_by_session(self, sid):
        return self._snips.get(sid, [])

    def get_coach_snippet_drafts(self, sid):
        return []

    def get_user_transcript_edits(self, sid):
        return []

    def get_snippet_slide_corrections(self, sid):
        return self._fixes or {}


def snip(sid, ms, text, slide=None):
    row = {"id": sid, "start_offset_ms": ms, "language": "en",
           "transcript": text, "recording_id": "rec-" + sid,
           "audio_ref": "a/" + sid, "duration_ms": 900}
    if slide is not None:
        row["metrics"] = {"piece": {"slide_index": slide}}
    return row


LATEST = [
    snip("s3", 9000, "and this one closes slide two", slide=1),
    snip("s1", 0, "we started small", slide=0),
    snip("s2", 4000, "then we shipped it fast", slide=0),
]


class TranscriptDocumentTests(unittest.TestCase):

    def test_the_document_reads_only_the_latest_spoken_take(self):
        doc = build("arc", database=Db({
            "t1": [snip("old", 0, "an older take about pricing", slide=0)],
            "t2": LATEST,
            "r2": [snip("read", 0, "the read aloud version", slide=0)],
        }))
        self.assertEqual((doc["take_session_id"], doc["take_index"]), ("t2", 2))
        self.assertIn("shipped it fast", doc["text"])
        for word in ("pricing", "read aloud"):
            self.assertNotIn(word, doc["text"])

    def test_one_paragraph_per_slide_and_the_coachs_slide_fix_applies(self):
        doc = build("arc", database=Db({"t2": LATEST}))
        self.assertEqual([p["slide_index"] for p in doc["paragraphs"]], [0, 1])
        first, second = doc["text"].split("\n\n")
        self.assertIn("started small", first)
        self.assertIn("shipped it fast", first)
        self.assertIn("closes slide two", second)

        fixed = build("arc", database=Db({"t2": LATEST}, fixes={"s2": 1}))
        first, second = fixed["text"].split("\n\n")
        self.assertNotIn("shipped", first)
        self.assertIn("shipped it fast", second)
        moved = next(p for p in fixed["pieces"] if p["snippet_id"] == "s2")
        self.assertEqual(moved["slide_index"], 1)

    def test_a_document_over_the_cap_keeps_only_whole_pieces(self):
        long = [snip(f"L{i}", i * 1000, " ".join(f"w{i}x{j}" for j in range(60)))
                for i in range(160)]
        full_length = sum(len(s["transcript"]) + 1 for s in long)
        doc = build("arc", database=Db({"t2": long}))
        self.assertLess(len(doc["text"]), full_length)
        kept = [p["snippet_id"] for p in doc["pieces"]]
        self.assertEqual(kept, [f"L{i}" for i in range(len(kept))])
        self.assertGreater(len(kept), 1)
        for p in doc["pieces"]:
            self.assertEqual(doc["text"][p["start"]:p["end"]], p["text"])
            # Whole: the piece's own last word is inside it.
            self.assertIn(f"w{p['snippet_id'][1:]}x59", p["text"])
        self.assertTrue(all(p["end"] <= len(doc["text"]) for p in doc["paragraphs"]))

    def test_no_words_builds_nothing(self):
        self.assertIsNone(build("arc", database=Db({"t2": [snip("a", 0, "   ")]})))


if __name__ == "__main__":
    unittest.main()
