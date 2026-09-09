from pathlib import Path

import pytest

from services.coach_guidance_delivery import (
    parse_attachment_request,
    principal_is_allowlisted,
    runtime_is_enabled,
    synthetic_context_payload,
)
from services.data_purge_registry import DEPENDENCIES

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations/add_coach_guidance_delivery_d3.sql"


def _identity_payload(**updates):
    payload = {
        "review_batch_id": "batch",
        "reveal_grant_id": "grant",
        "reveal_access_id": "access",
        "review_assignment_id": "assignment",
        "feedback_membership_id": "membership",
        "feedback_candidate_id": "candidate",
        "attachment_class": "general_product_guidance",
        "written_note": "Try a shorter pause before the final sentence.",
    }
    payload.update(updates)
    return payload


def test_runtime_gate_is_disabled_by_default():
    assert runtime_is_enabled() is False


def test_pilot_allowlist_accepts_only_exact_acquisition_principal(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_PILOT_ENABLED", True)
    monkeypatch.setattr(Config, "MLC3_PILOT_PRINCIPAL_IDS", ("principal-1",))
    assert principal_is_allowlisted(principal_id="principal-1") is True
    assert principal_is_allowlisted(principal_id="user-1") is False
    assert principal_is_allowlisted(principal_id=None) is False


def test_general_guidance_never_accepts_exercise_identity():
    with pytest.raises(ValueError, match="GENERAL_EXERCISE_FIELDS_FORBIDDEN"):
        parse_attachment_request(
            _identity_payload(exercise_offer_id="offer", need_contract_id="need")
        )


def test_mlc3_requires_approved_need_and_complete_offer_identity():
    with pytest.raises(ValueError, match="APPROVED_NEED_AND_INVENTORY_REQUIRED"):
        parse_attachment_request(_identity_payload(attachment_class="mlc3_exercise"))


def test_structure_and_delivery_remain_product_subcategories():
    request = parse_attachment_request(
        _identity_payload(product_subcategory="structure")
    )
    assert request.product_subcategory == "structure"
    with pytest.raises(ValueError, match="SUBCATEGORY_INVALID"):
        parse_attachment_request(_identity_payload(product_subcategory="new_family"))


def test_synthetic_payload_is_structurally_nonserving_and_nondataset():
    payload = synthetic_context_payload(
        review_batch_id="batch", reveal_grant_id="grant", items=[]
    )
    assert payload["serves_user"] is False
    assert payload["dataset_eligible"] is False
    assert payload["synthetic_only"] is True


def test_migration_freezes_batches_and_separates_delivery_from_exposure():
    sql = MIGRATION.read_text()
    assert "coach_guidance_review_frames" in sql
    assert "eligible_assignment_count" in sql
    assert "cutoff_at" in sql
    assert "COACH_GUIDANCE_BATCH_INCOMPLETE" in sql
    assert "coach_guidance_upload_recoveries" in sql
    assert "write_started" in sql
    assert "write_acknowledged" in sql
    assert "COACH_GUIDANCE_UPLOAD_NOT_FINALIZED" in sql
    assert "blind_judgment_id UUID NOT NULL" in sql
    assert "COACH_GUIDANCE_UPLOAD_ALREADY_TERMINAL" in sql
    assert "'authored', 'assigned', 'delivered', 'rendered', 'played'" in sql
    assert "serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user)" in sql
    assert (
        "dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)"
        in sql
    )


def test_migration_revalidates_authority_and_preserves_registry_boundary():
    sql = MIGRATION.read_text()
    assert "require_coach_guidance_assignment_live_v1" in sql
    assert "clock_timestamp()" in sql
    assert "processing_service_blocks" in sql
    assert "data_purge_requests" in sql
    assert "invalidate_synthetic_coach_publication_v1" in sql
    assert "COACH_GUIDANCE_MLC3_NEED_MISMATCH" in sql
    assert "upload_event.event_kind = 'finalized'" in sql
    assert "user_source_dependent" in sql
    assert "independent_clean_media" in sql
    assert "ml_learning_surfaces" not in sql
    assert "ml_feedback_families" not in sql


def _function_body(sql: str, function_name: str) -> str:
    marker = f"CREATE OR REPLACE FUNCTION public.{function_name}("
    start = sql.index(marker)
    end = sql.index("\n$$;", start) + 4
    return sql[start:end]


def test_general_guidance_uses_coach_review_not_exercise_authority():
    sql = MIGRATION.read_text()
    assignment = _function_body(sql, "require_coach_guidance_assignment_live_v1")
    completion = _function_body(sql, "complete_synthetic_coach_guidance_batch_v1")
    attachment = _function_body(sql, "create_synthetic_coach_guidance_attachment_v1")
    assert "require_coach_guidance_receipt_authority_v1" in assignment
    assert "IF p_purpose_id = 'coach_review'" in assignment
    assert "'coach_review'" in completion
    assert "'personalized_exercise_recommendation'" not in completion
    assert "CASE WHEN p_attachment_class = 'mlc3_exercise'" in attachment


def test_batch_liveness_and_revision_are_fail_closed():
    sql = MIGRATION.read_text()
    liveness = _function_body(sql, "require_coach_guidance_assignment_live_v1")
    freeze = _function_body(sql, "freeze_synthetic_coach_guidance_batch_v1")
    assert "assignment.reviewer_role = 'coach'" in liveness
    assert "assignment.expires_at > wall_now" in liveness
    assert "event_kind IN ('cancelled', 'expired')" in liveness
    assert "require_coach_guidance_reviewer_access_v1" in liveness
    assert "batch_revision" in freeze
    assert "supersedes_batch_id" in freeze
    assert "cancelled_before_cutoff" in freeze
    assert "expired_before_cutoff" in freeze


def test_independent_clean_media_requires_immutable_review():
    sql = MIGRATION.read_text()
    registration = _function_body(sql, "register_synthetic_coach_guidance_media_v1")
    assert "coach_guidance_independent_media_reviews" in sql
    assert "p_independent_media_review_id UUID" in registration
    assert "COACH_GUIDANCE_INDEPENDENT_REVIEW_REQUIRED" in registration
    assert "contains_user_audio BOOLEAN NOT NULL CHECK (NOT contains_user_audio)" in sql
    assert "contains_user_transcript BOOLEAN NOT NULL CHECK" in sql
    assert "contains_user_identity BOOLEAN NOT NULL CHECK" in sql
    assert "contains_project_context BOOLEAN NOT NULL CHECK" in sql
    assert "contains_unique_user_passage BOOLEAN NOT NULL CHECK" in sql


def test_media_validity_is_rechecked_at_every_boundary_and_replay():
    sql = MIGRATION.read_text()
    functions = {
        name: _function_body(sql, name)
        for name in (
            "record_synthetic_coach_guidance_upload_event_v1",
            "register_synthetic_coach_guidance_media_v1",
            "create_synthetic_coach_guidance_attachment_v1",
            "record_synthetic_coach_guidance_event_v1",
            "publish_synthetic_coach_exercise_v1",
        )
    }
    assert "coach_guidance_media_validity_events" in sql
    assert "'active', 'quarantined', 'invalid', 'deleted'" in sql
    object_guard = _function_body(sql, "require_coach_guidance_media_object_live_v1")
    assert "coach-guidance-media-validity:" in object_guard
    assert "pg_advisory_xact_lock" in object_guard
    assert "current_validity.validity_state = 'active'" in object_guard
    assert (
        "result.media_object_id"
        in functions["record_synthetic_coach_guidance_upload_event_v1"]
    )
    assert (
        "require_coach_guidance_media_object_live_v1"
        in functions["record_synthetic_coach_guidance_upload_event_v1"]
    )
    assert (
        "require_coach_guidance_media_object_live_v1"
        in functions["register_synthetic_coach_guidance_media_v1"]
    )
    for name in (
        "create_synthetic_coach_guidance_attachment_v1",
        "record_synthetic_coach_guidance_event_v1",
        "publish_synthetic_coach_exercise_v1",
    ):
        assert "require_coach_guidance_media_live_v1" in functions[name]
    assert (
        "validity.validity_state = 'active'"
        in functions["register_synthetic_coach_guidance_media_v1"]
    )


def test_terminal_only_batch_revisions_and_coach_provenance_are_explicit():
    sql = MIGRATION.read_text()
    freeze = _function_body(sql, "freeze_synthetic_coach_guidance_batch_v1")
    complete = _function_body(sql, "complete_synthetic_coach_guidance_batch_v1")
    assert "eligible_assignment_count >= 0" in sql
    assert "eligible_assignment_count + excluded_assignment_count > 0" in sql
    assert "COACH_GUIDANCE_BATCH_HAS_NO_ASSIGNMENTS" in freeze
    assert "COACH_GUIDANCE_BATCH_HAS_NO_REQUIRED_ASSIGNMENTS" not in freeze
    assert "actor_provenance = 'blind_coach'" in complete
    assert "blind_peer" not in complete


def test_deletion_registry_covers_every_subject_linked_d3_relation():
    expected_relations = {
        "coach_guidance_review_frames",
        "coach_guidance_review_frame_items",
        "coach_guidance_review_batches",
        "coach_guidance_reveal_grants",
        "coach_guidance_reveal_grant_judgments",
        "coach_guidance_reveal_accesses",
        "coach_guidance_upload_permits",
        "coach_guidance_upload_recoveries",
        "coach_guidance_upload_events",
        "coach_guidance_media_validity_events",
        "coach_guidance_independent_media_reviews",
        "coach_guidance_media_bindings",
        "coach_guidance_attachments",
        "coach_guidance_attachment_versions",
        "coach_guidance_lifecycle_events",
        "coach_guidance_publications",
        "coach_guidance_publication_invalidations",
    }
    registered = {dependency.relation for dependency in DEPENDENCIES}
    assert expected_relations <= registered
