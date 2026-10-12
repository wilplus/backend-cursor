"""Verbal lanes under V3: one eligibility rule, in the Take's own words.

N48.1 (Wave 1, E1), founder-approved 2026-10-05.

  * TWO COORDINATE SYSTEMS. A verbal row's `span` addresses the SERVED Ideal
    Text; V3's blocks address the Take's TRANSCRIPT document. From Take 2 on
    they differ (an unspoken Slide keeps its older Paragraph in the served
    text), so V3 compared numbers from two documents. The row is now mapped
    into the transcript, or excluded as `document_span_unmapped`.
  * ONE PREDICATE. `ensure_required_families` counted any row of a family as
    covering its lane, so a row V3 then excluded suppressed the fallback.
    Both readers now ask `verbal_exclusion`.
  * DETECTOR PRAISE CARRIES ITS EVIDENCE. Structural and impeccable praise
    are stamped with what their detector computed and a code-side version.
  * A ROW FROM ANOTHER TAKE NO LONGER ABORTS A SERVICE LANE.
"""
from __future__ import annotations

from services.ideal_text_parts import with_served_spans
from services.take_feedback_manager import (
    TakeDocumentMap,
    strip_internal_evidence,
    verbal_exclusion,
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


def _lane(frame, family):
    return frame["verbal_lanes"][family]


# ── Task 0: the coordinate systems differ, and the rows are mapped ─────────


# ── Task 1: one predicate decides the fallback ─────────────────────────────

def _map() -> TakeDocumentMap:
    return TakeDocumentMap.for_document(_placed_document(), SERVED,
                                        take_id=TAKE)


# ── Task 2: detector praise carries what its detector computed ─────────────

def _tracked(suggestion: dict, sid: str = "s2b") -> list[dict]:
    pieces = relocate_pieces(SERVED, DOC["pieces"], paragraph_fallback=True,
                             slide_regions={})
    return build_tracked_changes(SERVED, pieces, {sid: suggestion})


# ── The service lane: one unplaceable row no longer silences the lane ──────


def test_the_read_path_builds_its_map_from_the_review_take():
    """`_feedback_set_and_fallbacks` hands the fallback decision a map of the
    review Take placed on the served text -- the same relocation V3's
    binding uses -- and a failure degrades to no map (both fallbacks)."""
    from services.ideal_text_changes import _ChangesRun

    run = _ChangesRun.__new__(_ChangesRun)
    run.review_doc, run.served_text = DOC, SERVED
    run.slide_regions, run.arm_sid, run.arc_id = {}, TAKE, "arc-1"
    document_map = run._take_document_map()
    assert document_map is not None
    praise = _praise()
    assert verbal_exclusion(praise, document_map) == (
        None, (praise["span"]["start"] - SHIFT, praise["span"]["end"] - SHIFT))

    run.served_text = object()   # not text: relocation cannot run
    broken = run._take_document_map()
    assert broken is None or verbal_exclusion(praise, broken)[0] is not None


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
    from services.ideal_text_changes import _ChangesRun
    from services.take_feedback_manager import exposure_snapshot

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

    run = _ChangesRun.__new__(_ChangesRun)
    run.changes, run.styles = served, []
    run.sel, run.learning_presentations, run.v3_failure = {}, {}, ""
    payload = run._finish()
    assert payload["changes"]
    for row in payload["changes"]:
        assert "rank_key" not in row
        assert not any(key.startswith("_manager_") for key in row)
        for key in ("candidate_score", "machine_prediction",
                    "acoustic_feature_snapshot", "reason_tier",
                    "detector_version", "rule_version", "selected"):
            assert key not in row
        # `evidence` is the Manager's copy here, not coordinates: dropped.
        assert "evidence" not in row
        assert list(_numeric_leaves(row)) == []


def test_a_stray_mlc3_service_block_never_reaches_the_client():
    """The retired MLC-3 exercise context (L8, contract 66). The server no
    longer builds it; if a stored row still held one, the boundary drops it."""
    stray = {"membership_id": "m-1", "n1_candidate_set_id": "n-1",
             "authorization_check_id": "a-1"}
    [row] = strip_internal_evidence([{**_praise(), "mlc3_service": stray}])
    assert "mlc3_service" not in row
    assert row["quote"]
