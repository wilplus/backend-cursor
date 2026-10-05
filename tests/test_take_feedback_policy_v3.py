from services.take_feedback_policy_v3 import (
    FRAME_SCHEMA_VERSION,
    POLICY_VERSION,
    build_shadow_frame,
    dark_enabled,
)
from config import Config
from pathlib import Path
from services.db import DatabaseService
from tests.fakes import FakeSupabaseClient


def _piece(index, slide, words, score):
    text = " ".join(f"word{index}x{n}" for n in range(words))
    return {
        "snippet_id": f"snippet-{index}",
        "take_session_id": "take-2",
        "slide_index": slide,
        "start": index * 1000,
        "end": index * 1000 + len(text),
        "text": text,
        "recording_id": "recording-1",
        "start_offset_ms": index * 5000,
        "duration_ms": 5000,
        "score": score,
    }


def _frame(take_index=2):
    pieces = [
        _piece(0, 0, 25, -0.4),
        _piece(1, 0, 25, 0.2),
        _piece(2, 0, 25, 0.7),
        _piece(3, 1, 35, -0.5),
        _piece(4, 1, 35, -0.2),
    ]
    snippets = [{
        "id": piece["snippet_id"],
        "session_id": "take-2",
        "recording_id": "recording-1",
        "start_offset_ms": piece["start_offset_ms"],
        "duration_ms": piece["duration_ms"],
        "metrics": {
            "voice_confidence": {
                "version": "voice-confidence-universal-v3",
                "score": piece["score"],
            },
        },
    } for piece in pieces]
    suggestions = {
        "snippet-2": {"trigger": "confident", "cue_keys": ["full_volume"]},
    }
    feedback = [
        {
            "id": "weak-rewrite",
            "feedback_family": "rewrite_clarity",
            "snippet_id": "snippet-0",
            "take_session_id": "take-2",
            "span": {"start": 0, "end": 20},
            "quote": "a",
            "proposed_text": "b",
            "rule_version": "rewrite-generator-v1",
            "_manager_evidence": {"specificity": 1, "fallback": True},
        },
        {
            "id": "best-rewrite",
            "feedback_family": "rewrite_clarity",
            "snippet_id": "snippet-4",
            "take_session_id": "take-2",
            "span": {"start": 4050, "end": 4090},
            "quote": "a",
            "proposed_text": "b",
            "model_version": "rewrite-model-v1",
            "_manager_evidence": {"specificity": 5, "fallback": False},
        },
        {
            "id": "best-praise",
            "feedback_family": "great_formulation",
            "snippet_id": "snippet-2",
            "take_session_id": "take-2",
            "span": {"start": 100, "end": 130},
            "prompt_version": "praise-prompt-v1",
            "_manager_evidence": {"specificity": 4, "fallback": False},
        },
    ]
    return build_shadow_frame(
        take_document={
            "take_session_id": "take-2",
            "text": "x" * 5000,
            "pieces": pieces,
        },
        snippets=snippets,
        suggestions=suggestions,
        feedback_candidates=feedback,
        take_index=take_index,
        expected_recording_id="recording-1",
        # The Ideal Text IS this Take's transcript, so a served span is a
        # transcript span 1:1 (N48.1, Wave 1: verbal spans are mapped).
        served_text="x" * 5000,
    )


def test_one_relative_best_candidate_per_slide_bounded_75_word_block():
    frame = _frame()
    assert frame["policy_version"] == POLICY_VERSION
    assert frame["frame_schema_version"] == FRAME_SCHEMA_VERSION
    assert [block["word_count"] for block in frame["blocks"]] == [75, 70]
    assert len(frame["selected_confidence"]) == 2
    assert frame["blocks"][0]["selected_candidate_id"].endswith("snippet-2")
    # The second slide is negative in absolute terms, but its relatively best
    # valid clip still wins with honest tentative language.
    assert frame["blocks"][1]["selected_candidate_id"].endswith("snippet-4")
    assert frame["blocks"][1]["selection_reason"] == "best_available_tentative"
    assert all(
        candidate["clip_identity"]["recording_id"] == "recording-1"
        for block in frame["blocks"]
        for candidate in block["confidence_candidates"]
    )


def test_both_verbal_lanes_run_on_take_one():
    """REVERSED 2026-09-18 (founder — contract 24b). This test previously
    asserted `enabled is False` on Take 1 and that both lanes selected nothing.

    The old rule made the first Take the one Take whose bookmarks lead
    nowhere — the worst possible place in the product for that, because it is
    the only Take every user definitely sees. Rewritten rather than deleted so
    the reversal is legible in this file's history.
    """
    first = _frame(take_index=1)
    assert first["verbal_lanes"]["enabled"] is True
    assert first["verbal_lanes"]["rewrite_clarity"]["selected_candidate_ids"] == [
        "best-rewrite",
    ]


def test_the_rewrite_anchors_to_every_block_read_weak():
    """THE CAPS ARE LIFTED (founder 2026-09-29, evening; contract 24f). Until
    then the rewrite lane kept one rewrite for the whole Take, because a
    rewrite asserts a finding and can be wrong. Now each block the machine
    reads weak carries its best defensible rewrite, and a block read
    confident carries none: its follow-up is praise."""
    frame = _frame(take_index=2)
    lane = frame["verbal_lanes"]["rewrite_clarity"]
    assert lane["budget"] == "one_per_block"
    assert lane["selection_scope"] == "anchored_to_blocks_read_weak"
    weak, confident = frame["blocks"][1], frame["blocks"][0]
    assert weak["delivery_band"] == "delivery_signal_mid_low"
    assert confident["delivery_band"] == "delivery_signal_high"
    assert lane["anchors"] == [
        {"block_id": weak["block_id"], "candidate_id": "best-rewrite"},
    ]
    assert lane["selected_candidate_ids"] == ["best-rewrite"]
    # The fallback rewrite sits inside the confident block and is never
    # selected there, however it ranks.
    assert "weak-rewrite" not in lane["selected_candidate_ids"]


def test_praise_anchors_to_every_block_read_confident():
    frame = _frame(take_index=2)
    lane = frame["verbal_lanes"]["great_formulation"]
    assert lane["budget"] == "one_per_block"
    assert lane["selection_scope"] == "anchored_to_blocks_read_confident"
    assert lane["anchors"] == [
        {"block_id": frame["blocks"][0]["block_id"],
         "candidate_id": "best-praise"},
    ]
    # Every anchor names the block it belongs to — praise never floats free of
    # a Slide (contract 24f).
    block_ids = {block["block_id"] for block in frame["blocks"]}
    for anchor in lane["anchors"]:
        assert anchor["block_id"] in block_ids
        assert anchor["candidate_id"] in lane["selected_candidate_ids"]


def test_the_green_mark_stays_on_the_top_two_and_no_longer_places_praise():
    """24g keeps the two most Confident items green; 24f no longer ties
    praise to them."""
    frame = _frame(take_index=2)
    assert [b["most_confident"] for b in frame["blocks"]] == [True, True]
    praise = frame["verbal_lanes"]["great_formulation"]["anchors"]
    assert {a["block_id"] for a in praise} == {frame["blocks"][0]["block_id"]}


def test_shadow_is_not_delivery_exposure_or_dataset_input_and_hash_is_stable():
    first = _frame()
    second = _frame()
    assert first["frame_hash"] == second["frame_hash"]
    assert first["serves_user_feedback"] is False
    assert first["dataset_eligible"] is False
    assert first["exposure_semantics"]["shadow_computation_is_exposure"] is False
    serialized = str(first)
    assert "word0x0" not in serialized  # no transcript text in the shadow ledger
    versions = first["implementation_versions"]
    assert versions["confidence_detector_version"] == "voice-confidence-universal-v3"
    assert versions["acoustic_feature_schema_version"]
    assert versions["manager_rules_version"]
    assert versions["manager_evidence_schema_version"]
    assert len(versions["source_code_sha256"]) == 64


def test_exact_clip_lineage_mismatch_is_retained_as_a_typed_exclusion():
    frame = _frame()
    assert frame is not None
    first = frame["blocks"][0]["confidence_candidates"][0]
    assert first["eligibility"] == "eligible"

    pieces = [_piece(0, 0, 75, 0.4)]
    snippets = [{
        "id": "snippet-0",
        "session_id": "take-2",
        "recording_id": "another-recording",
        "start_offset_ms": 0,
        "duration_ms": 5000,
        "metrics": {},
    }]
    invalid = build_shadow_frame(
        take_document={
            "take_session_id": "take-2",
            "text": "x" * 100,
            "pieces": pieces,
        },
        snippets=snippets,
        suggestions={},
        feedback_candidates=[],
        take_index=1,
        expected_recording_id="recording-1",
    )
    assert invalid is not None
    candidate = invalid["blocks"][0]["confidence_candidates"][0]
    assert candidate["eligibility"] == "excluded"
    assert candidate["exclusion_reason"] == "recording_identity_mismatch"
    assert invalid["blocks"][0]["selected_candidate_id"] is None


def test_old_detector_artifact_is_excluded_not_ranked_as_missing_evidence():
    pieces = [_piece(0, 0, 75, 0.9), _piece(1, 0, 20, 0.1)]
    snippets = []
    for piece, version in zip(
        pieces, ("voice-confidence-v2", "voice-confidence-universal-v3")
    ):
        snippets.append({
            "id": piece["snippet_id"],
            "session_id": "take-2",
            "recording_id": "recording-1",
            "start_offset_ms": piece["start_offset_ms"],
            "duration_ms": piece["duration_ms"],
            "metrics": {"voice_confidence": {
                "version": version, "score": piece["score"],
            }},
        })
    frame = build_shadow_frame(
        take_document={
            "take_session_id": "take-2", "text": "x" * 100,
            "pieces": pieces,
        },
        snippets=snippets,
        suggestions={}, feedback_candidates=[], take_index=1,
        expected_recording_id="recording-1",
    )
    assert frame is not None
    candidates = frame["blocks"][0]["confidence_candidates"]
    legacy = next(row for row in candidates if row["snippet_id"] == "snippet-0")
    current = next(row for row in candidates if row["snippet_id"] == "snippet-1")
    assert legacy["eligibility"] == "excluded"
    assert legacy["exclusion_reason"] == "incompatible_detector_version"
    assert legacy["machine_version"] == "voice-confidence-v2"
    assert frame["blocks"][0]["selected_candidate_id"] == current["candidate_id"]


def test_invalid_rewrite_and_praise_candidates_are_frozen_not_dropped():
    pieces = [_piece(0, 0, 75, 0.4)]
    snippets = [{
        "id": "snippet-0",
        "session_id": "take-2",
        "recording_id": "recording-1",
        "start_offset_ms": 0,
        "duration_ms": 5000,
        "metrics": {},
    }]
    feedback = [
        {
            "id": "invalid-rewrite",
            "feedback_family": "rewrite_clarity",
            "snippet_id": "snippet-0",
            "take_session_id": "take-2",
            "span": {"start": 80, "end": 20},
            "rule_version": "rewrite-v1",
            "_manager_evidence": {"specificity": 2},
        },
        {
            "id": "invalid-praise",
            "feedback_family": "great_formulation",
            "snippet_id": "snippet-0",
            "take_session_id": "take-2",
            "span": {"start": 1, "end": 20},
            "_manager_evidence": {"specificity": 2},
        },
    ]
    frame = build_shadow_frame(
        take_document={
            "take_session_id": "take-2",
            "text": "x" * 100,
            "pieces": pieces,
        },
        snippets=snippets,
        suggestions={},
        feedback_candidates=feedback,
        take_index=2,
        expected_recording_id="recording-1",
    )
    assert frame is not None
    rewrite = frame["verbal_lanes"]["rewrite_clarity"]["candidates"][0]
    praise = frame["verbal_lanes"]["great_formulation"]["candidates"][0]
    assert rewrite["exclusion_reason"] == "invalid_document_span"
    assert praise["exclusion_reason"] == "missing_suggestion_generator_version"
    assert {row["candidate_id"] for row in frame["excluded_candidates"]} >= {
        "invalid-rewrite", "invalid-praise",
    }


def test_dark_activation_is_fail_closed_and_founder_exact(monkeypatch):
    monkeypatch.setattr(Config, "TAKE_FEEDBACK_POLICY_V3_SHADOW_WRITE_MODE", "dark")
    monkeypatch.setattr(Config, "TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID", "founder")
    assert dark_enabled("founder") is True
    assert dark_enabled("someone-else") is False
    monkeypatch.setattr(Config, "TAKE_FEEDBACK_POLICY_V3_SHADOW_WRITE_MODE", "enabled")
    assert dark_enabled("founder") is False

# ── merged from tests/test_take_feedback_policy_v3_integration.py (audit Q-T9) ──

ROUTE = Path("services/ideal_text_changes.py").read_text()
LEGACY_MIGRATION = Path("migrations/add_take_feedback_policy_v3_shadow.sql").read_text()
MIGRATION = Path(
    "migrations/add_take_feedback_policy_universal_v3_transition.sql"
).read_text()


def test_shadow_is_wired_but_cannot_become_the_serving_path():
    assert "dark_enabled(_v3_principal_id)" in ROUTE
    assert "record_take_feedback_policy_v3_shadow" in ROUTE
    assert "serves_user_feedback" in MIGRATION
    assert "CHECK (rendered_exposure_id IS NULL)" in LEGACY_MIGRATION
    assert "CHECK (dataset_eligible = FALSE)" in LEGACY_MIGRATION
    assert "acquisition_principal_id" in MIGRATION
    assert "take_row.owner_principal_id IS DISTINCT FROM" in MIGRATION
    assert "take_row.recording_1_id IS DISTINCT FROM p_recording_id" in MIGRATION
    assert "LEFT JOIN public.snippets" in MIGRATION
    assert "GRANT SELECT ON TABLE" in MIGRATION
    assert "GRANT ALL ON TABLE" not in LEGACY_MIGRATION
    assert "incompatible_detector_version" in MIGRATION
    assert "voice-confidence-universal-v3" in MIGRATION
    assert "AND NULLIF(block ->> 'selected_candidate_id', '') IS NULL" in MIGRATION


def test_database_adapter_uses_the_service_only_atomic_rpc():
    client = FakeSupabaseClient(rpc_rows={
        "record_take_feedback_policy_v3_shadow_v3": [{
            "outcome": "stored",
            "frame_hash": "a" * 64,
        }],
    })
    database = DatabaseService.__new__(DatabaseService)
    database.client = client
    result = database.record_take_feedback_policy_v3_shadow(
        arc_id="arc",
        take_session_id="11111111-1111-4111-8111-111111111111",
        recording_id="44444444-4444-4444-8444-444444444444",
        acquisition_principal_id="33333333-3333-4333-8333-333333333333",
        owner_user_id="22222222-2222-4222-8222-222222222222",
        take_index=2,
        policy_version="take-feedback-policy-v3-universal-dark-v3",
        frame={"serves_user_feedback": False, "dataset_eligible": False},
        frame_hash="a" * 64,
    )
    assert result["outcome"] == "stored"
    assert client.tables == {}
    assert "record_take_feedback_policy_v3_shadow_v3" in client.rpcs
    payload = client.rpcs["record_take_feedback_policy_v3_shadow_v3"].payload
    assert payload["p_recording_id"] == (
        "44444444-4444-4444-8444-444444444444"
    )


# ── the coverage ladder (founder 2026-09-18, contract 24c / Appendix H.13.1) ──

def test_the_coverage_floor_climbs_then_holds_at_one_hundred():
    from services.take_feedback_policy_v3 import coverage_floor

    assert coverage_floor(1) == 0.70
    assert coverage_floor(2) == 0.80
    assert coverage_floor(3) == 1.00
    # "3 and after" — a tenth Take is not a relaxation.
    assert coverage_floor(10) == 1.00


def test_junk_take_index_holds_the_strictest_floor():
    """Fail toward the strict end: an unreadable Take index must not silently
    buy a 70% floor."""
    from services.take_feedback_policy_v3 import coverage_floor

    for value in (None, "2", True, 0, -1):
        assert coverage_floor(value) == 1.00, repr(value)


def _blk(slide_index, selected, reason="no_exact_clip_lineage_candidate"):
    return {
        "slide_index": slide_index,
        "selected_candidate_id": selected,
        "selection_reason": reason if not selected else "relatively_strongest_measured",
    }


def test_the_denominator_is_blocks_not_slides():
    """THE POINT OF THE RULE. Slides that never formed a block are absent from
    `blocks` entirely, so they cannot appear in the denominator — which is what
    makes 100% reachable instead of capped by however many Slides were silent
    or too short to partition."""
    from services.take_feedback_policy_v3 import _slide_coverage

    # Ten-slide deck, only four Slides ever produced a block.
    blocks = [_blk(1, "a"), _blk(2, "b"), _blk(5, "c"), _blk(9, "d")]
    coverage = _slide_coverage(blocks, 3)

    assert coverage["assessable_slides"] == 4
    assert coverage["covered_slides"] == 4
    assert coverage["ratio"] == 1.0
    assert coverage["meets_floor"] is True


def test_an_uncovered_slide_carries_the_reason_it_was_missed():
    """A shortfall is a defect to investigate, not a licence to pad (24d), and
    the reason strings are the only thing that makes it diagnosable."""
    from services.take_feedback_policy_v3 import _slide_coverage

    blocks = [
        _blk(1, "a"),
        _blk(2, None, "no_exact_clip_lineage_candidate"),
        _blk(2, None, "incompatible_detector_version"),
        _blk(3, None, "no_exact_clip_lineage_candidate"),
    ]
    coverage = _slide_coverage(blocks, 1)

    assert coverage["covered_slides"] == 1
    assert coverage["assessable_slides"] == 3
    assert coverage["meets_floor"] is False
    missed = {row["slide_index"]: row for row in coverage["uncovered"]}
    assert set(missed) == {2, 3}
    # Both distinct reasons on slide 2 survive, de-duplicated and ordered.
    assert missed[2]["reasons"] == [
        "incompatible_detector_version", "no_exact_clip_lineage_candidate",
    ]
    assert missed[2]["block_count"] == 2


def test_one_covered_block_covers_its_slide():
    """Coverage counts Slides, not blocks: a long Slide partitioned into four
    blocks is covered once any of them selects."""
    from services.take_feedback_policy_v3 import _slide_coverage

    blocks = [_blk(4, None), _blk(4, None), _blk(4, "c"), _blk(4, None)]
    coverage = _slide_coverage(blocks, 3)

    assert coverage["assessable_slides"] == 1
    assert coverage["ratio"] == 1.0


def test_the_five_slide_failure_is_measured_as_a_failure():
    """The take that started this: five assessable Slides, one bookmark. Under
    relative-best that should be near impossible, and the ladder must report it
    as a flat miss rather than a judgement call."""
    from services.take_feedback_policy_v3 import _slide_coverage

    blocks = [_blk(i, "a" if i == 1 else None) for i in range(1, 6)]
    coverage = _slide_coverage(blocks, 1)

    assert coverage["ratio"] == 0.2
    assert coverage["required_floor"] == 0.70
    assert coverage["meets_floor"] is False
    assert len(coverage["uncovered"]) == 4


def test_a_document_with_no_blocks_is_not_a_coverage_failure():
    """Nothing to cover is not the same as failing to cover it; reporting 0%
    would make an empty recording look like a broken selector."""
    from services.take_feedback_policy_v3 import _slide_coverage

    coverage = _slide_coverage([], 3)
    assert coverage["assessable_slides"] == 0
    assert coverage["meets_floor"] is True


# ── one note per block, by the read (founder 2026-09-29, contract 24f) ──

def _block(block_id, start, end, selected="c1", score=0.9):
    return {
        "block_id": block_id, "slide_index": 0, "start": start, "end": end,
        "selected_candidate_id": selected,
        "confidence_candidates": [
            {"candidate_id": selected, "machine_score": score, "ordinal": 0},
        ],
    }


def _read_blocks(blocks):
    """`_practice_routing` writes the band each block was read at."""
    from services.take_feedback_policy_v3 import _practice_routing
    _practice_routing(blocks)
    return blocks


def test_the_read_splits_the_blocks_at_neutral():
    """Above neutral is read confident, neutral and below is read weak: the
    same cut `confident_voice_practice.machine_read` makes on the clip when
    the judgement lands, so the note anchored here and the follow-up the
    matrix chooses agree."""
    from services.take_feedback_policy_v3 import _blocks_read

    blocks = _read_blocks([
        _block("b-low", 0, 100, "c-low", -0.6),
        _block("b-mid-low", 100, 200, "c-ml", -0.2),
        _block("b-neutral", 200, 300, "c-n", 0.0),
        _block("b-mid-high", 300, 400, "c-mh", 0.2),
        _block("b-high", 400, 500, "c-h", 0.9),
    ])
    confident = [b["block_id"] for b in _blocks_read(blocks, confident=True)]
    weak = [b["block_id"] for b in _blocks_read(blocks, confident=False)]
    assert confident == ["b-mid-high", "b-high"]
    assert weak == ["b-low", "b-mid-low", "b-neutral"]


def test_praise_goes_to_every_confident_block_and_the_rewrite_to_every_weak_one():
    """THE CAPS ARE LIFTED (founder 2026-09-29, evening). Three blocks read
    confident carry three praise; two read weak carry two rewrites. No
    ranking among the blocks decides who gets one."""
    from services.take_feedback_policy_v3 import _anchored_notes, _blocks_read

    blocks = _read_blocks([
        _block("b-1", 0, 100, "c-1", 0.2),
        _block("b-2", 100, 200, "c-2", -0.4),
        _block("b-3", 200, 300, "c-3", 0.9),
        _block("b-4", 300, 400, "c-4", -0.1),
        _block("b-5", 400, 500, "c-5", 0.6),
    ])
    praise = [
        {"candidate_id": f"p-{n}", "document_span": {"start": s, "end": s + 40}}
        for n, s in ((1, 10), (2, 110), (3, 210), (4, 310), (5, 410))
    ]
    rewrites = [
        {"candidate_id": f"r-{n}", "document_span": {"start": s, "end": s + 40}}
        for n, s in ((1, 10), (2, 110), (3, 210), (4, 310), (5, 410))
    ]
    praised = _anchored_notes(praise, _blocks_read(blocks, confident=True))
    rewritten = _anchored_notes(rewrites, _blocks_read(blocks, confident=False))
    assert [row["candidate_id"] for row in praised] == ["p-1", "p-3", "p-5"]
    assert [row["candidate_id"] for row in rewritten] == ["r-2", "r-4"]
    # A praise inside a weak block and a rewrite inside a confident block are
    # never selected, however they rank.
    assert {"p-2", "p-4"}.isdisjoint(row["candidate_id"] for row in praised)
    assert {"r-1", "r-3", "r-5"}.isdisjoint(
        row["candidate_id"] for row in rewritten)


def test_a_block_with_no_note_inside_it_simply_gets_none():
    """The cost the founder accepted: a block read confident can carry no
    praise, and one read weak no rewrite. A note made from the nearest
    available text would be manufacturing, which L2 and contract 24d forbid."""
    from services.take_feedback_policy_v3 import _anchored_notes

    blocks = [_block("b-top", 100, 200), _block("b-two", 200, 300)]
    # Both candidates sit OUTSIDE either block.
    ranked = [
        {"candidate_id": "p-far", "document_span": {"start": 0, "end": 40}},
        {"candidate_id": "p-far2", "document_span": {"start": 400, "end": 440}},
    ]
    assert _anchored_notes(ranked, blocks) == []


def test_the_best_note_inside_a_block_wins_because_the_ranking_is_ordered():
    from services.take_feedback_policy_v3 import _anchored_notes

    blocks = [_block("b-top", 0, 500)]
    ranked = [
        {"candidate_id": "p-best", "document_span": {"start": 10, "end": 40}},
        {"candidate_id": "p-worse", "document_span": {"start": 60, "end": 90}},
    ]
    anchors = _anchored_notes(ranked, blocks)
    assert [row["candidate_id"] for row in anchors] == ["p-best"]


def test_one_note_per_block_so_a_single_block_cannot_take_two():
    from services.take_feedback_policy_v3 import _anchored_notes

    blocks = [_block("b-top", 0, 500)]
    ranked = [
        {"candidate_id": "p-one", "document_span": {"start": 10, "end": 40}},
        {"candidate_id": "p-two", "document_span": {"start": 60, "end": 90}},
    ]
    assert len(_anchored_notes(ranked, blocks)) == 1


def test_a_span_straddling_a_block_boundary_is_not_inside_it():
    """Containment, not overlap: a candidate half in the block is evidence
    about words the block does not own."""
    from services.take_feedback_policy_v3 import _anchored_notes

    blocks = [_block("b-top", 100, 200)]
    ranked = [{"candidate_id": "p", "document_span": {"start": 150, "end": 260}}]
    assert _anchored_notes(ranked, blocks) == []


def test_an_unselected_or_unread_block_never_anchors_a_note():
    """A block whose confidence item was not selected has no moment to note,
    and a block the detector could not measure is neither confident nor
    weak: a human ear settles it (35g-2)."""
    from services.take_feedback_policy_v3 import (
        _blocks_read, _top_confidence_blocks,
    )

    blocks = [{
        "block_id": "b", "slide_index": 0, "start": 0, "end": 100,
        "selected_candidate_id": None, "confidence_candidates": [],
    }]
    assert _top_confidence_blocks(blocks, 2) == []
    unread = _read_blocks([_block("u", 0, 100, "c-u", None)])
    assert unread[0]["delivery_band"] is None
    assert _blocks_read(unread, confident=True) == []
    assert _blocks_read(unread, confident=False) == []


# ── the practice threshold (founder 2026-09-18, contract 24e/24f) ──

def _rblock(block_id, score):
    return {
        "block_id": block_id, "slide_index": 0, "start": 0, "end": 10,
        "selected_candidate_id": f"c-{block_id}",
        "confidence_candidates": [
            {"candidate_id": f"c-{block_id}", "machine_score": score, "ordinal": 0},
        ],
    }


# ── 24a: an indivisible block stays whole, with a typed exception ──

def _words_piece(index, slide, words):
    return {"snippet_id": f"s{index}", "word_count": words, "slide_index": slide}


def test_a_block_in_the_normal_range_has_no_exception():
    from services.take_feedback_policy_v3 import _partition_exception

    run = [_words_piece(0, 0, 40), _words_piece(1, 0, 35)]
    assert _partition_exception(run, run) is None


def test_a_single_piece_over_ninety_words_is_indivisible_long():
    from services.take_feedback_policy_v3 import _partition_exception

    long_one = [_words_piece(0, 0, 140)]
    assert _partition_exception(long_one, long_one + [_words_piece(1, 0, 70)]) \
        == "indivisible_long"


def test_a_slide_run_under_sixty_words_is_a_short_slide_run():
    from services.take_feedback_policy_v3 import _partition_exception

    run = [_words_piece(0, 0, 20), _words_piece(1, 0, 15)]
    assert _partition_exception(run, run) == "short_slide_run"


def test_any_other_block_outside_the_range_is_named_too():
    from services.take_feedback_policy_v3 import _partition_exception

    pack = [_words_piece(0, 0, 50), _words_piece(1, 0, 50)]
    run = pack + [_words_piece(2, 0, 75)]
    assert _partition_exception(pack, run) == "closest_outside_range"


def test_the_frame_types_every_block_outside_sixty_to_ninety_words():
    """The fixture's slides partition into 75 and 70 words (no exception); a
    Slide spoken in one short piece stays whole and says why (contract 24a)."""
    from services.take_feedback_policy_v3 import (
        PARTITION_EXCEPTIONS, _semantic_blocks,
    )

    assert [b["partition_exception"] for b in _frame()["blocks"]] == [None, None]
    blocks, _ = _semantic_blocks([
        _piece(0, 0, 25, 0.1),            # Slide 0: one short piece
        _piece(1, 1, 120, 0.1),           # Slide 1: one long piece
        _piece(2, 2, 40, 0.1), _piece(3, 2, 40, 0.1),   # Slide 2: 80 words
    ])
    assert [(b["slide_index"], b["word_count"], b["partition_exception"])
            for b in blocks] == [
        (0, 25, "short_slide_run"),
        (1, 120, "indivisible_long"),
        (2, 80, None),
    ]
    assert {b["partition_exception"] for b in blocks} - {None} <= set(
        PARTITION_EXCEPTIONS)


# ── 25: an honest empty lane is typed, never merely absent ──

def test_a_lane_that_anchored_a_note_is_selected_and_names_the_blocks_without_one():
    from services.take_feedback_policy_v3 import _lane_outcome

    out = _lane_outcome(
        [{"block_id": "b1", "candidate_id": "c1"}],
        [{"block_id": "b1"}, {"block_id": "b2"}],
    )
    assert out == {
        "outcome": "selected",
        "blocks_without_note": [
            {"block_id": "b2", "reason": "no_defensible_candidate"}],
    }


def test_a_lane_with_nothing_defensible_freezes_no_defensible_candidate():
    from services.take_feedback_policy_v3 import (
        NO_DEFENSIBLE_CANDIDATE, _lane_outcome,
    )

    assert _lane_outcome([], [{"block_id": "b1"}]) == {
        "outcome": NO_DEFENSIBLE_CANDIDATE,
        "blocks_without_note": [
            {"block_id": "b1", "reason": NO_DEFENSIBLE_CANDIDATE}],
    }
    # No block read for the lane at all: still typed, nothing invented.
    assert _lane_outcome([], []) == {
        "outcome": NO_DEFENSIBLE_CANDIDATE, "blocks_without_note": []}


def test_the_frame_records_each_lane_outcome():
    lanes = _frame()["verbal_lanes"]
    assert lanes["rewrite_clarity"]["outcome"] == "selected"
    assert lanes["rewrite_clarity"]["selected_candidate_ids"] == ["best-rewrite"]
    praise = lanes["great_formulation"]
    assert praise["outcome"] in ("selected", "no_defensible_candidate")
    # Every block read for a lane is either anchored or named without a note.
    for lane in (lanes["rewrite_clarity"], praise):
        anchored = {row["block_id"] for row in lane["anchors"]}
        named = {row["block_id"] for row in lane["blocks_without_note"]}
        assert not anchored & named
        assert all(row["reason"] == "no_defensible_candidate"
                   for row in lane["blocks_without_note"])


def test_the_threshold_cuts_below_neutral():
    from services.take_feedback_policy_v3 import _practice_routing

    routing = _practice_routing([
        _rblock("high", 0.8),      # delivery_signal_high
        _rblock("mid_high", 0.2),  # delivery_signal_mid_high
        _rblock("neutral", 0.0),   # delivery_signal_neutral — NOT prompted
        _rblock("mid_low", -0.2),  # below
        _rblock("low", -0.9),      # below
    ])
    assert routing["high"]["practice_prompt"] is False
    assert routing["mid_high"]["practice_prompt"] is False
    assert routing["neutral"]["practice_prompt"] is False, (
        "neutral is AT the threshold, not below it — the cut is 'below neutral'"
    )
    assert routing["mid_low"]["practice_prompt"] is True
    assert routing["low"]["practice_prompt"] is True


def test_every_block_read_weak_carries_its_own_exercise():
    """REVERSED 2026-10-05 (audit 24f-exercise), following contract 24f as the
    founder amended it on 2026-09-29: "an exercise on any bookmark", each item
    the machine reads weak gets the library exercise matched to its own clip
    (35g-1). Until then exactly one block, the weakest below neutral, carried
    the drill, and the frame still declared that after the serve path had
    stopped following it. Read weak is the neutral band and below; a block read
    confident carries none; the prompt still cuts below neutral."""
    from services.take_feedback_policy_v3 import _practice_routing

    routing = _practice_routing([
        _rblock("a", -0.2), _rblock("b", -0.9), _rblock("c", -0.4),
        _rblock("neutral", 0.0), _rblock("mid_high", 0.2), _rblock("high", 0.8),
    ])
    carrying = [key for key, row in routing.items() if row["carries_exercise"]]
    assert carrying == ["a", "b", "c", "neutral"]
    assert [key for key, row in routing.items() if row["practice_prompt"]] == [
        "a", "b", "c"]


def test_the_frame_declares_the_exercise_rule_the_serve_path_follows():
    practice = _frame()["practice_policy"]
    assert practice["exercise_budget"] == "one_per_block_read_weak"
    assert practice["exercise_target"] == "each_block_read_weak_own_clip"
    assert practice["threshold"] == "below_neutral_delivery_band"


def test_a_take_with_nothing_below_neutral_offers_no_exercise():
    """What progress looks like: the drill disappears."""
    from services.take_feedback_policy_v3 import _practice_routing

    routing = _practice_routing([_rblock("a", 0.6), _rblock("b", 0.1)])
    assert not any(row["carries_exercise"] for row in routing.values())
    assert not any(row["practice_prompt"] for row in routing.values())


def test_an_unselected_block_is_not_routed_at_all():
    from services.take_feedback_policy_v3 import _practice_routing

    routing = _practice_routing([{
        "block_id": "b", "slide_index": 0, "start": 0, "end": 10,
        "selected_candidate_id": None, "confidence_candidates": [],
    }])
    assert routing == {}


def test_strongest_and_weakest_come_from_one_ordering():
    """Read from both ends of the same ranking, so the two can never disagree
    about a take — a separate 'weakest' rule could name a block the shared rule
    ranks above another it called stronger."""
    from services.take_feedback_policy_v3 import (
        _practice_routing, _top_confidence_blocks,
    )

    blocks = [_rblock("worst", -0.9), _rblock("best", 0.9), _rblock("mid", -0.1)]
    top = _top_confidence_blocks(blocks, 1)
    routing = _practice_routing(blocks)
    assert top[0]["block_id"] == "best"
    assert routing["best"]["carries_exercise"] is False
    assert routing["worst"]["carries_exercise"] is True


def test_the_band_stays_internal_and_the_client_gets_booleans():
    """AC-9. voice_confidence.band() says in its own docstring that the band is
    a VERDICT and must never reach a user payload, so what leaves the routing
    is two booleans plus the label for this internal frame only."""
    from services.take_feedback_policy_v3 import _practice_routing

    routing = _practice_routing([_rblock("a", -0.7)])
    assert set(routing["a"]) == {
        "delivery_band", "practice_prompt", "carries_exercise",
    }
    assert routing["a"]["practice_prompt"] is True


# ── the bookmark reaches the client (founder 2026-09-18, contract 24g) ──
#
# "There are no green bookmarks... none of that actually landed." It had not:
# the ladder was computed on the frame and dropped before the row was built, so
# the browser received no tier and every bookmark could only be one colour.


def test_the_two_most_confident_blocks_are_marked_green():
    from services.take_feedback_policy_v3 import _mark_top_confidence

    blocks = [
        _rblock("weak", -0.5), _rblock("best", 0.9),
        _rblock("second", 0.6), _rblock("middling", 0.1),
    ]
    _mark_top_confidence(blocks, 2)
    green = {b["block_id"] for b in blocks if b["most_confident"]}
    assert green == {"best", "second"}


def test_green_carries_no_position():
    """First and second render identically (24g) — a visible ordering is a
    surfaced ranking, so what lands on the block is a boolean and nothing
    else."""
    from services.take_feedback_policy_v3 import _mark_top_confidence

    blocks = [_rblock("best", 0.9), _rblock("second", 0.6)]
    _mark_top_confidence(blocks, 2)
    for block in blocks:
        assert block["most_confident"] is True
        assert "rank" not in block and "position" not in block


def test_a_beaten_block_loses_its_green():
    """Every block is written, not only the winners, so a re-run cannot leave
    a stale green on a block that has since been outranked."""
    from services.take_feedback_policy_v3 import _mark_top_confidence

    blocks = [_rblock("was_top", 0.9), _rblock("other", 0.1)]
    _mark_top_confidence(blocks, 2)
    assert blocks[0]["most_confident"] is True
    blocks.append(_rblock("newcomer", 0.95))
    blocks[0]["confidence_candidates"][0]["machine_score"] = -0.9
    _mark_top_confidence(blocks, 2)
    assert blocks[0]["most_confident"] is False


def test_the_client_row_gets_a_tier_and_never_the_band_or_the_score():
    """AC-9 at the boundary. The tier says which bookmark to DRAW; the band and
    the raw machine score stay on the internal frame and the canonical bundle
    respectively."""
    from services.take_feedback_policy_v3_service import (
        _block_presentation, _presentable,
    )

    block = {
        "block_id": "b1", "carries_exercise": False,
        "most_confident": True, "practice_prompt": False,
        "delivery_band": "delivery_signal_high",
    }
    presentation = _block_presentation(block, "b1")
    assert presentation["bookmark_tier"] == "confident"
    assert "delivery_band" not in presentation

    visible = _presentable(
        {
            "id": "c1", "quote": "words", "candidate_score": 0.87,
            "reason_tier": "not", "reason_degraded": True,
        },
        presentation,
    )
    assert visible["bookmark_tier"] == "confident"
    assert visible["practice_prompt"] is False
    assert "candidate_score" not in visible, (
        "a raw machine number in a payload is one render away from being shown"
    )
    assert "delivery_band" not in visible
    # 24j. Not a number, but "not" is a verdict about what the words did, and
    # it is the ordering input — a client holding it could reconstruct the
    # ranking. It rides the internal row; the visible copy is drawn by
    # `bookmark_tier` and `why_key`, which are signed keys.
    assert "reason_tier" not in visible
    assert "reason_degraded" not in visible


def test_the_read_decides_the_tier_not_the_old_ladder_flags():
    """Founder lock 2026-09-30 (B7): the tier is the read. The old flags of
    the rank ladder — the two most confident, the single weakest with an
    exercise — no longer place a colour; a block flagged both ways is
    whatever its read says."""
    from services.take_feedback_policy_v3_service import _block_presentation

    flagged_weak = {"carries_exercise": True, "most_confident": True,
                    "delivery_band": "delivery_signal_low"}
    assert _block_presentation(flagged_weak, "b1")["bookmark_tier"] == "weak"
    flagged_confident = {"carries_exercise": True, "most_confident": False,
                         "delivery_band": "delivery_signal_mid_high"}
    assert _block_presentation(flagged_confident, "b2")["bookmark_tier"] == "confident"


def test_an_ordinary_block_is_standard():
    from services.take_feedback_policy_v3_service import _block_presentation

    plain = _block_presentation({}, "b9")
    assert plain["bookmark_tier"] == "standard"
    assert plain["practice_prompt"] is False
    assert plain["block_id"] == "b9"


# ── the bar is the read, in two colours (founder lock 2026-09-30, B7) ──

def test_the_tier_names_the_read_not_the_rank():
    """`confident` above the threshold, `weak` at or below it, `standard`
    when the clip could not be read. No position, no number."""
    from services.take_feedback_policy_v3_service import _block_presentation

    def tier(band):
        return _block_presentation({"delivery_band": band}, "b")["bookmark_tier"]

    assert tier("delivery_signal_high") == "confident"
    assert tier("delivery_signal_mid_high") == "confident"
    assert tier("delivery_signal_neutral") == "weak"
    assert tier("delivery_signal_mid_low") == "weak"
    assert tier("delivery_signal_low") == "weak"
    assert tier(None) == "standard"


def test_every_block_above_the_threshold_is_confident_not_only_two():
    """A threshold is a tier name, never a rank: three blocks read above it
    are three greens, where the old ladder marked two."""
    from services.take_feedback_policy_v3 import _practice_routing
    from services.take_feedback_policy_v3_service import _block_presentation

    blocks = [_rblock("a", 0.9), _rblock("b", 0.6), _rblock("c", 0.2),
              _rblock("d", -0.3)]
    _practice_routing(blocks)
    tiers = [_block_presentation(b, b["block_id"])["bookmark_tier"] for b in blocks]
    assert tiers == ["confident", "confident", "confident", "weak"]
    presented = _block_presentation(blocks[0], "a")
    assert "delivery_band" not in presented and "rank" not in presented
