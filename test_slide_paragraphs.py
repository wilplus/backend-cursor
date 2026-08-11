"""THE SLIDE BOUNDARY IS A PARAGRAPH (founder 2026-08-11).

The read surface defines a CHUNK — the unit carrying one lock and one state —
as a "\\n\\n" paragraph. `_JOIN` was a single space, so a whole talk arrived as
ONE paragraph: one lock for the entire speech, one pending suggestion painting
every word of it, and no slide sections to scroll through, because the deck
groups by slide and there was only ever one group to group into.

The per-slide 1:1 segmentation — the load-bearing half of the north star's
piece (a) — existed in the data the whole time. It was thrown away here, at
the join, in the one place a user actually reads it.

These tests hold both directions: a provable slide change MUST break the
paragraph, and anything less than provable MUST NOT. Inventing a boundary is
worse than missing one, because a boundary is a lock unit.

Run: python3 -m unittest test_slide_paragraphs
"""
from __future__ import annotations

import unittest

from services.transcript_document import build_transcript_document, verify_spans

ARC = "arc-1"
T1 = "take-1"


def _snip(sid, at_ms, text, slide=None, **extra):
    row = {"id": sid, "start_offset_ms": at_ms, "language": "en",
           "transcript": text}
    if slide is not None:
        row["metrics"] = {"piece": {"slide_index": slide}}
    row.update(extra)
    return row


class _Db:
    def __init__(self, snips, *, slide_fixes=None):
        self._snips = snips
        self._fixes = slide_fixes

    def get_arc_sessions(self, arc_id):
        return [{"id": T1, "take_index": 1, "recording_kind": "spoken"}]

    def get_snippets_by_session(self, sid):
        return self._snips

    def get_coach_snippet_drafts(self, sid):
        return []

    def get_user_transcript_edits(self, sid):
        return []

    def get_snippet_slide_corrections(self, sid):
        if self._fixes is None:
            raise RuntimeError("no such table")   # pre-migration, on purpose
        return self._fixes


THREE_SLIDES = [
    _snip("a", 0, "we started small", slide=0),
    _snip("b", 4000, "the numbers came in strong", slide=1),
    _snip("c", 8000, "so here is the ask", slide=2),
]


class ParagraphPerSlideTests(unittest.TestCase):
    def test_each_slide_becomes_its_own_paragraph(self):
        doc = build_transcript_document(ARC, database=_Db(THREE_SLIDES))
        self.assertEqual(len(doc["text"].split("\n\n")), 3)
        self.assertEqual([p["slide_index"] for p in doc["paragraphs"]],
                         [0, 1, 2])

    def test_two_pieces_on_ONE_slide_stay_one_paragraph(self):
        # The talk still reads as a talk. Only the slide change breaks it —
        # a paragraph per piece would be a list of fragments.
        snips = [
            _snip("a", 0, "we started small", slide=0),
            _snip("b", 2000, "in a garage with nothing", slide=0),
            _snip("c", 8000, "so here is the ask", slide=1),
        ]
        doc = build_transcript_document(ARC, database=_Db(snips))
        paras = doc["text"].split("\n\n")
        self.assertEqual(len(paras), 2)
        self.assertIn("garage", paras[0])
        self.assertNotIn("\n", paras[0])

    def test_the_spans_survive_the_break(self):
        # The anchor contract for tracked changes. A separator that is two
        # characters where the cursor counted one puts every later piece off
        # by the number of paragraphs before it.
        doc = build_transcript_document(ARC, database=_Db(THREE_SLIDES))
        self.assertTrue(verify_spans(doc))
        for p in doc["pieces"]:
            self.assertEqual(doc["text"][p["start"]:p["end"]], p["text"])
        for p in doc["paragraphs"]:
            self.assertNotIn("\n", doc["text"][p["start"]:p["end"]])

    def test_every_paragraph_ends_on_a_terminal_mark(self):
        # smooth_piece leaves pieces unpunctuated (they are usually
        # mid-sentence) and finalize_document only closes the document's very
        # end — invisible while the whole talk was one paragraph, and the
        # seam between every pair of them the moment slides split it.
        doc = build_transcript_document(ARC, database=_Db(THREE_SLIDES))
        for para in doc["text"].split("\n\n"):
            self.assertIn(para.strip()[-1], ".!?")

    def test_pieces_stay_ONE_PER_SNIPPET(self):
        # paragraphs and pieces are different lists on purpose: pieces is the
        # per-snippet anchor contract, paragraphs is what the reader chunks.
        snips = [
            _snip("a", 0, "we started small", slide=0),
            _snip("b", 2000, "in a garage", slide=0),
        ]
        doc = build_transcript_document(ARC, database=_Db(snips))
        self.assertEqual(len(doc["pieces"]), 2)
        self.assertEqual(len(doc["paragraphs"]), 1)
        self.assertEqual([p["slide_index"] for p in doc["pieces"]], [0, 0])


class UnprovableBoundaryTests(unittest.TestCase):
    """A boundary is a lock unit — never invent one."""

    def test_no_slide_information_at_all_stays_one_paragraph(self):
        snips = [_snip("a", 0, "we started small"),
                 _snip("b", 4000, "and then we shipped it")]
        doc = build_transcript_document(ARC, database=_Db(snips))
        self.assertNotIn("\n\n", doc["text"])
        self.assertEqual(len(doc["paragraphs"]), 1)
        self.assertIsNone(doc["paragraphs"][0]["slide_index"])

    def test_an_unknown_piece_between_two_known_ones_does_not_break(self):
        snips = [
            _snip("a", 0, "we started small", slide=0),
            _snip("b", 2000, "and it worked"),            # no bucket
            _snip("c", 4000, "in a garage", slide=0),
        ]
        doc = build_transcript_document(ARC, database=_Db(snips))
        self.assertNotIn("\n\n", doc["text"])

    def test_an_unknown_piece_does_not_hide_a_later_real_change(self):
        # The run keeps the last PROVEN slide, so slide 1 still breaks even
        # though the piece before it knew nothing.
        snips = [
            _snip("a", 0, "we started small", slide=0),
            _snip("b", 2000, "and it worked"),
            _snip("c", 4000, "the numbers came in", slide=1),
        ]
        doc = build_transcript_document(ARC, database=_Db(snips))
        self.assertEqual(len(doc["text"].split("\n\n")), 2)

    def test_a_bool_is_not_a_slide_index(self):
        snips = [_snip("a", 0, "we started small", slide=True),
                 _snip("b", 4000, "and then we shipped it", slide=0)]
        doc = build_transcript_document(ARC, database=_Db(snips))
        self.assertNotIn("\n\n", doc["text"])


class CoachCorrectionTests(unittest.TestCase):
    def test_the_coach_bucket_wins_and_the_paragraphs_follow(self):
        # The whole slide-correction affordance exists to make the human the
        # ground truth here; a correction that did not reflow the document
        # would be a correction the reader never sees.
        snips = [_snip("a", 0, "we started small", slide=0),
                 _snip("b", 4000, "and then we shipped it", slide=0)]
        doc = build_transcript_document(
            ARC, database=_Db(snips, slide_fixes={"b": 1}))
        self.assertEqual(len(doc["text"].split("\n\n")), 2)
        self.assertEqual([p["slide_index"] for p in doc["paragraphs"]], [0, 1])

    def test_a_revert_falls_THROUGH_to_the_pipeline_bucket(self):
        # slide_index None in the corrections table is a withdrawal, not an
        # assertion that the slide is unknown — the same rule _build_take
        # follows.
        snips = [_snip("a", 0, "we started small", slide=0),
                 _snip("b", 4000, "the numbers came in", slide=1)]
        doc = build_transcript_document(
            ARC, database=_Db(snips, slide_fixes={"b": None}))
        self.assertEqual(len(doc["text"].split("\n\n")), 2)

    def test_a_missing_corrections_table_degrades_to_the_pipeline(self):
        # _Db raises when slide_fixes is None — pre-migration.
        doc = build_transcript_document(ARC, database=_Db(THREE_SLIDES))
        self.assertEqual(len(doc["paragraphs"]), 3)


if __name__ == "__main__":
    unittest.main()
