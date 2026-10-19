"""
STORY    As a speaker, I want feedback offered only where it points at exact
         words I said (and, for Confident Voice, a clip I can play), so that
         every piece of feedback is evidence-backed.
OUTCOME
  O1  A candidate whose words are found in the Take is served with evidence
      that quotes those exact words, their paragraph and slide, and (for
      Confident Voice) the playable clip window; a rewrite carries its
      replacement.
  O2  The evidence identity is stable: the same Take and candidate always
      produce the same evidence id and hash (the canonical tables key on it).
  O3  A candidate with no placeable words, words outside every paragraph, a
      Confident Voice clip with no playable audio, or a rewrite with nothing
      to propose produces no evidence and is not served.
  O4  When the bundle is bound to an Ideal Text snapshot, a surface that is
      not the one on screen, or a span that does not fit it, produces no
      evidence.
PROVES   O1 -> test_placeable_words_are_served_with_exact_evidence
         O2 -> test_evidence_identity_is_golden
         O3 -> test_feedback_without_evidence_is_not_served
         O4 -> test_feedback_bound_to_another_surface_is_not_served
WHY      Audit W1 (2026-09-28): evidence identity pinned before the builder
         was split into named stages.
"""
from __future__ import annotations

from hashlib import sha256

import pytest

from services.feedback_data_contract import build_feedback_exposure_bundle

V3 = "take-feedback-policy-v3-serving-v1"
TAKE = {
    "id": "take-2",
    "project_id": "11111111-2222-4333-8444-555555555555",
    "owner_principal_id": "99999999-8888-4777-8666-555555555555",
    "take_index": 1,
}
# What was said, and the Ideal Text on screen: same words, different layout,
# so every served span must be found again in the transcript.
TEXT = "We started small. Then we shipped it fast."
SERVED = "We started small.\n\nThen we shipped it fast."
SNAPSHOT = "33333333-4444-4555-8666-777777777777"
SURFACE_SHA = sha256(SERVED.encode("utf-8")).hexdigest()
DOC = {
    "take_session_id": "take-2",
    "text": TEXT,
    "pieces": [
        {"snippet_id": "s1", "start": 0, "end": 17, "slide_index": 0,
         "start_offset_ms": 100, "duration_ms": 900, "recording_id": "rec-1",
         "audio_ref": "a/1.webm", "language": "en"},
        {"snippet_id": "s2", "start": 18, "end": 42, "slide_index": None,
         "start_offset_ms": 1000, "duration_ms": 0},
    ],
    "paragraphs": [{"start": 0, "end": 17, "slide_index": 0},
                   {"start": 18, "end": 42, "slide_index": 3}],
}


def _span(words: str) -> dict:
    start = SERVED.index(words)
    return {"start": start, "end": start + len(words)}


CV = {"id": "cv-1", "feedback_family": "confident_voice", "snippet_id": "s1",
      "span": _span("We started small.")}
PRAISE = {"id": "gf-1", "feedback_family": "great_formulation",
          "snippet_id": "s2", "span": _span("we shipped it")}
REWRITE = {"id": "rc-1", "feedback_family": "rewrite_clarity",
           "snippet_id": "s2", "span": _span("Then we shipped it fast."),
           "proposed_text": " We sent it quickly. ",
           "take_session_id": "take-9"}
KEYS = [{"id": "cv-1", "feedback_family": "confident_voice"}]


def _serve(candidates, *, document=DOC, bound=True):
    """Build the bundle production writes; returns (bundle, closed gates)."""
    detail: list[str] = []
    snapshot = ({"document_snapshot_id": SNAPSHOT,
                 "document_surface_sha256": SURFACE_SHA} if bound else {})
    bundle = build_feedback_exposure_bundle(
        session=TAKE, transcript_document=document, served_text=SERVED,
        candidates=candidates, selected_keys=KEYS, manager_rules_version=V3,
        commit="test", detail=detail, **snapshot,
    )
    return bundle, detail


def _evidence(bundle) -> dict:
    return {row["candidate_key"]: row["evidence"]
            for row in bundle["candidates"]}


def test_placeable_words_are_served_with_exact_evidence():
    bundle, detail = _serve([CV, PRAISE, REWRITE])
    assert detail == []
    evidence = _evidence(bundle)

    voice = evidence["cv-1"]
    assert voice["exact_text"] == "We started small."
    assert TEXT[voice["start_char"]:voice["end_char"]] == "We started small."
    assert (voice["start_ms"], voice["end_ms"]) == (100, 1000)
    assert voice["audio_ref"] == "a/1.webm"
    assert voice["evidence_kind"] == "audio_and_transcript"
    assert (voice["paragraph_index"], voice["slide_index"]) == (0, 0)
    assert voice["target_locator"]["exact_text"] == "We started small."
    assert voice["target_locator"]["surface_hash"] == SURFACE_SHA

    # Verbal feedback quotes the served words where they occur in the Take.
    praise = evidence["gf-1"]
    assert praise["exact_text"] == "we shipped it"
    assert TEXT[praise["start_char"]:praise["end_char"]] == "we shipped it"
    assert praise["evidence_kind"] == "transcript_span"
    # The piece has no slide of its own, so the paragraph's slide is used.
    assert (praise["paragraph_index"], praise["slide_index"]) == (1, 3)

    rewrite = evidence["rc-1"]
    assert rewrite["exact_text"] == "Then we shipped it fast."
    assert rewrite["replacement_text"] == "We sent it quickly."
    assert rewrite["evidence_kind"] == "correction_pair"


GOLDEN = {
    "unbound":
        "dbc3772d70e41435a83113b8d519b6369933a8d3364b0317eef5614d052d90e6",
    "bound":
        "5539944a1b3be5164b40c09bafd1fbfebac17fd2d40207a8b4072941e45d2714",
    "bound_id": "a7ebe236-2b11-538b-b8ec-e45216217cbd",
}


def test_evidence_identity_is_golden():
    # Unbound and bound callers both key on these; a changed byte here means
    # every stored evidence row gets a new identity.
    unbound, _ = _serve([CV], bound=False)
    bound, _ = _serve([CV])
    assert _evidence(unbound)["cv-1"]["target_locator"] is None
    assert {
        "unbound": _evidence(unbound)["cv-1"]["evidence_hash"],
        "bound": _evidence(bound)["cv-1"]["evidence_hash"],
        "bound_id": _evidence(bound)["cv-1"]["id"],
    } == GOLDEN


BROKEN_CLIP = dict(DOC, pieces=[dict(DOC["pieces"][0], start=17, end=3)])


# Unbound, so each case is refused by its own evidence rule and not by the
# snapshot locator (which O4 proves separately).
@pytest.mark.parametrize("candidate, document", [
    pytest.param(dict(CV, span={"start": 5, "end": 99}), BROKEN_CLIP,
                 id="no-placeable-words"),
    pytest.param(dict(PRAISE, snippet_id="s1", span={"start": 5, "end": 99}),
                 BROKEN_CLIP, id="no-placeable-verbal-words"),
    pytest.param(CV, dict(DOC, paragraphs=[{"start": 30, "end": 42}]),
                 id="words-outside-every-paragraph"),
    pytest.param(dict(CV, snippet_id="s2",
                      span=_span("Then we shipped it fast.")),
                 DOC, id="confident-voice-without-playable-audio"),
    pytest.param(dict(REWRITE, proposed_text="  "), DOC,
                 id="rewrite-with-nothing-to-propose"),
])
def test_feedback_without_evidence_is_not_served(candidate, document):
    candidates = [candidate] if candidate["id"] == "cv-1" else [CV, candidate]
    bundle, detail = _serve(candidates, document=document, bound=False)
    assert bundle is None
    assert any(gate.startswith("candidate_not_canonical:")
               and gate.endswith("/" + candidate["id"]) for gate in detail)


@pytest.mark.parametrize("candidate, surface_sha", [
    pytest.param(CV, sha256(TEXT.encode("utf-8")).hexdigest(),
                 id="surface-is-not-the-screen"),
    pytest.param(dict(CV, span={"start": 5, "end": 99}), SURFACE_SHA,
                 id="span-not-on-the-screen"),
])
def test_feedback_bound_to_another_surface_is_not_served(candidate,
                                                         surface_sha):
    detail: list[str] = []
    assert build_feedback_exposure_bundle(
        session=TAKE, transcript_document=DOC, served_text=SERVED,
        candidates=[candidate], selected_keys=KEYS, manager_rules_version=V3,
        commit="test", detail=detail, document_snapshot_id=SNAPSHOT,
        document_surface_sha256=surface_sha,
    ) is None
    assert "candidate_not_canonical:confident_voice/cv-1" in detail
