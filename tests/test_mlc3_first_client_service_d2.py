import re
from pathlib import Path

import pytest

from services.coach_guidance_delivery import principal_is_allowlisted
from services.data_purge_registry import DEPENDENCIES

ROOT = Path(__file__).resolve().parents[1]
SQL = (
    ROOT / "migrations/add_mlc3_first_client_service_d2.sql"
).read_text()
ROUTE = (
    ROOT / "routes/v2/mlc3_first_client_service.py"
).read_text()
COACH_ROUTE = (
    ROOT / "routes/v2/mlc3_first_client_coach.py"
).read_text()
GUIDANCE_ROUTE = (
    ROOT / "routes/v2/coach_guidance_delivery.py"
).read_text()


def _function(name: str) -> str:
    marker = f"CREATE OR REPLACE FUNCTION public.{name}("
    start = SQL.index(marker)
    return SQL[start:SQL.index("\n$$;", start) + 4]


def test_all_four_service_gates_are_independent_and_default_closed(monkeypatch):
    from config import Config

    assert Config.MLC3_PILOT_ENABLED is False
    monkeypatch.setattr(Config, "MLC3_PILOT_ENABLED", True)
    monkeypatch.setattr(Config, "MLC3_PILOT_PRINCIPAL_IDS", ())
    assert principal_is_allowlisted(principal_id="principal") is False
    assert "state = 'disabled'" in SQL
    assert "NEXT_PUBLIC_MLC3_PILOT_ENABLED" not in ROUTE


def test_service_rpcs_never_delegate_to_synthetic_rpcs():
    service_functions = (
        "freeze_feedback_v3_service_membership_v1",
        "ack_feedback_v3_service_render_v1",
        "record_feedback_v3_service_response_v1",
        "freeze_exercise_service_offer_v2",
        "create_exercise_practice_service_session_v1",
        "reserve_exercise_practice_service_upload_v1",
        "ack_exercise_practice_service_upload_v1",
        "finalize_exercise_practice_service_media_v1",
        "authorize_exercise_practice_transcription_v1",
        "mark_exercise_practice_transcription_dispatched_v1",
        "finalize_exercise_practice_transcription_v1",
        "reconcile_exercise_practice_transcription_v1",
        "reconcile_exercise_practice_transcription_request_v1",
        "attach_exercise_practice_service_attempt_v1",
        "record_exercise_practice_service_measurement_v1",
        "record_exercise_practice_service_validity_v1",
        "freeze_exercise_practice_service_selection_v1",
        "record_exercise_offer_service_event_v1",
        "record_exercise_practice_service_event_v1",
        "reserve_coach_guidance_service_upload_v1",
        "record_coach_guidance_service_upload_event_v1",
        "finalize_coach_guidance_service_media_v1",
        "create_coach_guidance_service_attachment_v1",
        "record_coach_guidance_service_event_v1",
        "resolve_coach_guidance_service_media_read_v1",
        "publish_coach_guidance_service_exercise_v1",
    )
    for name in service_functions:
        body = _function(name)
        assert re.search(r"public\.[a-z0-9_]*synthetic_[a-z0-9_]*\(", body) is None


def test_render_and_response_require_exact_frozen_identity():
    render = _function("ack_feedback_v3_service_render_v1")
    response = _function("record_feedback_v3_service_response_v1")
    for identity in (
        "membership_id",
        "candidate_id",
        "feedback_exposure_id",
        "content_identity_sha256",
    ):
        assert identity in render
    assert "render_receipt_id" in response
    assert "confidence-owner-five-state-v1" in response
    assert "confident_audio_unclear" in response
    assert "shown_at IS NOT NULL" in response
    assert "feedback_exposure_render_transition" in render
    assert "SET shown_at = p_rendered_at" in render
    assert "exposed.shown_at IS NULL" in render
    assert "row.shown_at IS NOT NULL" in render


def test_offer_requires_response_and_audio_unclear_fails_closed():
    required = _function("require_feedback_v3_service_response_v1")
    offer = _function("freeze_exercise_service_offer_v2")
    assert "binding.response IN" in required
    assert "'confident_not_sure'" in required
    assert "'confident_audio_unclear'" not in required
    assert "require_feedback_v3_service_response_v1" in offer
    assert "coach_exercise_requested" in offer
    assert "exercise_n1_pattern_candidates" in offer
    assert "pattern_distance" in offer


def test_source_and_practice_authorization_receipts_stay_separate():
    assert "source_acquisition_receipt_id" in SQL
    assert "practice_acquisition_receipt_id" in SQL
    assert "pooled_authorization_snapshot_id" in SQL
    authority = _function("issue_exercise_service_authority_v1")
    assert "pooled_model_improvement" in authority
    assert "pooled_snapshot_id" in authority
    assert "service_snapshot_id" in authority
    assert "pooled_snapshot_id" not in _function(
        "require_exercise_practice_service_live_v1"
    )
    context = _function("prepare_feedback_v3_service_context_v1")
    assert "source_attempt.authorization_snapshot_id" in context
    assert "source_pooled_snapshot_id" in context
    assert "pooled.created_at <= source_attempt.created_at" in context


def test_offer_and_practice_session_require_authenticated_principal():
    offer = _function("freeze_exercise_service_offer_v2")
    practice = _function("create_exercise_practice_service_session_v1")
    assert "p_acquisition_principal_id UUID" in offer
    assert "row.acquisition_principal_id = p_acquisition_principal_id" in offer
    assert "p_acquisition_principal_id UUID" in practice
    assert "row.acquisition_principal_id = p_acquisition_principal_id" in practice


def test_practice_passage_and_window_are_server_derived():
    practice = _function("create_exercise_practice_service_session_v1")
    signature = practice.split(") RETURNS", 1)[0]
    assert "p_exact_passage" not in signature
    assert "p_opens_at" not in signature
    assert "p_closes_at" not in signature
    assert "source_evidence.exact_text" in practice
    assert "practice-window-v1-24h" in practice
    assert "opens_at := clock_timestamp()" in practice


def test_original_and_practice_confidence_reviews_are_separate_and_blind():
    freeze = _function("freeze_exercise_service_blind_review_set_v1")
    judgment = _function("submit_exercise_service_confidence_judgment_v1")
    complete = _function("complete_exercise_service_blind_review_v1")
    assert "original_source" in freeze
    assert "first_valid_practice" in freeze
    assert "source_confidence_assignment_id" in freeze
    assert "practice_confidence_assignment_id" in freeze
    assert "blind_coach" in judgment
    assert "dataset_eligible" not in judgment or "false" in judgment
    assert "source_judgment" in complete
    assert "practice_judgment" in complete
    assert "exercise_pair_judgments" not in complete
    assert "transcript" not in COACH_ROUTE.split(
        '"assignments": assignments', 1
    )[0] or "deliberately absent before reveal" in COACH_ROUTE
    assert '"evidence_kind"' not in COACH_ROUTE
    assert "confidence-blind-order-v1" in COACH_ROUTE


def test_coach_assignment_payload_omits_chronology():
    from routes.v2 import mlc3_first_client_coach as coach_route

    payload = coach_route._assignment_payload({
        "id": "11111111-1111-1111-1111-111111111111",
        "evidence_kind": "original_source",
        "start_offset_ms": 0,
        "duration_ms": 1000,
        "playback_reference_id": "33333333-3333-3333-3333-333333333333",
        "packet_sha256": "a" * 64,
        "taxonomy_version": "confidence-five-state-v1",
    }, None, "22222222-2222-2222-2222-222222222222")
    assert payload is not None
    assert "evidence_kind" not in payload
    assert "start_offset_ms" not in payload
    assert "duration_ms" not in payload
    assert payload["audio_ref"] == (
        "/api/v2/coach/mlc3/reviews/playback/"
        "33333333-3333-3333-3333-333333333333"
    )
    assert "object_key" not in str(payload)


def test_coach_blind_playback_is_opaque_and_server_extracted():
    assert "presigned_get_user_media_r2" not in COACH_ROUTE
    assert "get_user_media_r2_bytes" in COACH_ROUTE
    assert "load_authorized_blind_clip" in COACH_ROUTE
    assert 'mimetype="audio/wav"' in COACH_ROUTE
    assert "playback_reference_id" in COACH_ROUTE


def test_provider_write_is_reserved_and_verified_before_attachment():
    reserve = _function("reserve_exercise_practice_service_upload_v1")
    acknowledge = _function("ack_exercise_practice_service_upload_v1")
    finalize = _function("finalize_exercise_practice_service_media_v1")
    attach = _function("attach_exercise_practice_service_attempt_v1")
    assert "write_started" in reserve
    assert "p_attempt_index" not in reserve
    assert "practice-service-upload-session:" in reserve
    assert "allocated_attempt_index" in reserve
    assert 'request.form.get("attempt_index")' not in ROUTE
    assert "'r2', contract.practice_bucket" in reserve
    assert "write_acknowledged" in acknowledge
    assert "read_after_write_sha256" in finalize
    assert "practice_acquisition_receipt_id" in attach
    assert "transcription_run" in attach
    assert "row.status = 'finalized'" in attach
    assert "deleted_at IS NULL" in attach
    coach_reserve = _function("reserve_coach_guidance_service_upload_v1")
    coach_finalize = _function("finalize_coach_guidance_service_media_v1")
    assert "coach_guidance_upload_recoveries" in coach_reserve
    assert "read_after_write_sha256" in coach_finalize
    assert "coach_guidance_media_validity_events" in coach_finalize
    assert "independent_clean_media" in coach_finalize
    assert "result.status = 'attached'" in acknowledge
    assert "write_required" in ROUTE


def test_practice_transcription_has_exact_authorized_run_provenance():
    authorize = _function("authorize_exercise_practice_transcription_v1")
    dispatch = _function(
        "mark_exercise_practice_transcription_dispatched_v1"
    )
    finalize = _function("finalize_exercise_practice_transcription_v1")
    reconcile = _function("reconcile_exercise_practice_transcription_v1")
    reconcile_request = _function(
        "reconcile_exercise_practice_transcription_request_v1"
    )
    measurement = _function("record_exercise_practice_service_measurement_v1")
    for value in (
        "processing_audio_object_id",
        "exact_audio_sha256",
        "authorization_check_id",
        "request_sha256",
        "permit_sha256",
        "whisper-1",
        "disfluent-preservation-v1",
        "auto-detect-no-hint-v1",
        "whisper-verbose-word-timestamps-v1",
    ):
        assert value in authorize
    assert "require_exercise_service_current_authority_v1" in authorize
    assert "PRACTICE_TRANSCRIPTION_PERMIT_EXPIRED" in dispatch
    assert "mlc3-processing-audio-object:" in dispatch
    assert "processing_audio_object_deletion_events" in dispatch
    assert "clock_timestamp() > result.permit_expires_at" in finalize
    assert "mlc3-processing-audio-object:" in finalize
    assert "processing_audio_object_deletion_events" in finalize
    assert "expired_after_dispatch" in finalize
    assert "revoked_after_dispatch" in finalize
    assert "EXCEPTION WHEN raise_exception" in finalize
    assert "EXCEPTION WHEN OTHERS" not in finalize
    assert "MLC3_SERVICE_CONTRACT_NOT_ACTIVE" in finalize
    assert "outcome_uncommitted" in reconcile
    assert "does not require continuing service authority" in reconcile_request
    assert "response_sha256" in finalize
    assert "provider_error_code" in finalize
    assert '"p_terminal_status": "uncertain"' in ROUTE
    assert "SnippetTranscriptionProviderError" in ROUTE
    assert "mark_exercise_practice_transcription_dispatched" in ROUTE
    assert "reconcile_exercise_practice_transcription" in ROUTE
    assert "reconcile_exercise_practice_transcription_request" in ROUTE
    assert "transcription_run.run_sha256" in measurement
    assert "row.status = 'finalized'" in measurement
    assert 'transcription_run.get("status") == "finalized"' in ROUTE
    assert "canonical_output" in ROUTE
    assert '"p_occurred_at": capture_completed_at' in ROUTE
    assert any(
        dependency.code == "exercise_practice_transcription_runs"
        for dependency in DEPENDENCIES
    )


def test_lifecycle_events_do_not_conflate_delivery_and_render():
    for name in (
        "record_exercise_offer_service_event_v1",
        "record_exercise_practice_service_event_v1",
    ):
        body = _function(name)
        assert "delivery_prepared" in body
        assert "render_confirmed" in body
        assert "playback_started" in body
        assert "playback_completed" in body
        assert "EXERCISE_SERVICE_EVENT_SEQUENCE_INVALID" in body or (
            "PRACTICE_SERVICE_EVENT_SEQUENCE_INVALID" in body
        )
        assert "render_instance_id" in body
        assert "content_identity_sha256" in body
    assert "capture_reserved" in _function(
        "record_exercise_practice_service_event_v1"
    )
    assert "attempt_processed" in _function(
        "record_exercise_practice_service_event_v1"
    )
    guidance = _function("record_coach_guidance_service_event_v1")
    assert "delivered" in guidance
    assert "rendered" in guidance
    assert "played" in guidance
    assert "required_previous" in guidance
    assert "render_instance_id" in guidance
    signed_read = _function("resolve_coach_guidance_service_media_read_v1")
    assert signed_read.count("require_coach_guidance_service_media_live_v1") == 2
    assert "attachment_version_id" in signed_read
    assert "recipient_principal_id" in signed_read


def test_catalog_growth_creates_a_new_version_and_snapshot():
    publication = _function("publish_coach_guidance_service_exercise_v1")
    assert "independent_clean_media" in publication
    assert "contains_user_audio" in publication
    assert "INSERT INTO public.exercise_versions" in publication
    assert "INSERT INTO public.exercise_catalog_snapshots" in publication
    assert "INSERT INTO public.exercise_catalog_snapshot_items" in publication
    assert "source_attachment_version_id" in publication
    assert publication.count(
        "definition_source.language_code = p_language_code"
    ) == 2
    assert "published_definition.exercise_key = p_exercise_key" in publication
    assert "published_version.instruction_text" in publication


def test_general_guidance_can_target_any_selected_frozen_feedback_item():
    attachment = _function("create_coach_guidance_service_attachment_v1")
    assert (
        "p_attachment_class = 'mlc3_exercise'\n"
        "           AND (context->>'feedback_candidate_id')::UUID <>"
    ) in attachment
    assert "row.membership_id = p_feedback_membership_id" in attachment
    assert "row.candidate_id = p_feedback_candidate_id" in attachment
    assert "row.selected AND row.eligibility = 'eligible'" in attachment
    assert "offer.feedback_candidate_id <> p_feedback_candidate_id" in attachment
    assert "COACH_GUIDANCE_GENERAL_EXERCISE_FIELDS_FORBIDDEN" in attachment


def test_media_finalization_replay_is_exact_and_fail_closed():
    finalize = _function("finalize_coach_guidance_service_media_v1")
    assert "COACH_GUIDANCE_MEDIA_FINALIZATION_REPLAY_CONFLICT" in finalize
    assert "COACH_GUIDANCE_MEDIA_VALIDITY_REPLAY_CONFLICT" in finalize
    assert "row.event_sha256 = event_hash" in finalize
    assert "row.evidence_sha256 = event_hash" in finalize


def test_migration_reapply_drops_dependent_constraints_first():
    dependent = SQL.index(
        "DROP CONSTRAINT IF EXISTS exercise_service_offers_feedback_response_fk"
    )
    replay_identity = SQL.index(
        "DROP CONSTRAINT IF EXISTS "
        "feedback_v3_service_response_offer_identity_unique"
    )
    assert dependent < replay_identity
    for constraint in (
        "exercise_service_offers_selection_check",
        "exercise_service_offers_operation_mode_check",
        "exercise_service_offer_candidates_operation_mode_check",
        "exercise_service_offer_events_operation_mode_check",
    ):
        assert f"DROP CONSTRAINT IF EXISTS {constraint}" in SQL


def test_raw_measurements_never_create_improvement_or_dataset_labels():
    measurement = _function("record_exercise_practice_service_measurement_v1")
    validity = _function("record_exercise_practice_service_validity_v1")
    assert "raw_measurements" in measurement
    assert "safeguards" in measurement
    assert "improved" not in measurement
    assert "improved" not in validity
    assert "dataset_eligible" not in ROUTE or "False" in ROUTE
    assert 'route("/user/mlc3/training' not in ROUTE.lower()
    assert "extract_rushed_phrase_endings_n1" in ROUTE
    assert "acoustic_snapshot" not in ROUTE
    selection = _function("freeze_exercise_practice_service_selection_v1")
    assert selection.count("practice.validity_contract_version") >= 3


def test_service_playback_uses_authoritative_resolvers_and_strict_r2():
    for name in (
        "resolve_exercise_service_offer_read_v1",
        "resolve_exercise_practice_session_read_v1",
        "resolve_exercise_practice_media_read_v1",
        "resolve_exercise_confidence_media_read_v1",
    ):
        assert "require_" in _function(name)
    assert "presigned_get_user_media_r2" in ROUTE
    assert "presigned_get_coach_object_r2" in ROUTE
    assert "get_exercise_service_offer(" not in ROUTE
    assert "get_processing_audio_object(" not in COACH_ROUTE


def test_service_window_uses_fresh_current_authority_not_historical_permit():
    current = _function("require_exercise_service_current_authority_v1")
    practice = _function("require_exercise_practice_service_live_v1")
    offer_read = _function("resolve_exercise_service_offer_read_v1")
    assert "p_historical_authorization_check_id" in current
    assert "issue_exercise_service_authority_v1" in current
    assert "ALTER COLUMN checked_at SET DEFAULT clock_timestamp()" in SQL
    assert "require_exercise_service_current_authority_v1" in practice
    assert "require_practice_source_live_v1" not in practice
    assert "processing_audio_object_deletion_events" in practice
    assert "require_exercise_service_current_authority_v1" in offer_read
    offer_event = _function("record_exercise_offer_service_event_v1")
    assert offer_event.count("require_exercise_service_offer_live_v1") == 3


def test_expired_blind_assignments_get_immutable_successors():
    freeze = _function("freeze_exercise_service_blind_review_set_v1")
    live = _function("require_exercise_service_confidence_live_v1")
    assert "assignment_revision" in freeze
    assert "expired_unanswered_successor" in freeze
    assert "source_judged" in freeze
    assert "practice_judged" in freeze
    assert "supersedes_assignment_id" in freeze
    assert "newer.assignment_revision > row.assignment_revision" in live


def test_all_new_subject_relations_are_in_deletion_inventory():
    expected = {
        "mlc3_service_principal_allowlist",
        "feedback_v3_service_render_receipts",
        "feedback_v3_service_response_bindings",
        "exercise_service_acquisition_receipts",
        "exercise_practice_transcription_runs",
        "exercise_service_blind_review_sets",
        "exercise_service_confidence_assignments",
        "exercise_service_confidence_render_receipts",
        "exercise_service_confidence_judgments",
        "exercise_service_blind_reveal_grants",
        "exercise_service_blind_reveal_accesses",
    }
    registered = {dependency.relation for dependency in DEPENDENCIES}
    assert expected <= registered
    reviewer_edges = {
        "exercise_service_confidence_assignment_reviewers",
        "exercise_service_confidence_render_reviewers",
        "exercise_service_confidence_judgment_reviewers",
        "exercise_service_blind_review_set_reviewers",
        "exercise_service_blind_reveal_grant_reviewers",
        "exercise_service_blind_reveal_access_reviewers",
        "mlc3_service_principal_allowlist_approvers",
    }
    assert reviewer_edges <= {dependency.code for dependency in DEPENDENCIES}


@pytest.mark.parametrize(
    "table",
    (
        "mlc3_service_contracts",
        "mlc3_service_principal_allowlist",
        "feedback_v3_service_response_bindings",
        "feedback_v3_service_render_receipts",
        "exercise_service_acquisition_receipts",
        "exercise_service_blind_review_sets",
        "exercise_service_confidence_assignments",
        "exercise_service_confidence_render_receipts",
        "exercise_service_confidence_judgments",
        "exercise_service_blind_reveal_grants",
        "exercise_service_blind_reveal_accesses",
    ),
)
def test_new_tables_are_rls_and_runtime_read_only(table: str):
    assert f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY" in SQL
    assert "GRANT SELECT ON public.%I TO service_role" in SQL


def test_route_surface_is_hidden_and_has_no_learning_operations():
    assert ROUTE.count("@mlc3_pilot_required") == 12
    assert ROUTE.count("@require_auth") == 12
    for forbidden in (
        "/user/mlc3/dataset",
        "/user/mlc3/training",
        "/user/mlc3/evaluation",
        "/user/mlc3/promotion",
        "synthetic_",
    ):
        assert forbidden not in ROUTE.lower()
    assert "runtime_is_enabled()" in GUIDANCE_ROUTE
    assert "store_exact_object" in GUIDANCE_ROUTE
    assert "publish_coach_guidance_service_exercise" in GUIDANCE_ROUTE
