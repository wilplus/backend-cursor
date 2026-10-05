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
    ensure_required_families,
    strip_internal_evidence,
    verbal_exclusion,
)
from services.take_feedback_policy_v3 import (
    build_service_candidate_frame,
    build_shadow_frame,
)
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory
from services.tracked_changes import (
    DELIVERY_IMPECCABLE_DETECTOR_VERSION,
    STRUCTURAL_DEVICE_DETECTOR_VERSION,
    build_tracked_changes,
)
from services.transcript_document import relocate_pieces

TAKE = "take-2"
OLD_TAKE = "take-1"
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


def _block_of(frame, slide):
    return next(b for b in frame["blocks"] if b["slide_index"] == slide)


# ── Task 0: the coordinate systems differ, and the rows are mapped ─────────

class TestTheTwoDocumentsDiffer:
    def test_take_two_served_text_is_not_the_take_document(self):
        # The evidence the adjacent risk asked for: same words, other offsets.
        assert SERVED != DOC["text"]
        placed = _placed_document()
        for piece in placed["pieces"]:
            assert piece["served_start"] == piece["start"] + SHIFT
            assert SERVED[piece["served_start"]:piece["served_end"]] == \
                DOC["text"][piece["start"]:piece["end"]]

    def test_a_served_span_read_as_a_transcript_span_misses_its_block(self):
        # What the old comparison did: the praise on Slide 2's last words,
        # read as transcript offsets, runs past the Take document -- the row
        # was dropped as out of bounds although its words were spoken.
        praise = _praise()
        assert praise["span"]["end"] > len(DOC["text"])
        # And the rewrite on Slide 1's first words, read as numbers, is not
        # inside Slide 1's block and addresses other words entirely.
        frame = _frame([])
        slide_1 = _block_of(frame, 1)
        rewrite = _rewrite()
        start, end = rewrite["span"]["start"], rewrite["span"]["end"]
        assert not (slide_1["start"] <= start and end <= slide_1["end"])
        assert DOC["text"][start:end] != rewrite["quote"]

    def test_verbal_rows_are_mapped_into_the_take_document(self):
        frame = _frame([_praise(), _rewrite()])
        praise = _lane(frame, "great_formulation")["candidates"][0]
        rewrite = _lane(frame, "rewrite_clarity")["candidates"][0]
        assert praise["eligibility"] == "eligible"
        assert rewrite["eligibility"] == "eligible"
        for item in (praise, rewrite):
            span, target = item["document_span"], item["target_span"]
            assert span["start"] == target["start"] - SHIFT
            assert DOC["text"][span["start"]:span["end"]] == \
                SERVED[target["start"]:target["end"]]

    def test_each_note_anchors_to_the_block_its_words_were_spoken_in(self):
        frame = _frame([_praise(), _rewrite()])
        confident, weak = _block_of(frame, 2), _block_of(frame, 1)
        assert _lane(frame, "great_formulation")["anchors"] == [
            {"block_id": confident["block_id"],
             "candidate_id": "structural-praise"}]
        assert _lane(frame, "rewrite_clarity")["anchors"] == [
            {"block_id": weak["block_id"],
             "candidate_id": "structural-repair"}]

    def test_words_on_an_unspoken_slide_map_nowhere(self):
        # The concision fallback picks the shortest sentence in the WHOLE
        # served text; here that is Slide 0, which Take 2 never spoke. It
        # names a Take-2 snippet, but the words are Take 1's.
        fallback = _row("praise-review:x", "great_formulation", OLD_SLIDE_0,
                        snippet="s1a", rule_version="fallback-v1",
                        _manager_evidence={"fallback": True,
                                           "specificity": 1})
        frame = _frame([fallback])
        item = _lane(frame, "great_formulation")["candidates"][0]
        assert item["eligibility"] == "excluded"
        assert item["exclusion_reason"] == "document_span_unmapped"
        assert item["document_span"] is None
        assert _lane(frame, "great_formulation")["anchors"] == []

    def test_words_edited_away_from_the_transcript_map_nowhere(self):
        served = SERVED.replace("are clear", "are very clear")
        document = with_served_spans(DOC, served_text=served,
                                     slide_regions={})
        at = served.index("The results so far are very clear")
        row = {**_praise(), "snippet_id": "s2a",
               "span": {"start": at, "end": at + 33}}
        frame = _frame([row], served=served, document=document)
        item = _lane(frame, "great_formulation")["candidates"][0]
        assert item["exclusion_reason"] == "document_span_unmapped"

    def test_identical_documents_map_one_to_one(self):
        # Take 1's usual shape: the Ideal Text is the transcript.
        start = DOC["text"].index(SPOKEN[3][2])
        row = {**_praise(), "span": {"start": start,
                                     "end": start + len(SPOKEN[3][2])}}
        frame = _frame([row], served=DOC["text"], document=DOC)
        item = _lane(frame, "great_formulation")["candidates"][0]
        assert item["eligibility"] == "eligible"
        assert item["document_span"] == item["target_span"]

    def test_without_the_served_text_nothing_is_proven(self):
        frame = _frame([_praise()], served=None)
        item = _lane(frame, "great_formulation")["candidates"][0]
        assert item["exclusion_reason"] == "document_span_unmapped"


# ── Task 1: one predicate decides the fallback ─────────────────────────────

def _map() -> TakeDocumentMap:
    return TakeDocumentMap.for_document(_placed_document(), SERVED,
                                        take_id=TAKE)


def _ensure(rows):
    return ensure_required_families(
        SERVED, rows, take_session_id=TAKE, snippet_id="s1a",
        document_map=_map())


def _fallbacks(rows):
    return [row for row in rows
            if (row.get("_manager_evidence") or {}).get("fallback")]


class TestOnePredicateDecidesTheFallback:
    def test_an_eligible_row_covers_its_lane(self):
        out = _ensure([_praise(), _rewrite()])
        assert _fallbacks(out) == []

    def test_detector_praise_without_evidence_no_longer_hides_the_fallback(self):
        bare = {key: value for key, value in _praise().items()
                if key not in ("_manager_evidence", "detector_version")}
        out = _ensure([bare, _rewrite()])
        assert [row["feedback_family"] for row in _fallbacks(out)] == [
            "great_formulation"]

    def test_an_llm_rewrite_no_longer_hides_the_fallback_rewrite(self):
        llm = _row("s1b", "rewrite_clarity", SPOKEN[1][2], snippet="s1b",
                   kind="replace", source="wording",
                   proposed_text="We give every learner one short daily task.")
        out = _ensure([llm, _praise()])
        assert [row["feedback_family"] for row in _fallbacks(out)] == [
            "rewrite_clarity"]

    def test_a_row_from_another_take_does_not_count(self):
        # A Take-1 praise still in the text, fully evidenced and versioned.
        old = _row("t1-praise", "great_formulation", OLD_SLIDE_0,
                   snippet="t1-s0", take=OLD_TAKE, source="structural",
                   detector_version=STRUCTURAL_DEVICE_DETECTOR_VERSION,
                   _manager_evidence={"detector": "structural_device"})
        assert verbal_exclusion(old, _map())[0] == "missing_snippet_lineage"
        same_snippet_other_take = {**_praise(), "take_session_id": OLD_TAKE}
        assert verbal_exclusion(same_snippet_other_take, _map())[0] == \
            "candidate_take_mismatch"
        out = _ensure([old, same_snippet_other_take, _rewrite()])
        assert [row["feedback_family"] for row in _fallbacks(out)] == [
            "great_formulation"]

    def test_without_a_map_both_fallbacks_are_offered(self):
        out = ensure_required_families(
            SERVED, [_praise(), _rewrite()], take_session_id=TAKE,
            snippet_id="s1a")
        assert sorted(row["feedback_family"] for row in _fallbacks(out)) == [
            "great_formulation", "rewrite_clarity"]

    def test_the_fallback_decision_and_v3_agree_row_by_row(self):
        # ONE rule: whatever V3 calls eligible is exactly what covers a lane.
        bare = {key: value for key, value in _praise("bare").items()
                if key != "_manager_evidence"}
        rows = [_praise(), _rewrite(), bare,
                {**_praise("other-take"), "take_session_id": OLD_TAKE}]
        frame = _frame(rows)
        eligible = {
            item["candidate_id"]
            for family in ("rewrite_clarity", "great_formulation")
            for item in _lane(frame, family)["candidates"]
            if item["eligibility"] == "eligible"
        }
        assert eligible == {
            row["id"] for row in rows
            if verbal_exclusion(row, _map())[0] is None
        } == {"structural-praise", "structural-repair"}


# ── Task 2: detector praise carries what its detector computed ─────────────

def _tracked(suggestion: dict, sid: str = "s2b") -> list[dict]:
    pieces = relocate_pieces(SERVED, DOC["pieces"], paragraph_fallback=True,
                             slide_regions={})
    return build_tracked_changes(SERVED, pieces, {sid: suggestion})


class TestDetectorPraiseEvidence:
    def test_structural_praise_is_stamped_with_its_detector(self):
        [row] = _tracked({"kind": "structure", "trigger": "contrast",
                          "why": "reading scores rose"})
        assert row["source"] == "structural"
        assert row["detector_version"] == STRUCTURAL_DEVICE_DETECTOR_VERSION
        assert row["_manager_evidence"] == {
            "detector": "structural_device", "fallback": False,
            "lexical_words_invented": 0}

    def test_impeccable_praise_counts_the_cues_that_earned_it(self):
        [row] = _tracked({"kind": "delivery", "trigger": "impeccable",
                          "cue_keys": ["full_volume", "landed_ending",
                                       "not-a-cue"]})
        assert row["detector_version"] == DELIVERY_IMPECCABLE_DETECTOR_VERSION
        assert row["_manager_evidence"] == {
            "detector": "delivery_impeccable", "cue_count": 2}

    def test_other_advice_carries_nothing(self):
        [issue] = _tracked({"kind": "delivery", "trigger": "rushed"})
        [unknown] = _tracked({"kind": "structure", "trigger": "metaphor"})
        for row in (issue, unknown):
            assert "_manager_evidence" not in row
            assert "detector_version" not in row

    def test_rewrites_stay_without_evidence(self):
        # LLM rewrites are NOT made servable here (a separate decision).
        [row] = _tracked({"kind": "replace", "trigger": "polish",
                          "replacement_text": "Scores rose this spring."})
        assert "_manager_evidence" not in row

    def test_the_evidence_never_rides_the_payload(self):
        [row] = _tracked({"kind": "structure", "trigger": "contrast"})
        [visible] = strip_internal_evidence([row])
        assert "_manager_evidence" not in visible

    def test_detector_praise_now_competes_and_is_served(self):
        from services.intervention_candidates import feedback_family_of
        from services.take_feedback_manager import exposure_snapshot
        [row] = _tracked({"kind": "structure", "trigger": "contrast"})
        row["feedback_family"] = feedback_family_of(row)
        assert row["feedback_family"] == "great_formulation"
        pool = exposure_snapshot(ensure_required_families(
            SERVED, [row, _rewrite()], take_session_id=TAKE,
            snippet_id="s1a", document_map=_map()))
        # The detector praise covers its lane: no fallback praise added.
        assert _fallbacks(pool) == []
        frame = _frame(pool)
        assert _lane(frame, "great_formulation")["selected_candidate_ids"] \
            == ["s2b"]


# ── The service lane: one unplaceable row no longer silences the lane ──────

def test_a_row_from_another_take_does_not_abort_the_service_lane():
    prior_take = _row("prior:s1a", "rewrite_clarity", SPOKEN[0][2],
                      snippet="t1-s1", take=OLD_TAKE, kind="replace",
                      proposed_text="Our first idea was simpler.")
    rows = [prior_take, _rewrite(), _praise()]
    document = _placed_document(parts=True)
    frame = build_service_candidate_frame(
        take_document=document, snippets=_snippets(), suggestions={},
        feedback_candidates=rows, take_index=2,
        expected_recording_id=RECORDING, served_text=SERVED)
    detail: list[str] = []
    inventory = prepare_v3_service_inventory(
        frame=frame, take_document=document, served_text=SERVED,
        feedback_candidates=rows, detail=detail)
    assert inventory is not None
    visible = {(row["feedback_family"], row["id"])
               for row in inventory["visible_rows"]}
    assert ("rewrite_clarity", "structural-repair") in visible
    assert ("great_formulation", "structural-praise") in visible
    assert ("rewrite_clarity", "prior:s1a") not in visible
    assert "verbal_candidate_unplaced:rewrite_clarity:1" in detail
    assert not any(d.startswith("verbal_lane_excluded") for d in detail)


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


def test_where_the_documents_agree_the_anchors_are_exactly_the_old_ones():
    """FROZEN TAKES (task 3). Where the served text IS the Take's transcript
    (Take 1's usual shape) the map is the identity, so every verbal note
    anchors exactly where the served-span comparison put it before N48.1 and
    a frozen set rebuilds the same identities."""
    from services.take_feedback_policy_v3 import (
        _anchored_notes, _blocks_read,
    )
    text = DOC["text"]

    def at(words, row):
        start = text.index(words)
        return {**row, "span": {"start": start, "end": start + len(words)}}

    rows = [at(SPOKEN[3][2], _praise()), at(SPOKEN[0][2], _rewrite()),
            at("The results so far are clear", _praise("second-praise"))]
    frame = _frame(rows, served=text, document=DOC)
    for family, confident in (("great_formulation", True),
                              ("rewrite_clarity", False)):
        lane = _lane(frame, family)
        # Equal evidence within each lane here, so the ranking is position.
        ranked = sorted(
            (item for item in lane["candidates"]
             if item["eligibility"] == "eligible"),
            key=lambda item: item["target_span"]["start"])
        assert all(item["document_span"] == item["target_span"]
                   for item in ranked)
        old_rule = [{**item, "document_span": item["target_span"]}
                    for item in ranked]
        assert lane["anchors"] == _anchored_notes(
            old_rule, _blocks_read(frame["blocks"], confident=confident))
