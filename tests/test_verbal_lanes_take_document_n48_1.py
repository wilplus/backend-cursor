"""
STORY    As a speaker, I want feedback on later Takes to point at the right
         words and never show internal numbers, so that a slide I did not
         speak cannot confuse it.
OUTCOME
  O1  A verbal row on words of this Take is mapped into the Take's own
      transcript (its served span shifted past the unspoken Slide).
  O2  A verbal row on a Slide this Take did not speak, or with no served
      text to prove it, is excluded as ``document_span_unmapped``.
  O3  NEVER-1: the rows that leave the server carry the feedback's words
      and no rank, evidence, score, version or other number (AC-9).
  O4  A served clearer version names the moment it corrects (its block),
      so the walk draws it on that moment and not as a moment of its own
      (founder 2026-10-20: "the rewrite doesn't appear at all").
PROVES   O1 -> test_a_row_on_this_takes_words_is_mapped_into_its_transcript
         O2 -> test_a_row_on_an_unspoken_slide_is_excluded
         O3 -> test_a_served_v3_payload_carries_no_internal_evidence_or_numbers
         O3 -> test_a_stray_mlc3_service_block_never_reaches_the_client
         O4 -> test_a_served_rewrite_rides_its_moments_block
WHY      N48.1 (Wave 1, E1), founder-approved 2026-10-05: from Take 2 on the
         served Ideal Text and the Take's transcript are two documents.
"""
from __future__ import annotations

from services.ideal_text_parts import with_served_spans
from services.take_feedback_manager import (
    exposure_snapshot,
    strip_internal_evidence,
)
from services.take_feedback_policy_v3 import (
    build_service_candidate_frame,
    build_shadow_frame,
)
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory
from services.tracked_changes import (
    STRUCTURAL_DEVICE_DETECTOR_VERSION,
    build_tracked_changes,
)
from services.transcript_document import relocate_pieces

TAKE = "take-2"
RECORDING = "recording-2"

# Slide 0 was NOT spoken in Take 2, so the served Ideal Text keeps Take 1's
# Paragraph for it (take_rebuild.merge_by_slide). Slides 1 and 2 are Take 2's.
OLD_SLIDE_0 = (
    "Last year we started with a single classroom and one teacher who "
    "believed in it."
)
SPOKEN = [
    # (snippet, slide, words, delivery score)
    ("s1a", 1, "Our second idea is simple and it changes how every student "
               "practises at home", -0.6),
    ("s1b", 1, "we give each learner a short daily task that builds on the "
               "one before it.", -0.6),
    ("s2a", 2, "The results so far are clear", 0.8),
    ("s2b", 2, "reading scores rose in every group we measured this spring.",
     0.8),
]


def _take_document() -> dict:
    """Take 2's transcript document: its own two Slides, nothing else."""
    pieces, parts, cursor = [], [], 0
    for index, (sid, slide, words, _score) in enumerate(SPOKEN):
        if index:
            sep = " " if SPOKEN[index - 1][1] == slide else "\n\n"
            parts.append(sep)
            cursor += len(sep)
        pieces.append({
            "snippet_id": sid, "take_session_id": TAKE, "take_index": 2,
            "slide_index": slide, "start": cursor,
            "end": cursor + len(words), "text": words,
            "recording_id": RECORDING, "start_offset_ms": index * 4000,
            "duration_ms": 4000,
        })
        parts.append(words)
        cursor += len(words)
    return {"text": "".join(parts), "pieces": pieces,
            "take_session_id": TAKE, "take_index": 2}


DOC = _take_document()
SERVED = OLD_SLIDE_0 + "\n\n" + DOC["text"]
SHIFT = len(OLD_SLIDE_0) + 2


def _snippets() -> list[dict]:
    return [{
        "id": piece["snippet_id"], "session_id": TAKE,
        "recording_id": RECORDING,
        "start_offset_ms": piece["start_offset_ms"],
        "duration_ms": piece["duration_ms"],
        "metrics": {"voice_confidence": {
            "version": "voice-confidence-universal-v3", "score": score,
        }},
    } for piece, (_s, _sl, _w, score) in zip(DOC["pieces"], SPOKEN)]


def _placed_document(*, parts: bool = False) -> dict:
    """The document as the service sees it: pieces placed on the served text
    (and, for the service, bound to a Paragraph -- `bind_pieces_to_parts`)."""
    placed = with_served_spans(DOC, served_text=SERVED, slide_regions={})
    if parts:
        placed = {**placed, "pieces": [
            {**piece, "part_id": f"part-slide-{piece['slide_index']}"}
            for piece in placed["pieces"]
        ]}
    return placed


def _served_span(words: str) -> dict:
    at = SERVED.index(words)
    return {"start": at, "end": at + len(words)}


def _row(row_id, family, words, *, snippet, take=TAKE, **extra) -> dict:
    span = _served_span(words)
    return {
        "id": row_id, "feedback_family": family, "snippet_id": snippet,
        "take_session_id": take, "span": span,
        "quote": SERVED[span["start"]:span["end"]], **extra,
    }


def _praise(row_id="structural-praise", words=SPOKEN[3][2], **extra):
    return _row(row_id, "great_formulation", words, snippet="s2b",
                kind="advice", source="structural", device="contrast",
                detector_version=STRUCTURAL_DEVICE_DETECTOR_VERSION,
                _manager_evidence={"detector": "structural_device",
                                   "fallback": False,
                                   "lexical_words_invented": 0},
                **extra)


def _rewrite(row_id="structural-repair", **extra):
    return _row(row_id, "rewrite_clarity", SPOKEN[0][2], snippet="s1a",
                kind="replace", proposed_text="Our second idea is simple.",
                rule_version="structural-rewrite-v1",
                _manager_evidence={"fallback": False, "specificity": 5,
                                   "detector": "stranded_negated_object_boundary",
                                   "lexical_words_invented": 0},
                **extra)


def _frame(rows, *, served=SERVED, document=None):
    return build_shadow_frame(
        take_document=document or _placed_document(),
        snippets=_snippets(), suggestions={}, feedback_candidates=rows,
        take_index=2, expected_recording_id=RECORDING, served_text=served,
    )


def _tracked(suggestion: dict, sid: str = "s2b") -> list[dict]:
    """Tracked changes over the served text (shared with
    tests/test_clearer_versions_reach_the_manager.py)."""
    pieces = relocate_pieces(SERVED, DOC["pieces"], paragraph_fallback=True,
                             slide_regions={})
    return build_tracked_changes(SERVED, pieces, {sid: suggestion})


def _lane(frame, family):
    return {c["candidate_id"]: c for c in frame["verbal_lanes"][family]["candidates"]}


def test_a_row_on_this_takes_words_is_mapped_into_its_transcript():
    praise = _praise()
    row = _lane(_frame([praise]), "great_formulation")["structural-praise"]
    assert row["eligibility"] == "eligible"
    assert row["document_span"] == {"start": praise["span"]["start"] - SHIFT,
                                    "end": praise["span"]["end"] - SHIFT}
    span = row["document_span"]
    assert DOC["text"][span["start"]:span["end"]] == SPOKEN[3][2]


def test_a_row_on_an_unspoken_slide_is_excluded():
    lane = _lane(_frame([_praise(), _praise("old-praise", OLD_SLIDE_0)]),
                 "great_formulation")
    assert lane["structural-praise"]["eligibility"] == "eligible"
    assert (lane["old-praise"]["eligibility"],
            lane["old-praise"]["exclusion_reason"]) == ("excluded", "document_span_unmapped")
    unproven = _lane(_frame([_praise()], served=None), "great_formulation")
    assert unproven["structural-praise"]["exclusion_reason"] == "document_span_unmapped"


# ── AC-9 at the serving boundary: only client-read fields leave ────────────

def _numeric_leaves(value, path=""):
    """Every number in a row outside the location coordinates the client
    reads (`evidence`, `span`) and the clip window it plays."""
    allowed = ("span", "evidence", "start_offset_ms", "duration_ms")
    if isinstance(value, dict):
        for key, item in value.items():
            if not path and key in allowed:
                continue
            yield from _numeric_leaves(item, f"{path}.{key}")
    elif isinstance(value, list):
        for item in value:
            yield from _numeric_leaves(item, path + "[]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield path


def test_a_served_v3_payload_carries_no_internal_evidence_or_numbers():
    pool = exposure_snapshot([
        {**_praise(), "cue_keys": ["full_volume"],
         "machine_prediction": {"score": 0.91},
         "acoustic_feature_snapshot": {"features": {"pitch": 1.2}}},
        _rewrite(),
    ])
    document = _placed_document(parts=True)
    frame = build_service_candidate_frame(
        take_document=document, snippets=_snippets(), suggestions={},
        feedback_candidates=pool, take_index=2,
        expected_recording_id=RECORDING, served_text=SERVED)
    inventory = prepare_v3_service_inventory(
        frame=frame, take_document=document, served_text=SERVED,
        feedback_candidates=pool)
    assert inventory is not None
    served = inventory["visible_rows"]
    verbal = [row for row in served
              if row["feedback_family"] != "confident_voice"]
    assert verbal and all("rank_key" in row and "evidence" in row
                          for row in verbal)   # the leak, before the boundary

    # The serving boundary every student payload passes (the changes
    # block's last stage).
    visible = strip_internal_evidence(served)
    assert {row["id"] for row in visible} == {row["id"] for row in served}
    assert all(row["quote"] for row in visible)
    for row in visible:
        assert "rank_key" not in row
        assert not any(key.startswith("_manager_") for key in row)
        for key in ("candidate_score", "machine_prediction",
                    "acoustic_feature_snapshot", "reason_tier",
                    "detector_version", "rule_version", "selected"):
            assert key not in row
        # `evidence` is the Manager's copy here, not coordinates: dropped.
        assert "evidence" not in row
        assert list(_numeric_leaves(row)) == []


def test_a_served_rewrite_rides_its_moments_block(monkeypatch):
    # The rewrite gate (H3) is its own contract (tests/test_rewrite_gate.py);
    # here it lets the clearer version through so the serving can be read.
    monkeypatch.setattr("services.rewrite_gate.words_need_help",
                        lambda *_a, **_k: "fillers")
    monkeypatch.setattr("services.rewrite_gate.rewrite_refusal",
                        lambda *_a, **_k: None)
    pool = exposure_snapshot([_praise(), _rewrite()])
    document = _placed_document(parts=True)
    frame = build_service_candidate_frame(
        take_document=document, snippets=_snippets(), suggestions={},
        feedback_candidates=pool, take_index=2,
        expected_recording_id=RECORDING, served_text=SERVED)
    inventory = prepare_v3_service_inventory(
        frame=frame, take_document=document, served_text=SERVED,
        feedback_candidates=pool)
    assert inventory is not None
    visible = strip_internal_evidence(inventory["visible_rows"])
    by_snippet: dict[str, set] = {}
    for row in visible:
        by_snippet.setdefault(str(row.get("snippet_id")), set()).add(
            row.get("block_id"))
    rewrite = [row for row in visible
               if row["feedback_family"] == "rewrite_clarity"]
    assert rewrite, "the clearer version is served"
    # One block id per snippet: the rewrite's is its moment's, and it is set.
    assert all(rewrite_row.get("block_id") for rewrite_row in rewrite)
    assert len(by_snippet["s1a"]) == 1


def test_a_stray_mlc3_service_block_never_reaches_the_client():
    """The retired MLC-3 exercise context (L8, contract 66). The server no
    longer builds it; if a stored row still held one, the boundary drops it."""
    stray = {"membership_id": "m-1", "n1_candidate_set_id": "n-1",
             "authorization_check_id": "a-1"}
    [row] = strip_internal_evidence([{**_praise(), "mlc3_service": stray}])
    assert "mlc3_service" not in row
    assert row["quote"]
