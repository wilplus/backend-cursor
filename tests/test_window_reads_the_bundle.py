"""The window finds the machine's read and the Slide-saved paragraphs
(F1 Repair Plan Phase 1).

Two defects the founder-lock audit of 2026-10-03 found in production:

* the score map was keyed by the bundle candidate's uuid and looked up by
  the served row's id (its candidate key), so every lookup missed and the
  window fell back to text order;
* a paragraph whose helper words were saved from a practice attempt or from
  an earlier Take -- stored on its Slide row, not on the paragraph -- did not
  count as saved, so it kept a bar that could never be answered.
"""
from services.ideal_text_changes import (
    saved_paragraphs, window_score, window_scores,
)

BUNDLE = {"candidates": [
    {"id": "11111111-aaaa-4aaa-8aaa-111111111111", "candidate_key": "cv-1",
     "feedback_family": "confident_voice", "candidate_score": 0.7},
    {"id": "22222222-aaaa-4aaa-8aaa-222222222222", "candidate_key": "cv-2",
     "feedback_family": "confident_voice", "candidate_score": -0.4},
    {"id": "33333333-aaaa-4aaa-8aaa-333333333333", "candidate_key": "cv-1",
     "feedback_family": "rewrite_clarity", "candidate_score": 9.0},
]}


def test_a_served_row_finds_its_read_by_its_id():
    scores = window_scores(BUNDLE)
    row = {"id": "cv-1", "feedback_family": "confident_voice"}
    assert window_score(scores, row) == 0.7
    assert window_score(scores, {"id": "cv-2",
                                 "feedback_family": "confident_voice"}) == -0.4


def test_the_family_keeps_two_items_with_one_key_apart():
    scores = window_scores(BUNDLE)
    assert window_score(scores, {"id": "cv-1",
                                 "feedback_family": "rewrite_clarity"}) == 9.0


def test_the_bundle_uuid_on_the_row_also_finds_it():
    scores = window_scores(BUNDLE)
    row = {"id": "other", "feedback_family": "confident_voice",
           "candidate_id": "22222222-aaaa-4aaa-8aaa-222222222222"}
    assert window_score(scores, row) == -0.4


def test_no_bundle_no_read():
    assert window_score(window_scores(None), {"id": "cv-1"}) is None
    assert window_score(window_scores({"candidates": [
        {"id": "x", "candidate_key": "k", "feedback_family": "f",
         "candidate_score": True}]}), {"id": "k", "feedback_family": "f"}) is None


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
