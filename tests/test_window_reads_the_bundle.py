"""The window finds the Slide-saved paragraphs (F1 Repair Plan Phase 1).

A defect the founder-lock audit of 2026-10-03 found in production:

* a paragraph whose helper words were saved from a practice attempt or from
  an earlier Take -- stored on its Slide row, not on the paragraph -- did not
  count as saved, so it kept a bar that could never be answered.
"""
from services.ideal_text_changes import saved_paragraphs

PARTS = [
    {"id": "P-ONE", "locked_at": "t", "root_phrase": "own words"},
    {"id": "p-two", "locked_at": "t", "root_phrase": None},
    {"id": "p-three", "locked_at": None, "root_phrase": None},
    {"id": "p-four", "locked_at": "t", "root_phrase": None},
]


def test_paragraph_words_count_as_before():
    assert saved_paragraphs(PARTS, set()) == {0}


def test_slide_saved_words_count_for_the_paragraph_they_name():
    assert saved_paragraphs(PARTS, {"p-two"}) == {0, 1}


def test_an_unlocked_paragraph_is_not_saved_by_its_slide_row():
    assert saved_paragraphs(PARTS, {"p-three"}) == {0}


def test_ids_compare_case_blind():
    assert saved_paragraphs(PARTS, {"p-one"}) == {0}
    assert saved_paragraphs([{"id": "P-FOUR", "locked_at": "t"}], {"p-four"}) == {0}
