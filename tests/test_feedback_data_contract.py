import uuid

from services.feedback_data_contract import (
    blind_packet_hash,
    build_feedback_exposure_bundle,
    canonical_paragraph_decision,
    canonical_root_phrase,
    canonical_root_phrase_skip,
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


def test_v3_service_bundle_allows_variable_budget_but_never_dataset_use():
    session, document, text, rows, _keys = _fixture()
    keys = [
        {"id": "confidence-1", "feedback_family": "confident_voice"},
        {"id": "praise-1", "feedback_family": "great_formulation"},
    ]
    bundle = build_feedback_exposure_bundle(
        session=session,
        transcript_document=document,
        served_text=text,
        candidates=rows,
        selected_keys=keys,
        manager_rules_version="take-feedback-policy-v3-serving-v1",
        commit="abc123",
    )
    assert bundle is not None
    assert bundle["selected_keys"] == keys
    assert all(not row["training_eligible"] for row in bundle["candidates"])
    assert {
        row["ineligibility_reason"] for row in bundle["candidates"]
    } == {"service_product_evidence_only"}
    assert build_feedback_exposure_bundle(
        session=session,
        transcript_document=document,
        served_text=text,
        candidates=rows,
        selected_keys=[keys[1]],
        manager_rules_version="take-feedback-policy-v3-serving-v1",
        commit="abc123",
    ) is None


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


# ---------------------------------------------------------------------------
#  A CANDIDATE'S ID BELONGS TO ITS SET (2026-09-21).
#
#  Minutes after the lineage write first succeeded, the next open logged
#  23505 on feedback_candidates_pkey: the speaker's edits changed the
#  inventory, a second candidate set was recorded for the Take, and it carried
#  the same candidate ids as the first. Ids are now sealed to the inventory:
#  same content → same ids (replay stays idempotent), changed content → ids
#  of its own.
# ---------------------------------------------------------------------------
