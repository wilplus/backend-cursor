"""Where a stored Feedback row with no saved locator points, pinned before
``_document_evidence`` was split into named stages (audit W1, 2026-09-28):
the exact locator, the audio interval, and every refusal by its reason."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.feedback_repository import (
    FeedbackContractError,
    _document_evidence,
)

SESSION = {"id": "take-1", "arc_id": "arc-1"}
SNIPPET = {"id": "snip-1", "start_offset_ms": 1200, "duration_ms": 800}
DOCUMENT = {
    "pieces": [
        {"snippet_id": "other", "slide_index": 0, "start": 0, "end": 5,
         "text": "Other"},
        {"snippet_id": "snip-1", "slide_index": 2, "start": 7, "end": 18,
         "text": "our words"},
        "junk",
    ],
    "paragraphs": [
        {"start": 0, "end": 5},
        "junk",
        {"start": 7, "end": 30},
    ],
}


def _locate(document=DOCUMENT, session=SESSION, snippet=SNIPPET):
    with patch("services.transcript_document.build_transcript_document",
               return_value=document) as build:
        locator = _document_evidence(object(), dict(session), dict(snippet))
    return locator, build


def test_the_exact_locator():
    locator, build = _locate()
    assert build.call_args.args == ("arc-1",)
    assert build.call_args.kwargs["session_id"] == "take-1"
    # The paragraph index counts only well-formed paragraphs: the junk entry
    # is dropped first, so the one holding the span is index 1.
    assert (locator.project_id, locator.take_id, locator.slide_index,
            locator.paragraph_index, locator.piece_id) == (
        "arc-1", "take-1", 2, 1, "snip-1")
    assert dict(locator.evidence_span) == {
        "start": 7, "end": 18, "text": "our words"}
    assert dict(locator.audio_interval) == {"start_ms": 1200, "end_ms": 2000}


def test_the_take_and_project_fall_back():
    locator, build = _locate(session={"project_id": "p-1"},
                             snippet=dict(SNIPPET, session_id="take-9"))
    assert build.call_args.args == ("p-1",)
    assert build.call_args.kwargs["session_id"] == "take-9"
    assert (locator.project_id, locator.take_id) == ("p-1", "take-9")


def test_the_audio_interval():
    locator, _ = _locate(snippet=dict(SNIPPET, start_offset_ms=-50.7,
                                      duration_ms=20.9))
    assert dict(locator.audio_interval) == {"start_ms": 0, "end_ms": 0}
    locator, _ = _locate(snippet=dict(SNIPPET, start_offset_ms=100.4,
                                      duration_ms=200.9))
    assert dict(locator.audio_interval) == {"start_ms": 100, "end_ms": 301}
    for over in ({"duration_ms": None}, {"start_offset_ms": "1"}):
        locator, _ = _locate(snippet=dict(SNIPPET, **over))
        assert locator.audio_interval is None


def test_a_missing_text_is_empty():
    pieces = [dict(DOCUMENT["pieces"][1], text=None)]
    locator, _ = _locate(document=dict(DOCUMENT, pieces=pieces))
    assert locator.evidence_span["text"] == ""


@pytest.mark.parametrize("document, reason", [
    (None, "feedback requires an exact transcript span"),
    ({"pieces": "x"}, "feedback requires an exact transcript span"),
    (dict(DOCUMENT, pieces=[dict(DOCUMENT["pieces"][1],
                                 snippet_id="nope")]),
     "feedback requires an exact transcript span"),
    (dict(DOCUMENT, pieces=[dict(DOCUMENT["pieces"][1], slide_index=True)]),
     "feedback requires an exact slide"),
    (dict(DOCUMENT, pieces=[dict(DOCUMENT["pieces"][1], slide_index=None)]),
     "feedback requires an exact slide"),
    (dict(DOCUMENT, pieces=[dict(DOCUMENT["pieces"][1], start=-1)]),
     "feedback requires a valid evidence span"),
    (dict(DOCUMENT, pieces=[dict(DOCUMENT["pieces"][1], end=7)]),
     "feedback requires a valid evidence span"),
    (dict(DOCUMENT, pieces=[dict(DOCUMENT["pieces"][1], start="7")]),
     "feedback requires a valid evidence span"),
    (dict(DOCUMENT, paragraphs=[{"start": 0, "end": 5}]),
     "feedback requires an exact paragraph"),
    (dict(DOCUMENT, paragraphs="x"), "feedback requires an exact paragraph"),
    (dict(DOCUMENT, paragraphs=[{"start": "0", "end": 30}]),
     "feedback requires an exact paragraph"),
])
def test_every_refusal(document, reason):
    with pytest.raises(FeedbackContractError) as caught:
        _locate(document=document)
    assert str(caught.value) == reason


def test_no_project_is_refused():
    with pytest.raises(FeedbackContractError) as caught:
        _locate(session={"id": "take-1"})
    assert str(caught.value) == "feedback requires a project"
