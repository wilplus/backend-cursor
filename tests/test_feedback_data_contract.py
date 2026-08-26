import uuid

from services.feedback_data_contract import (
    TAXONOMY_VERSION,
    blind_packet_hash,
    build_feedback_exposure_bundle,
    canonical_paragraph_decision,
    canonical_root_phrase,
    canonical_root_phrase_skip,
    canonical_feedback_decision,
)


OWNER_ID = "10000000-0000-0000-0000-000000000001"
PROJECT_ID = "20000000-0000-0000-0000-000000000001"
TAKE_ID = "30000000-0000-0000-0000-000000000001"
RECORDING_ID = "40000000-0000-0000-0000-000000000001"
SNIPPET_ID = "50000000-0000-0000-0000-000000000001"


def _fixture():
    text = "We shipped on Friday. The room understood why."
    document = {
        "take_session_id": TAKE_ID,
        "text": text,
        "paragraphs": [
            {"start": 0, "end": 21, "slide_index": 0},
            {"start": 22, "end": len(text), "slide_index": 1},
        ],
        "pieces": [{
            "snippet_id": SNIPPET_ID,
            "recording_id": RECORDING_ID,
            "audio_ref": "https://audio.invalid/take.webm",
            "language": "en",
            "start": 0,
            "end": len(text),
            "start_offset_ms": 120,
            "duration_ms": 4100,
            "slide_index": 0,
        }],
    }
    rows = [
        {
            "id": "confidence-1",
            "feedback_family": "confident_voice",
            "take_session_id": TAKE_ID,
            "snippet_id": SNIPPET_ID,
            "span": {"start": 0, "end": 21},
            "quote": text[:21],
            "candidate_score": 0.81,
            "machine_prediction": {
                "classification": "yes",
                "score": 0.81,
                "model_version": "confidence-model-v3",
                "complete_output": {"classification": "yes", "score": 0.81},
            },
            "acoustic_feature_snapshot": {
                "features": {"pace": 1.1, "pitch": 0.4},
            },
        },
        {
            "id": "rewrite-1",
            "feedback_family": "rewrite_clarity",
            "take_session_id": TAKE_ID,
            "snippet_id": SNIPPET_ID,
            "span": {"start": 0, "end": 21},
            "quote": text[:21],
            "proposed_text": "We shipped Friday.",
            "candidate_score": 0.72,
            "model_version": "rewrite-model-v2",
            "prompt_version": "rewrite-prompt-v4",
        },
        {
            "id": "praise-1",
            "feedback_family": "great_formulation",
            "take_session_id": TAKE_ID,
            "snippet_id": SNIPPET_ID,
            "span": {"start": 22, "end": len(text)},
            "quote": text[22:],
            "candidate_score": 0.65,
        },
        {
            "id": "praise-not-selected",
            "feedback_family": "great_formulation",
            "take_session_id": TAKE_ID,
            "snippet_id": SNIPPET_ID,
            "span": {"start": 0, "end": 21},
            "quote": text[:21],
            "candidate_score": 0.4,
        },
    ]
    keys = [
        {"id": "confidence-1", "feedback_family": "confident_voice"},
        {"id": "rewrite-1", "feedback_family": "rewrite_clarity"},
        {"id": "praise-1", "feedback_family": "great_formulation"},
    ]
    session = {
        "id": TAKE_ID,
        "owner_principal_id": OWNER_ID,
        "project_id": PROJECT_ID,
        "take_index": 2,
        # Duplicate display names are intentionally irrelevant to identity.
        "name": "Same name",
    }
    return session, document, text, rows, keys


def test_complete_candidate_pool_and_exact_three_membership_are_frozen():
    session, document, text, rows, keys = _fixture()
    bundle = build_feedback_exposure_bundle(
        session=session,
        transcript_document=document,
        served_text=text,
        candidates=rows,
        selected_keys=keys,
        manager_rules_version="manager-v7",
        commit="abc123",
    )
    assert bundle is not None
    assert bundle["owner_principal_id"] == OWNER_ID
    assert bundle["project_id"] == PROJECT_ID
    assert len(bundle["candidates"]) == 4
    assert len(bundle["selected_keys"]) == 3
    assert {row["candidate_key"] for row in bundle["candidates"]} == {
        "confidence-1", "rewrite-1", "praise-1", "praise-not-selected",
    }
    evidence = {row["candidate_key"]: row["evidence"]
                for row in bundle["candidates"]}
    assert evidence["confidence-1"]["exact_text"] == text
    assert evidence["confidence-1"]["audio_ref"].endswith("take.webm")
    assert evidence["rewrite-1"]["exact_text"] == text[:21]
    assert evidence["rewrite-1"]["replacement_text"] == "We shipped Friday."
    confidence = next(row for row in bundle["candidates"]
                      if row["candidate_key"] == "confidence-1")
    uuid.UUID(confidence["machine_prediction"]["id"])
    uuid.UUID(confidence["acoustic_feature_snapshot"]["id"])
    assert confidence["machine_prediction"]["complete_output"] == {
        "classification": "yes", "score": 0.81}
    assert len(bundle["generation_runs"]) == 1
    assert bundle["generation_runs"][0]["task_type"] == \
        "correction_generation"
    uuid.UUID(bundle["candidate_set_id"])


def test_bundle_is_deterministic_and_refuses_any_non_exact_three_set():
    session, document, text, rows, keys = _fixture()
    kwargs = dict(
        session=session, transcript_document=document, served_text=text,
        candidates=rows, selected_keys=keys,
        manager_rules_version="manager-v7", commit="abc123",
    )
    first = build_feedback_exposure_bundle(**kwargs)
    second = build_feedback_exposure_bundle(**kwargs)
    assert first == second
    assert build_feedback_exposure_bundle(
        **{**kwargs, "selected_keys": keys[:2]}) is None
    assert build_feedback_exposure_bundle(
        **{**kwargs, "selected_keys": [keys[0], keys[1], keys[1]]}) is None


def test_fallback_and_source_target_mismatch_are_research_only():
    session, document, text, rows, keys = _fixture()
    rows[2]["_manager_evidence"] = {"fallback": True}
    bundle = build_feedback_exposure_bundle(
        session=session, transcript_document=document, served_text=text,
        candidates=rows, selected_keys=keys,
        manager_rules_version="manager-v7", commit="abc123",
    )
    praise = next(row for row in bundle["candidates"]
                  if row["candidate_key"] == "praise-1")
    assert praise["training_eligible"] is False
    assert praise["ineligibility_reason"] == \
        "fallback_or_source_target_mismatch"


def test_typed_decisions_never_infer_editor_open_as_a_preference():
    assert canonical_feedback_decision(
        take_id=TAKE_ID,
        rater_id=OWNER_ID,
        feedback_id="rewrite-1",
        feedback_family="rewrite_clarity",
        response="edit_myself",
    ) is None
    accepted = canonical_feedback_decision(
        take_id=TAKE_ID,
        rater_id=OWNER_ID,
        feedback_id="rewrite-1",
        feedback_family="rewrite_clarity",
        response="apply_suggestion",
    )
    assert accepted["value"] == "accept_proposed"
    assert accepted["taxonomy_version"] == TAXONOMY_VERSION
    assert accepted == canonical_feedback_decision(
        take_id=TAKE_ID,
        rater_id=OWNER_ID,
        feedback_id="rewrite-1",
        feedback_family="rewrite_clarity",
        response="apply_suggestion",
    )


def test_blind_packet_hash_ignores_forbidden_ratings_and_predictions():
    allowed = {
        "evidence_span_id": "evidence-1",
        "audio_ref": "signed-audio",
        "start_ms": 10,
        "end_ms": 20,
        "technical_metadata": {"codec": "opus"},
    }
    assert blind_packet_hash(allowed) == blind_packet_hash({
        **allowed,
        "owner_value": "yes",
        "machine_value": "no",
        "peer_values": ["in_between"],
    })


def test_paragraph_and_root_decisions_are_exact_and_idempotent():
    part_id = "60000000-0000-0000-0000-000000000001"
    decision = canonical_paragraph_decision(
        take_id=TAKE_ID,
        project_id=PROJECT_ID,
        rater_id=OWNER_ID,
        source_ideal_part_id=part_id,
        exact_text="The room understood why.",
        value="lock_for_next_take",
        revision_coordinate="iteration-2",
    )
    assert decision == canonical_paragraph_decision(
        take_id=TAKE_ID,
        project_id=PROJECT_ID,
        rater_id=OWNER_ID,
        source_ideal_part_id=part_id,
        exact_text="The room understood why.",
        value="lock_for_next_take",
        revision_coordinate="iteration-2",
    )
    uuid.UUID(decision["evidence_id"])
    root = canonical_root_phrase(
        take_id=TAKE_ID,
        project_id=PROJECT_ID,
        rater_id=OWNER_ID,
        source_ideal_part_id=part_id,
        exact_text="understood why",
        start=9,
        end=23,
        revision_coordinate="root-selection-1",
    )
    assert root["idempotency_key"].startswith("root-phrase:")
    assert canonical_root_phrase(
        take_id=TAKE_ID,
        project_id=PROJECT_ID,
        rater_id=OWNER_ID,
        source_ideal_part_id=part_id,
        exact_text="understood why",
        start=23,
        end=9,
        revision_coordinate="bad",
    ) is None
    skipped = canonical_root_phrase_skip(
        take_id=TAKE_ID,
        project_id=PROJECT_ID,
        rater_id=OWNER_ID,
        source_ideal_part_id=part_id,
        revision_coordinate="legacy-revision-9",
    )
    assert skipped["idempotency_key"].startswith("root-phrase-skip:")
