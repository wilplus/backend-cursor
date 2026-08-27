"""Tests for prepared packets versus true rendered exposure receipts."""
from __future__ import annotations

import uuid
from unittest.mock import Mock

import pytest

from services.learning_exposures import (
    LearningExposureError,
    acknowledge_visible_render,
    prepare_feedback_presentations,
    prepare_ideal_text_presentation,
    prepare_presentation,
)


OWNER = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
TAKE = "33333333-3333-4333-8333-333333333333"
ACTOR = "44444444-4444-4444-8444-444444444444"


def _candidate(key: str, family: str, evidence_id: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "candidate_key": key,
        "feedback_family": family,
        "candidate_score": 0.7,
        "rank_evidence": {"rank_key": [1]},
        "generated_output": {"quote": f"Visible {key}"},
        "training_eligible": True,
        "evidence": {
            "id": evidence_id,
            "evidence_hash": "a" * 64,
            "exact_text": f"Evidence {key}",
            "audio_ref": "recordings/take.webm",
            "start_ms": 0,
            "end_ms": 1000,
        },
    }


def _bundle() -> dict:
    candidates = [
        _candidate("voice", "confident_voice",
                   "55555555-5555-4555-8555-555555555555"),
        _candidate("rewrite", "rewrite_clarity",
                   "66666666-6666-4666-8666-666666666666"),
        _candidate("praise", "great_formulation",
                   "77777777-7777-4777-8777-777777777777"),
    ]
    return {
        "owner_principal_id": OWNER,
        "project_id": PROJECT,
        "take_id": TAKE,
        "candidate_set_id": "88888888-8888-4888-8888-888888888888",
        "candidates": candidates,
        "selected_keys": [
            {"id": row["candidate_key"],
             "feedback_family": row["feedback_family"]}
            for row in candidates
        ],
        "versions": {"taxonomy_version": "v1", "selector_version": "v1"},
        "generation_runs": [],
    }


def _presentation_database() -> Mock:
    database = Mock()
    database.create_learning_surface_presentation.side_effect = lambda row: {
        "presentation_id": str(uuid.uuid4()),
        "acknowledgement_token": str(uuid.uuid4()),
        "learning_surface": row["learning_surface"],
        "evaluation_only": row["delivery_mode"] == "shadow",
    }
    return database


def test_three_feedback_cards_prepare_five_isolated_surface_packets():
    database = _presentation_database()

    packets = prepare_feedback_presentations(
        database=database, bundle=_bundle(), actor_id=ACTOR)

    assert set(packets) == {"voice", "rewrite", "praise"}
    assert [row["learning_surface"] for row in packets["voice"]] == [
        "confidence_classification",
    ]
    assert {row["learning_surface"] for row in packets["rewrite"]} == {
        "correction_generation", "correction_selection",
    }
    assert {row["learning_surface"] for row in packets["praise"]} == {
        "praise_generation", "praise_selection",
    }
    assert database.create_learning_surface_presentation.call_count == 5


def test_each_packet_freezes_the_complete_candidate_set_not_just_the_winner():
    database = _presentation_database()
    prepare_feedback_presentations(
        database=database, bundle=_bundle(), actor_id=ACTOR)

    for call in database.create_learning_surface_presentation.call_args_list:
        payload = call.args[0]
        assert len(payload["complete_candidate_set"]) == 3
        assert len(payload["content_hash"]) == 64
        assert payload["actor_role"] == "owner"
        assert payload["actor_id"] == ACTOR


def test_shadow_packets_can_be_stored_but_are_never_returned_for_rendering():
    database = _presentation_database()

    packets = prepare_feedback_presentations(
        database=database,
        bundle=_bundle(),
        actor_id=ACTOR,
        delivery_mode="shadow",
    )

    assert packets == {}
    assert database.create_learning_surface_presentation.call_count == 5


def test_ideal_text_packet_uses_document_take_boundary_without_fake_evidence():
    database = _presentation_database()

    packet = prepare_ideal_text_presentation(
        database=database,
        owner_principal_id=OWNER,
        project_id=PROJECT,
        take_id=TAKE,
        actor_id=ACTOR,
        text="The exact rendered document.",
        version=2,
        take_count=2,
        title="A talk",
        parts=[{"id": "part-1", "text": "The exact rendered document."}],
    )

    assert packet["learning_surface"] == "ideal_text_generation"
    payload = database.create_learning_surface_presentation.call_args.args[0]
    assert payload["evidence_span_id"] is None
    assert payload["visible_payload"]["text"] == \
        "The exact rendered document."
    assert payload["selected_candidate"]["document_hash"] == \
        payload["complete_candidate_set"][0]["document_hash"]
    assert payload["versions"]["surface_schema"] == \
        "ideal-text-exposure-v1"


def test_ideal_text_packet_rejects_an_empty_document():
    database = _presentation_database()
    with pytest.raises(LearningExposureError, match="no document"):
        prepare_ideal_text_presentation(
            database=database,
            owner_principal_id=OWNER,
            project_id=PROJECT,
            take_id=TAKE,
            actor_id=ACTOR,
            text="   ",
            version=1,
            take_count=1,
            title=None,
            parts=None,
        )


def test_presentation_persistence_failure_is_explicit():
    database = Mock()
    database.create_learning_surface_presentation.return_value = None

    with pytest.raises(LearningExposureError, match="was not persisted"):
        prepare_presentation(
            database=database,
            owner_principal_id=OWNER,
            project_id=PROJECT,
            take_id=TAKE,
            evidence_span_id="55555555-5555-4555-8555-555555555555",
            learning_surface="confidence_classification",
            actor_role="owner",
            actor_id=ACTOR,
            complete_candidate_set=[{"candidate_key": "voice"}],
            selected_candidate={"candidate_key": "voice"},
            visible_payload={"audio_ref": "take.webm"},
            versions={"taxonomy_version": "v1"},
        )


def test_post_render_ack_has_stable_idempotency_and_no_decision_value():
    database = Mock()
    database.acknowledge_learning_surface_exposure.return_value = {
        "exposure_receipt_id": "99999999-9999-4999-8999-999999999999",
        "learning_surface": "confidence_classification",
    }
    kwargs = {
        "database": database,
        "presentation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "acknowledgement_token": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "actor_role": "owner",
        "actor_id": ACTOR,
        "render_instance_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    }

    acknowledge_visible_render(**kwargs)
    first = database.acknowledge_learning_surface_exposure.call_args.args[0]
    acknowledge_visible_render(**kwargs)
    second = database.acknowledge_learning_surface_exposure.call_args.args[0]

    assert first["idempotency_key"] == second["idempotency_key"]
    assert "value" not in first
    assert "decision" not in first


def test_invalid_render_identity_never_reaches_the_database():
    database = Mock()
    with pytest.raises(LearningExposureError, match="invalid UUID"):
        acknowledge_visible_render(
            database=database,
            presentation_id="not-a-uuid",
            acknowledgement_token="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            actor_role="owner",
            actor_id=ACTOR,
            render_instance_id="cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        )
    database.acknowledge_learning_surface_exposure.assert_not_called()
