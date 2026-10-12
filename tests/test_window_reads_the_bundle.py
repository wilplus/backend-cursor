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
    window_score,
    window_scores,
)

BUNDLE = {"candidates": [
    {"id": "11111111-aaaa-4aaa-8aaa-111111111111", "candidate_key": "cv-1",
     "feedback_family": "confident_voice", "candidate_score": 0.7},
    {"id": "22222222-aaaa-4aaa-8aaa-222222222222", "candidate_key": "cv-2",
     "feedback_family": "confident_voice", "candidate_score": -0.4},
    {"id": "33333333-aaaa-4aaa-8aaa-333333333333", "candidate_key": "cv-1",
     "feedback_family": "rewrite_clarity", "candidate_score": 9.0},
]}


def test_the_bundle_uuid_on_the_row_also_finds_it():
    scores = window_scores(BUNDLE)
    row = {"id": "other", "feedback_family": "confident_voice",
           "candidate_id": "22222222-aaaa-4aaa-8aaa-222222222222"}
    assert window_score(scores, row) == -0.4
