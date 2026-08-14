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


class ParagraphCapTests(unittest.TestCase):
    """SPEC §11.1 (founder 2026-08-14): within a slide run, pieces pack
    greedily up to PARAGRAPH_CAP_CHARS — the slide stops being the chunk's
    upper bound of readability; the cap is. Piece boundaries are the only
    cut points, so every split changes a separator and never a word."""

    def _long_pieces(self, n, slide=None, start_sid=0):
        text = ("these are the spoken words of one piece long enough to "
                "carry real content across the line")           # ~90 chars
        return [_snip(f"s{start_sid + i}", (start_sid + i) * 1000, text,
                      slide=slide) for i in range(n)]

    def test_a_long_single_slide_run_splits_at_the_cap(self):
        doc = build_transcript_document(
            ARC, database=_Db(self._long_pieces(6, slide=0)))
        paras = doc["text"].split("\n\n")
        self.assertGreater(len(paras), 1)
        from services.slide_word_split import PARAGRAPH_CAP_CHARS
        for para in paras:
            self.assertLessEqual(len(para), PARAGRAPH_CAP_CHARS + 1)
        # One provenance row per paragraph, ALL still slide 0 — sibling
        # paragraphs repeat their run's slide; the deck groups them back
        # into one slide section.
        rows = doc["paragraphs"]
        self.assertEqual(len(rows), len(paras))
        self.assertEqual({p["slide_index"] for p in rows}, {0})
        self.assertTrue(verify_spans(doc))

    def test_the_cap_never_cuts_inside_a_piece(self):
        # A single piece longer than the cap is its own paragraph, legally
        # over — verbatim beats the cap (a piece never splits). Distinct
        # tokens on purpose: smooth_piece collapses repeated words.
        big = " ".join(f"token{i}" for i in range(40))           # ~290 chars
        doc = build_transcript_document(
            ARC, database=_Db([_snip("s0", 0, big, slide=0)]))
        self.assertEqual(len(doc["paragraphs"]), 1)
        self.assertEqual(len(doc["pieces"]), 1)
        from services.slide_word_split import PARAGRAPH_CAP_CHARS
        self.assertGreater(len(doc["text"]), PARAGRAPH_CAP_CHARS)
        self.assertNotIn("\n\n", doc["text"])

    def test_the_words_survive_only_separators_change(self):
        # L1 verbatim by construction: strip the separators/terminal marks
        # and the capped document reads the same words in the same order.
        snips = self._long_pieces(6, slide=0)
        doc = build_transcript_document(ARC, database=_Db(snips))
        def _words(s):
            return [w for w in s.replace("\n\n", " ").split() ]
        joined = " ".join(s["transcript"] for s in snips)
        self.assertEqual(
            [w.lower().rstrip(".") for w in _words(doc["text"])],
            [w.lower() for w in _words(joined)])

    def test_a_long_no_slide_document_still_splits_readably(self):
        # No slide info = one RUN (no invented slide boundary), but the
        # cap still makes it readable paragraphs; none claims a slide.
        doc = build_transcript_document(
            ARC, database=_Db(self._long_pieces(6, slide=None)))
        self.assertGreater(len(doc["text"].split("\n\n")), 1)
        self.assertEqual({p["slide_index"] for p in doc["paragraphs"]},
                         {None})

    def test_a_slide_change_still_breaks_even_mid_pack(self):
        # The cap adds breaks; it never removes the slide boundary. Two
        # short slides stay two paragraphs even though one pack could
        # have held both.
        doc = build_transcript_document(ARC, database=_Db([
            _snip("s0", 0, "short words on slide one", slide=0),
            _snip("s1", 1000, "short words on slide two", slide=1)]))
        self.assertEqual(len(doc["text"].split("\n\n")), 2)
        self.assertEqual([p["slide_index"] for p in doc["paragraphs"]],
                         [0, 1])


class PackItemsTests(unittest.TestCase):
    """The shared packer itself — one home for the packing rule."""

    def _items(self, *widths):
        return [({"id": f"s{i}"}, "x" * w) for i, w in enumerate(widths)]

    def test_greedy_close_exactly_when_the_next_item_would_cross(self):
        from services.transcript_document import pack_items
        # 90 + 1 + 90 = 181 ≤ 200; adding another 90 (272) crosses.
        packs = pack_items(self._items(90, 90, 90), 200)
        self.assertEqual([len(p) for p in packs], [2, 1])

    def test_an_oversize_item_is_its_own_pack_never_split(self):
        from services.transcript_document import pack_items
        packs = pack_items(self._items(50, 300, 50), 200)
        self.assertEqual([len(p) for p in packs], [1, 1, 1])
        self.assertEqual(len(packs[1][0][1]), 300)

    def test_everything_under_the_cap_stays_one_pack(self):
        from services.transcript_document import pack_items
        packs = pack_items(self._items(50, 50, 50), 200)
        self.assertEqual([len(p) for p in packs], [3])

    def test_empty_in_empty_out(self):
        from services.transcript_document import pack_items
        self.assertEqual(pack_items([], 200), [])
