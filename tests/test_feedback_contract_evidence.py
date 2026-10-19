"""The exact transcript evidence one Feedback candidate carries, pinned
before ``_exact_transcript_evidence`` was split into named stages (audit W1,
2026-09-28).

The hashes are golden: they are the evidence identity the canonical tables
store, so a refactor that changes one byte of the identity changes them.
"""
from __future__ import annotations

from services.feedback_data_contract import _exact_transcript_evidence as ev

TEXT = "We started small. Then we shipped it fast."
SERVED = "We started small.\n\nThen we shipped it fast."
DOC = {
    "take_session_id": "take-2",
    "pieces": [
        {"snippet_id": "s1", "start": 0, "end": 17, "slide_index": 0,
         "start_offset_ms": 100, "duration_ms": 900, "recording_id": "rec-1",
         "audio_ref": "a/1.webm", "language": "en"},
        {"snippet_id": "s2", "start": 18, "end": 42, "slide_index": None,
         "start_offset_ms": 1000, "duration_ms": 0},
    ],
    "paragraphs": [{"start": 0, "end": 17}, {"start": 18, "end": 42}],
}
TRANSCRIPT = {"text": TEXT, "paragraphs": [{"slide_index": 0},
                                           {"slide_index": 3}]}
REWRITE = {"snippet_id": "s2", "span": {"start": 19, "end": 34},
           "proposed_text": " We sent it quickly. ",
           "take_session_id": "take-9"}


def _ev(family, row, **kwargs):
    kwargs.setdefault("served_text", SERVED)
    kwargs.setdefault("document", DOC)
    return ev(family=family, row=row, transcript=TRANSCRIPT, **kwargs)


def test_refusals():
    # No placeable words: a bad snippet span and no usable target.
    broken = dict(DOC, pieces=[dict(DOC["pieces"][0], start=17, end=3)])
    assert _ev("great_formulation", {"snippet_id": "s1"},
               document=broken) is None
    assert _ev("great_formulation", {"snippet_id": "s1",
                                     "span": {"start": 5, "end": 99}},
               document=broken) is None
    # Words outside every document paragraph.
    unparagraphed = dict(DOC, paragraphs=[{"start": 30, "end": 42}])
    assert _ev("confident_voice", {"snippet_id": "s1"},
               document=unparagraphed) is None
    # A paragraph index the transcript does not have.
    assert ev(family="confident_voice", row={"snippet_id": "s1"},
              document=DOC, served_text=SERVED,
              transcript={"text": TEXT, "paragraphs": []}) is None
    # Confident Voice with no playable duration.
    assert _ev("confident_voice", {"snippet_id": "s2"}) is None
    # A rewrite with nothing to propose.
    assert _ev("rewrite_clarity", dict(REWRITE, proposed_text="  ")) is None
