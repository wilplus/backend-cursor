"""A live Take's Ideal Text is smoothed with the hesitation list of the
language Whisper heard (limitations assessment 2026-10-19, L2).

The Ideal Text builder picks its filler list by each piece's ``language``.
The live Take writer never stored one, so every live Take fell back to the
cross-language list, which keeps English "um" and "umm" because they are
real words elsewhere. This pins the hand-off: the language on the state is
on every stored piece, and the Ideal Text built from those pieces reads
without the speaker's "um"."""
from __future__ import annotations

import unittest

from services.recording_persistence import persist_recording_snippets
from services.recording_state import RecordingState
from services.transcript_document import build_transcript_document


class _Db:
    """Stores the pieces the Take writes, and serves them back to the
    Ideal Text builder."""

    def __init__(self):
        self.rows: list = []

    def create_charisma_snippets_bulk(self, rows):
        self.rows = [dict(r, id=f"s{i}") for i, r in enumerate(rows)]
        return [r["id"] for r in self.rows]

    @property
    def takes(self):
        return self

    def get_arc_sessions(self, arc_id):
        return [{"id": "take-1", "take_index": 1, "recording_kind": "spoken"}]

    def get_snippets_by_session(self, sid):
        return self.rows

    def get_coach_snippet_drafts(self, sid):
        return []

    def get_user_transcript_edits(self, sid):
        return []

    def get_snippet_slide_corrections(self, sid):
        return {}


def _take(language):
    piece = {"idx": 0, "start_ms": 0, "dur_ms": 4000,
             "transcript": "um so I think umm we should launch in May",
             "metrics": {"piece": {"index": 0}}}
    return RecordingState(
        session_id="take-1", user_id="u1", recording_id="r1",
        audio_bytes=b"", filename="take.webm", session_context={},
        parent_audio_url="a/take-1", recording_kind="spoken",
        paired_session_id=None, run_analytics=False,
        analyzed_pieces=(piece,), language=language)


class ALiveTakeIsSmoothedInItsOwnLanguage(unittest.TestCase):

    def test_an_english_take_reads_without_its_um(self):
        db = _Db()
        persist_recording_snippets(_take("en"), database=db)
        self.assertEqual([r.get("language") for r in db.rows], ["en"])
        doc = build_transcript_document("arc", database=db)
        self.assertEqual(doc["text"], "So I think we should launch in May.")

    def test_a_take_whisper_named_no_language_keeps_the_safe_list(self):
        db = _Db()
        persist_recording_snippets(_take(None), database=db)
        doc = build_transcript_document("arc", database=db)
        self.assertIn("um", doc["text"].lower().split())


if __name__ == "__main__":
    unittest.main()
