"""The exact transcript evidence one Feedback candidate carries, pinned
before ``_exact_transcript_evidence`` was split into named stages (audit W1,
2026-09-28).

The hashes are golden: they are the evidence identity the canonical tables
store, so a refactor that changes one byte of the identity changes them.
"""
from __future__ import annotations

import hashlib

from services.feedback_data_contract import _exact_transcript_evidence as ev

TEXT = "We started small. Then we shipped it fast."
SERVED = "We started small.\n\nThen we shipped it fast."
SHA = hashlib.sha256(SERVED.encode("utf-8")).hexdigest()
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


def test_confident_voice_keeps_its_own_audio_and_snippet_span():
    assert _ev("confident_voice", {
        "snippet_id": "s1", "span": {"start": 19, "end": 34},
    }) == {
        "id": "bfca52c2-8e69-5f02-8077-67bd191fd63e",
        "recording_id": "rec-1",
        "legacy_piece_id": "s1",
        "uses_transcript": True,
        "evidence_kind": "audio_and_transcript",
        "task_type": "confidence_classification",
        "audio_ref": "a/1.webm",
        "start_ms": 100,
        "end_ms": 1000,
        "start_char": 0,
        "end_char": 17,
        "exact_text": "We started small.",
        "replacement_text": None,
        "slide_index": 0,
        "paragraph_index": 0,
        "document_snapshot_id": None,
        "target_locator": None,
        "target_locator_sha256": None,
        "technical_metadata": {"duration_ms": 900, "language": "en"},
        "evidence_hash":
            "dbc3772d70e41435a83113b8d519b6369933a8d3364b0317eef5614d052d90e6",
        "input_hash":
            "dbc3772d70e41435a83113b8d519b6369933a8d3364b0317eef5614d052d90e6",
        "target_matches_transcript": True,
    }


def test_a_snapshot_bound_rewrite_moves_onto_the_target_words():
    assert _ev("rewrite_clarity", REWRITE, document_snapshot_id="snap-1",
               document_surface_sha256=SHA) == {
        "id": "e280810b-ad81-557d-8530-afd11ab4cde9",
        "recording_id": None,
        "legacy_piece_id": "s2",
        "uses_transcript": True,
        "evidence_kind": "correction_pair",
        "task_type": "correction_selection",
        "audio_ref": None,
        "start_ms": 1000,
        "end_ms": None,
        "start_char": 18,
        "end_char": 33,
        "exact_text": "Then we shipped",
        "replacement_text": "We sent it quickly.",
        # The piece has no slide, so the paragraph's is used.
        "slide_index": 3,
        "paragraph_index": 1,
        "document_snapshot_id": "snap-1",
        "target_locator": {
            "version": "ideal-text-target-locator-v1",
            "surface": "ideal_text",
            "surface_hash": SHA,
            "start": 19,
            "end": 34,
            "exact_text": "Then we shipped",
        },
        "target_locator_sha256":
            "d7264b39d71b446d8f46fa10874a853af37b0c27d8b3140de3784f0db8724b81",
        "technical_metadata": {"duration_ms": 0, "language": None},
        "evidence_hash":
            "f29ac1fa0794a61141ddf752a80dc3a31253b4c1bd8b0110b45be89c634bcbbf",
        "input_hash":
            "f29ac1fa0794a61141ddf752a80dc3a31253b4c1bd8b0110b45be89c634bcbbf",
        "target_matches_transcript": True,
    }


def test_praise_whose_target_is_not_in_the_transcript_keeps_the_snippet():
    out = _ev("great_formulation",
              {"snippet_id": "s2", "span": {"start": 0, "end": 2}},
              served_text="Xx and more")
    assert out is not None
    assert (out["evidence_kind"], out["task_type"]) == (
        "transcript_span", "praise_selection")
    assert (out["start_char"], out["end_char"], out["exact_text"]) == (
        18, 42, "Then we shipped it fast.")
    assert out["target_matches_transcript"] is False
    assert out["evidence_hash"] == (
        "1d2e8166d3f018bc82fc515984dd8818571a2dcd678dd111053974a1813e57f4")
    assert out["id"] == "32f34427-3504-5868-9287-7744a1373e47"


def test_a_target_in_the_transcript_needs_no_snippet():
    out = _ev("great_formulation",
              {"snippet_id": "gone", "span": {"start": 19, "end": 34}})
    assert (out["start_char"], out["end_char"], out["exact_text"]) == (
        18, 33, "Then we shipped")
    assert out["legacy_piece_id"] == "gone"
    assert (out["recording_id"], out["start_ms"], out["slide_index"]) == (
        None, None, 3)
    assert out["target_matches_transcript"] is True


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


def test_snapshot_binding_refuses_anything_but_an_exact_surface():
    bound = {"document_snapshot_id": "snap-1", "document_surface_sha256": SHA}
    assert _ev("rewrite_clarity", REWRITE, **bound) is not None
    for broken in (
        dict(bound, document_snapshot_id=""),
        dict(bound, document_snapshot_id=None),
        dict(bound, document_surface_sha256=None),
        dict(bound, document_surface_sha256="0" * 64),
    ):
        assert _ev("rewrite_clarity", REWRITE, **broken) is None
    assert _ev("rewrite_clarity", dict(REWRITE, span=None), **bound) is None


def test_an_unbound_call_never_carries_a_locator():
    out = _ev("rewrite_clarity", REWRITE)
    assert out["target_locator"] is None
    assert out["target_locator_sha256"] is None
    assert out["exact_text"] == "Then we shipped"
