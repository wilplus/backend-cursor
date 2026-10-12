"""The gate that had no key: a spoken piece learns its Paragraph.

PRODUCTION, 2026-09-19. The founder's take, read from the Railway log after
three rounds of making that log readable:

    v3 stood down take=440b7c97-… reason=service_inventory_unavailable
    detail=piece_has_no_part_id; at_candidate:1; confidence_block_rejected:1

``piece_has_no_part_id`` is the TENTH and last of ``_row_rejection``'s checks.
Everything before it passed -- candidate id, snippet present in the document,
span shape, span bounds, eligibility, recording id, start offset, duration.
The frame was healthy all the way to the final binding.

And that binding could never happen. ``build_transcript_document`` writes
eleven fields onto a piece and ``part_id`` is not one of them; neither does
``master_document``. So V3 has produced nothing since the cutover, for any
Take -- a gate with no key, the same shape as ``service_enrollment_missing``,
which was found and removed the same way days earlier. Two consumers read
this field and nothing produced it.

THE GATE STAYS. ``source_ideal_part_id`` is a required, UUID-validated field
of the feedback contract; it is the Paragraph a bookmark hangs on. An item
with no part is attached to nothing.

THE RULE (founder, 2026-09-19): slide first, span to refine, and no guess.
"""
from __future__ import annotations

import unittest

from services.ideal_text_parts import bind_pieces_to_parts

# Two Paragraphs, joined by "\n\n" exactly as `joined`/`part_spans` require.
FIRST = "The opening paragraph of the talk."
SECOND = "A second paragraph, on the very same slide."
THIRD = "The paragraph belonging to the next slide."
SERVED = f"{FIRST}\n\n{SECOND}\n\n{THIRD}"

PARTS = [
    {"id": "11111111-1111-4111-8111-111111111111", "text": FIRST, "ord": 0},
    {"id": "22222222-2222-4222-8222-222222222222", "text": SECOND, "ord": 1},
    {"id": "33333333-3333-4333-8333-333333333333", "text": THIRD, "ord": 2},
]

# Slide 0 holds the first two Paragraphs; slide 1 holds the third alone.
REGIONS = {
    0: (0, len(FIRST) + 2 + len(SECOND)),
    1: (len(FIRST) + 2 + len(SECOND) + 2, len(SERVED)),
}


def _doc(pieces):
    return {"take_session_id": "take-1", "text": SERVED, "pieces": pieces}


def _bind(pieces, *, parts=PARTS, regions=REGIONS, served=SERVED):
    out = bind_pieces_to_parts(
        _doc(pieces), served_text=served, slide_regions=regions, parts=parts,
    )
    return [p.get("part_id") for p in out["pieces"]]


def _piece(snippet_id, text, slide, start, end):
    # The shape `build_transcript_document` actually emits, minus part_id.
    return {
        "snippet_id": snippet_id, "text": text, "slide_index": slide,
        "start": start, "end": end, "take_session_id": "take-1",
        "recording_id": "rec-1", "start_offset_ms": 0, "duration_ms": 1000,
    }


class NothingIsGuessed(unittest.TestCase):


    def test_a_span_disagreeing_with_its_slide_binds_to_nothing(self):
        # Two proofs that disagree are not a proof: words matching slide 1's
        # Paragraph, spoken (per the piece) on slide 0.
        self.assertEqual(_bind([_piece("s3", THIRD, 0, 0, len(THIRD))]), [None])


class TheEdgesThatAReadCanActuallyHit(unittest.TestCase):
    """Each of these is a shape a real read produces, not a hypothetical."""

    def test_a_malformed_piece_passes_through_untouched(self):
        # `pieces` is JSON off a document row; one bad entry must not cost
        # the document its other bindings.
        out = bind_pieces_to_parts(
            _doc(["not a dict", _piece("s3", "spoken", 1, 0, 6)]),
            served_text=SERVED, slide_regions=REGIONS, parts=PARTS,
        )
        self.assertEqual(out["pieces"][0], "not a dict")
        self.assertEqual(out["pieces"][1]["part_id"],
                         "33333333-3333-4333-8333-333333333333")

    def test_a_piece_relocation_dropped_binds_to_nothing(self):
        from services.ideal_text_parts import _part_id_for, part_spans

        # `relocate_pieces` drops a piece whose words are genuinely gone and
        # whose gap is empty. There is then no span to refine with, and the
        # slide holds two Paragraphs, so nothing proves which.
        self.assertIsNone(
            _part_id_for(
                _piece("s1", FIRST, 0, 0, len(FIRST)),
                None, part_spans(PARTS), REGIONS,
            ))

    def test_a_paragraph_with_no_usable_id_binds_to_nothing(self):
        from services.ideal_text_parts import _part_id_for, part_spans

        # A part row that lost its id cannot be a `source_ideal_part_id`;
        # the contract UUID-validates it downstream.
        nameless = [{"id": None, "text": FIRST, "ord": 0},
                    {"id": "", "text": SECOND, "ord": 1}]
        spans = part_spans(nameless)
        self.assertIsNone(_part_id_for(
            _piece("s1", FIRST, 0, 0, len(FIRST)),
            {"snippet_id": "s1", "start": 0, "end": len(FIRST)},
            spans, {},
        ))
