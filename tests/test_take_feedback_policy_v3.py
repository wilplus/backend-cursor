from services.take_feedback_policy_v3 import (
    FRAME_SCHEMA_VERSION,
    POLICY_VERSION,
    build_shadow_frame,
    dark_enabled,
)


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
            "snippet_id": "snippet-1",
            "take_session_id": "take-2",
            "span": {"start": 50, "end": 90},
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
            "text": "x" * 500,
            "pieces": pieces,
        },
        snippets=snippets,
        suggestions=suggestions,
        feedback_candidates=feedback,
        take_index=take_index,
        expected_recording_id="recording-1",
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


def test_take_one_is_confidence_only_and_take_two_selects_global_absolute_lanes():
    first = _frame(take_index=1)
    assert first["verbal_lanes"]["enabled"] is False
    assert first["verbal_lanes"]["rewrite_clarity"]["selected_candidate_id"] is None

    mature = _frame(take_index=2)
    assert mature["verbal_lanes"]["enabled"] is True
    assert mature["verbal_lanes"]["rewrite_clarity"]["selected_candidate_id"] == "best-rewrite"
    assert mature["verbal_lanes"]["great_formulation"]["selected_candidate_id"] == "best-praise"


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
    monkeypatch.setenv("TAKE_FEEDBACK_POLICY_V3_MODE", "dark")
    monkeypatch.setenv("TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID", "founder")
    assert dark_enabled("founder") is True
    assert dark_enabled("someone-else") is False
    monkeypatch.setenv("TAKE_FEEDBACK_POLICY_V3_MODE", "enabled")
    assert dark_enabled("founder") is False
