"""
STORY    As a speaker, I want each spoken piece attached to the right
         paragraph of my Ideal Text (slide first, then span, never a guess),
         so that feedback lands on the paragraph I actually said. (Ideal
         Text -> feedback: an item with no paragraph is attached to nothing.)
OUTCOME
  O1  On a slide with one paragraph, the piece gets that paragraph's id,
      whatever words it carries.
  O2  On a slide with several paragraphs, the piece's span picks the
      paragraph, and its served-text span rides along.
  O3  When the proofs disagree, or nothing proves which paragraph, or the
      paragraph has no usable id, the piece gets no part_id.
  O4  One malformed piece never costs the others their binding.
PROVES   O1 -> test_a_piece_on_a_one_paragraph_slide_takes_that_paragraph
         O2 -> test_a_span_picks_between_paragraphs_on_one_slide
         O3 -> test_a_span_disagreeing_with_its_slide_binds_to_nothing
               test_a_piece_whose_words_are_gone_binds_to_nothing
               test_a_paragraph_with_no_usable_id_binds_to_nothing
         O4 -> test_a_malformed_piece_passes_through_untouched
WHY      Production 2026-09-19: V3 stood down on every Take with
         piece_has_no_part_id, because nothing ever wrote part_id.
"""
from __future__ import annotations

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


ID1, ID2, ID3 = (p["id"] for p in PARTS)


def test_a_piece_on_a_one_paragraph_slide_takes_that_paragraph():
    # Slide 1 holds THIRD alone. The speaker rewrote it, so the pieces'
    # words are gone, and the slide's region (here starting at the blank
    # line before THIRD) gives a span no single paragraph contains: only the
    # slide proves the paragraph, and that is enough.
    regions = {0: REGIONS[0], 1: (REGIONS[0][1], len(SERVED))}
    assert _bind([_piece("s3", "something said quite differently", 1, 0, 32),
                  _piece("s4", "and more words that are gone", 1, 33, 61)],
                 regions=regions) == [ID3, ID3]


def test_a_span_picks_between_paragraphs_on_one_slide():
    transcript_first, transcript_second = (0, len(FIRST)), (len(FIRST) + 1, len(FIRST) + 1 + len(SECOND))
    out = bind_pieces_to_parts(
        _doc([_piece("s1", FIRST, 0, *transcript_first),
              _piece("s2", SECOND, 0, *transcript_second)]),
        served_text=SERVED, slide_regions=REGIONS, parts=PARTS)
    first, second = out["pieces"]
    assert (first["part_id"], second["part_id"]) == (ID1, ID2)
    assert SERVED[second["served_start"]:second["served_end"]] == SECOND


def test_a_span_disagreeing_with_its_slide_binds_to_nothing():
    # Two proofs that disagree are not a proof: words matching slide 1's
    # Paragraph, spoken (per the piece) on slide 0.
    assert _bind([_piece("s3", THIRD, 0, 0, len(THIRD))]) == [None]


def test_a_piece_whose_words_are_gone_binds_to_nothing():
    # Slide 0 holds two Paragraphs and the words appear in neither: the slide
    # alone cannot say which, so nothing is guessed.
    assert _bind([_piece("s1", "words the speaker later deleted", 0, 0, 31)]) == [None]


def test_a_paragraph_with_no_usable_id_binds_to_nothing():
    # A part row that lost its id cannot be a `source_ideal_part_id`.
    nameless = [{"id": None, "text": FIRST, "ord": 0}, {"id": "", "text": SECOND, "ord": 1}]
    served = f"{FIRST}\n\n{SECOND}"
    assert _bind([_piece("s1", FIRST, 0, 0, len(FIRST))], parts=nameless,
                 regions={0: (0, len(served))}, served=served) == [None]
    assert _bind([_piece("s1", FIRST, 0, 0, len(FIRST))], parts=nameless[:1],
                 regions={0: (0, len(FIRST))}, served=FIRST) == [None]


def test_a_malformed_piece_passes_through_untouched():
    # `pieces` is JSON off a document row; one bad entry must not cost the
    # document its other bindings.
    out = bind_pieces_to_parts(
        _doc(["not a dict", _piece("s3", "spoken", 1, 0, 6)]),
        served_text=SERVED, slide_regions=REGIONS, parts=PARTS,
    )
    assert out["pieces"][0] == "not a dict"
    assert out["pieces"][1]["part_id"] == ID3
