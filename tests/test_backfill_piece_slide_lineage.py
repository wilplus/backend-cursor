"""The detector that decides which Ideal Text heads render flat.

Founder 2026-09-18: "after a lock the text skipped the slides and got
concatenated again."  A head whose pieces all carry ``slide_index`` NULL makes
``groupChunksBySlide`` fail on the first paragraph (``missing_parent_slide``),
and the deck collapses into one unlinked "Your talk" section with no slide
kickers and no slide preview.

These hold the two halves that decide whether a canonical document gets
republished, so both have to be exactly as strict as the client's reader: too
loose and the script rewrites healthy documents, too tight and the broken ones
stay broken.
"""
from scripts.backfill_piece_slide_lineage import (
    _is_poisoned,
    _linked,
    _pieces,
)


def piece(slide):
    return {"piece_key": 0, "text": "words", "slide_index": slide}


class TestLinked:
    def test_counts_real_slide_indexes(self):
        assert _linked([piece(0), piece(1), piece(2)]) == 3

    def test_zero_is_a_slide(self):
        # The first slide is index 0, and a falsy check here would read the
        # whole first slide of every deck as unlinked.
        assert _linked([piece(0)]) == 1

    def test_null_is_not_a_slide(self):
        assert _linked([piece(None), piece(None)]) == 0

    def test_a_bool_is_not_a_slide(self):
        # bool is a subclass of int in Python; the client's reader rejects it
        # explicitly and so must this, or True would count as slide 1.
        assert _linked([piece(True), piece(False)]) == 0

    def test_a_negative_index_is_not_a_slide(self):
        assert _linked([piece(-1)]) == 0

    def test_a_non_integer_is_not_a_slide(self):
        assert _linked([piece("0"), piece(1.5), piece(None)]) == 0


class TestIsPoisoned:
    def test_every_index_null_is_poisoned(self):
        assert _is_poisoned([piece(None), piece(None), piece(None)]) is True

    def test_a_healthy_document_is_untouched(self):
        assert _is_poisoned([piece(0), piece(1), piece(2)]) is False

    def test_a_trailing_null_is_not_poisoned(self):
        # A NULL that FOLLOWS a real index is legitimate: the paragraph
        # continues on the slide it started on, and the client inherits it.
        # Republishing this document would be a write with nothing to fix.
        assert _is_poisoned([piece(0), piece(None), piece(1)]) is False

    def test_a_leading_null_with_any_real_index_is_not_in_scope(self):
        # This one DOES render flat (missing_parent_slide at index 0), but the
        # lineage is partly provable, so a republish could change more than it
        # repairs. Left out of the automatic sweep deliberately — it is a
        # narrower case that wants its own look, not a bulk rewrite.
        assert _is_poisoned([piece(None), piece(1)]) is False

    def test_a_single_paragraph_is_not_worth_republishing(self):
        # One paragraph renders as one section whether it is linked or not.
        assert _is_poisoned([piece(None)]) is False

    def test_no_pieces_at_all_is_not_poisoned(self):
        # Nothing to re-derive from, and nothing this script can prove.
        assert _is_poisoned([]) is False


class TestPieces:
    def test_reads_the_pieces_block(self):
        assert _pieces({"pieces": [piece(0)]}) == [piece(0)]

    def test_absent_block_is_empty(self):
        assert _pieces({}) == []
        assert _pieces(None) == []

    def test_non_mapping_rows_are_dropped(self):
        assert _pieces({"pieces": [piece(0), "junk", None]}) == [piece(0)]

    def test_a_non_list_block_is_empty(self):
        assert _pieces({"pieces": "nope"}) == []
