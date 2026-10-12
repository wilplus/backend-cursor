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


def test_dark_activation_covers_every_speaker_and_stays_fail_closed(monkeypatch):
    # S-V1 A: every speaker's Takes, only in explicit dark mode.
    monkeypatch.setattr(Config, "TAKE_FEEDBACK_POLICY_V3_SHADOW_WRITE_MODE", "dark")
    monkeypatch.setattr(Config, "TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID", "founder")
    assert dark_enabled("founder") is True
    assert dark_enabled("someone-else") is True
    assert dark_enabled("") is False
    assert dark_enabled(None) is False
    monkeypatch.setattr(Config, "TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID", "")
    assert dark_enabled("someone-else") is True
    for mode in ("enabled", "off", "", "Dark"):
        monkeypatch.setattr(Config, "TAKE_FEEDBACK_POLICY_V3_SHADOW_WRITE_MODE", mode)
        assert dark_enabled("someone-else") is False

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


# ── one whole Take through the public frame (contracts 24a, 24c, 24e-24g) ──
#
# Replaces 30 tests that each called one private helper of the frame
# (founder 2026-10-12, "How to test": test the contract, not the helpers).
# Every rule they pinned is asserted here on what `build_shadow_frame`
# returns, so a refactor that keeps the frame right keeps this green.

# (piece index, slide, words, delivery score, has a snippet record)
_DECK = [
    (0, 0, 75, 0.9, True),     # high       -> confident, green
    (1, 1, 75, 0.6, True),     # high       -> confident, green
    (2, 2, 75, 0.2, True),     # mid-high   -> confident, NOT green (third)
    (3, 3, 75, 0.0, True),     # neutral    -> weak, exercise, no prompt
    (4, 4, 75, -0.7, True),    # low        -> weak, exercise, prompt
    (5, 5, 25, None, True),    # unread     -> neither; short_slide_run
    (6, 6, 120, -0.2, True),   # mid-low    -> weak; indivisible_long
    (7, 7, 50, 0.3, True),     # slide 7: two blocks, only one selectable
    (8, 7, 50, 0.3, False),
    (9, 7, 50, 0.3, False),
    (10, 8, 75, 0.5, False),   # slide 8: a block, but no clip -> uncovered
]


def _deck_note(note_id, family, snippet_id, start, end, specificity):
    row = {
        "id": note_id, "feedback_family": family, "snippet_id": snippet_id,
        "take_session_id": "take-2", "span": {"start": start, "end": end},
        "_manager_evidence": {"specificity": specificity, "fallback": False},
    }
    if family == "rewrite_clarity":
        row.update(quote="a", proposed_text="b", model_version="rewrite-model-v1")
    else:
        row.update(prompt_version="praise-prompt-v1")
    return row


def _deck_frame(take_index):
    pieces, snippets, at = [], [], 0
    for index, slide, words, score, has_snippet in _DECK:
        text = " ".join(f"w{index}x{n}" for n in range(words))
        pieces.append({
            "snippet_id": f"s{index}", "take_session_id": "take-2",
            "slide_index": slide, "start": at, "end": at + len(text),
            "text": text, "recording_id": "recording-1",
            "start_offset_ms": index * 5000, "duration_ms": 5000,
        })
        at += len(text) + 1
        if has_snippet:
            metrics = ({"voice_confidence": {
                "version": "voice-confidence-universal-v3", "score": score,
            }} if score is not None else {})
            snippets.append({
                "id": f"s{index}", "session_id": "take-2",
                "recording_id": "recording-1",
                "start_offset_ms": index * 5000, "duration_ms": 5000,
                "metrics": metrics,
            })
    text = " ".join(piece["text"] for piece in pieces)
    # Block spans: slide 0 is 0-439, slide 3 is 1320-1759, slide 4 is
    # 1760-2199, slide 5 (unread) is 2200-2339.
    notes = [
        _deck_note("p-worse", "great_formulation", "s0", 100, 140, 2),
        _deck_note("p-best", "great_formulation", "s0", 200, 240, 5),
        _deck_note("p-in-weak", "great_formulation", "s4", 1800, 1840, 9),
        _deck_note("p-unread", "great_formulation", "s5", 2210, 2250, 9),
        _deck_note("r-in-confident", "rewrite_clarity", "s0", 50, 90, 9),
        _deck_note("r-straddle", "rewrite_clarity", "s3", 1740, 1780, 9),
        _deck_note("r-unread", "rewrite_clarity", "s5", 2260, 2300, 9),
        _deck_note("r-weak", "rewrite_clarity", "s4", 1900, 1940, 3),
    ]
    return build_shadow_frame(
        take_document={"take_session_id": "take-2", "text": text,
                       "pieces": pieces},
        snippets=snippets, suggestions={}, feedback_candidates=notes,
        take_index=take_index, expected_recording_id="recording-1",
        served_text=text,
    )


def test_a_whole_take_is_partitioned_read_marked_noted_and_covered():
    frame = _deck_frame(take_index=2)
    blocks = frame["blocks"]
    by_slide = {}
    for block in blocks:
        by_slide.setdefault(block["slide_index"], []).append(block)

    # 24a: a block outside 60-90 words stays whole and says why.
    assert [(b["slide_index"], b["word_count"], b["partition_exception"])
            for b in blocks] == [
        (0, 75, None), (1, 75, None), (2, 75, None), (3, 75, None),
        (4, 75, None), (5, 25, "short_slide_run"), (6, 120, "indivisible_long"),
        (7, 50, "closest_outside_range"), (7, 100, "closest_outside_range"),
        (8, 75, None),
    ]

    # 24g: the two most confident blocks are green, as a flag, and every
    # other block is written False rather than left without the key.
    assert [b["most_confident"] for b in blocks] == [
        True, True, False, False, False, False, False, False, False, False]

    # 24e/24f: the prompt cuts BELOW neutral; the exercise rides every block
    # read weak (neutral and below); an unread or unselected block gets
    # neither.
    routed = [(b["slide_index"], b["practice_prompt"], b["carries_exercise"])
              for b in blocks]
    assert routed == [
        (0, False, False), (1, False, False), (2, False, False),
        (3, False, True), (4, True, True), (5, False, False),
        (6, True, True), (7, False, False), (7, False, False),
        (8, False, False),
    ]

    # 24f: one note per block, by the read, only from inside the block. The
    # best-ranked praise in a confident block wins; a praise in a weak block,
    # a rewrite in a confident one, a rewrite straddling a block boundary and
    # anything in the unread block are never selected however they rank.
    lanes = frame["verbal_lanes"]
    rewrite, praise = lanes["rewrite_clarity"], lanes["great_formulation"]
    assert rewrite["selected_candidate_ids"] == ["r-weak"]
    assert rewrite["anchors"] == [
        {"block_id": by_slide[4][0]["block_id"], "candidate_id": "r-weak"}]
    assert praise["selected_candidate_ids"] == ["p-best"]
    assert praise["anchors"] == [
        {"block_id": by_slide[0][0]["block_id"], "candidate_id": "p-best"}]
    # 25: every block read for a lane without a note is named, typed.
    assert rewrite["outcome"] == praise["outcome"] == "selected"
    assert [row["block_id"] for row in rewrite["blocks_without_note"]] == [
        by_slide[3][0]["block_id"], by_slide[6][0]["block_id"]]
    assert [row["block_id"] for row in praise["blocks_without_note"]] == [
        by_slide[1][0]["block_id"], by_slide[2][0]["block_id"],
        by_slide[7][0]["block_id"]]
    assert {row["reason"] for lane in (rewrite, praise)
            for row in lane["blocks_without_note"]} == {"no_defensible_candidate"}

    # 24c: the denominator is Slides with a block. Slide 7 is covered by its
    # one selected block; slide 8 formed a block but has no clip, and says so.
    coverage = frame["coverage"]
    assert coverage["assessable_slides"] == 9
    assert coverage["covered_slide_indexes"] == [0, 1, 2, 3, 4, 5, 6, 7]
    assert coverage["uncovered"] == [{
        "slide_index": 8, "block_count": 1,
        "reasons": ["no_exact_clip_lineage_candidate"],
    }]
    assert coverage["required_floor"] == 0.80
    assert coverage["meets_floor"] is True        # 8/9 clears Take 2's 80%
    assert _deck_frame(take_index=3)["coverage"]["meets_floor"] is False


def test_a_take_with_no_blocks_has_no_frame():
    """Nothing to cover is not a coverage failure: no frame at all."""
    assert build_shadow_frame(
        take_document={"take_session_id": "take-2", "text": "", "pieces": []},
        snippets=[], suggestions={}, feedback_candidates=[], take_index=2,
        expected_recording_id="recording-1", served_text="",
    ) is None


def _rblock(block_id, score):
    return {
        "block_id": block_id, "slide_index": 0, "start": 0, "end": 10,
        "selected_candidate_id": f"c-{block_id}",
        "confidence_candidates": [
            {"candidate_id": f"c-{block_id}", "machine_score": score, "ordinal": 0},
        ],
    }


# ── 25: an honest empty lane is typed, never merely absent ──

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


def test_the_frame_declares_the_exercise_rule_the_serve_path_follows():
    practice = _frame()["practice_policy"]
    assert practice["exercise_budget"] == "one_per_block_read_weak"
    assert practice["exercise_target"] == "each_block_read_weak_own_clip"
    assert practice["threshold"] == "below_neutral_delivery_band"


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


