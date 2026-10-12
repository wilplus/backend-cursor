"""What build_transcript_document builds, pinned before its split into
named stages (audit W1, 2026-09-28): one exact document, the take it reads,
the coach's slide fixes, the length cap, and every way it builds nothing.

tests/test_living_transcript.py and tests/test_slide_paragraphs.py hold the
product cases; these pin the whole payload and the refusals that had no
test."""
from __future__ import annotations

import unittest

from services.transcript_document import build_transcript_document as build


class Db:
    def __init__(self, snips, *, sessions=None, session_row=None,
                 fixes=None, raise_on=None):
        self._snips, self._sessions = snips, sessions
        self._row, self._fixes, self._raise = session_row, fixes, raise_on or set()

    @property
    def takes(self):
        return self

    def _maybe_raise(self, name):
        if name in self._raise:
            raise RuntimeError(name)

    def get_arc_sessions(self, arc_id):
        self._maybe_raise("get_arc_sessions")
        if self._sessions is not None:
            return self._sessions
        return [{"id": "t1", "take_index": 1, "recording_kind": "spoken"}]

    def v2_get_session_by_id(self, sid):
        self._maybe_raise("v2_get_session_by_id")
        return self._row

    def get_snippets_by_session(self, sid):
        self._maybe_raise("get_snippets_by_session")
        return self._snips

    def get_coach_snippet_drafts(self, sid):
        return []

    def get_user_transcript_edits(self, sid):
        return []

    def get_snippet_slide_corrections(self, sid):
        self._maybe_raise("get_snippet_slide_corrections")
        return self._fixes or {}


def snip(sid, ms, text, slide=None, **extra):
    row = {"id": sid, "start_offset_ms": ms, "language": "en",
           "transcript": text, "recording_id": "rec-" + sid,
           "audio_ref": "a/" + sid, "duration_ms": 900}
    if slide is not None:
        row["metrics"] = {"piece": {"slide_index": slide}}
    row.update(extra)
    return row


SNIPS = [
    snip("s3", 9000, "and this one closes slide two", slide=1),
    snip("s1", 0, "um we started small", slide=0),
    snip("s2", 4000, "then we uh shipped it fast", slide=0),
    snip("s4", 12000, "   ", slide=1),
]


class BuildTranscriptDocumentPins(unittest.TestCase):


    def test_a_document_over_the_cap_is_cut_at_a_word_and_keeps_whole_pieces(
            self):
        long = [snip(f"L{i}", i * 1000,
                     " ".join(f"w{i}x{j}" for j in range(60)))
                for i in range(160)]
        doc = build("arc", database=Db(long))
        self.assertEqual(len(doc["text"]), 39997)
        self.assertEqual(len(doc["pieces"]), 98)
        self.assertEqual(len(doc["paragraphs"]), 98)
        self.assertEqual(doc["text"][-40:], '8x27 w98x28 w98x29 w98x30 w98x31 w98x32.')
        self.assertEqual(doc["pieces"][-1]["snippet_id"], "L97")
        self.assertTrue(all(p["end"] <= len(doc["text"])
                            for p in doc["pieces"] + doc["paragraphs"]))
        for p in doc["pieces"]:
            self.assertEqual(doc["text"][p["start"]:p["end"]], p["text"])

    def test_nothing_to_build_is_none(self):
        self.assertIsNone(build("arc", database=Db(SNIPS, sessions=[])))
        self.assertIsNone(build("arc", database=Db(SNIPS, sessions=[
            {"id": None, "take_index": 1, "recording_kind": "spoken"}])))
        self.assertIsNone(build("arc", database=Db([])))
        self.assertIsNone(build("arc", database=Db([
            snip("a", 0, "   "), snip("b", 1, None)])))
        # Words that smoothing removes entirely are no words.
        self.assertIsNone(build("arc", database=Db([snip("a", 0, "um uh")])))


if __name__ == "__main__":
    unittest.main()
