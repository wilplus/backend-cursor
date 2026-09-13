import ast
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations/pending/add_confident_moment_coaching_bundle_v1.sql").read_text()


def test_pending_migration_is_dark_rpc_only_and_unnumbered():
    assert "serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user)" in SQL
    assert "dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible)" in SQL
    assert "FORCE ROW LEVEL SECURITY" in SQL
    assert "FROM PUBLIC,anon,authenticated,service_role" in SQL
    assert "GRANT EXECUTE ON FUNCTION public.project_confident_moment_bundles_v1(uuid,uuid,uuid) TO service_role" in SQL
    assert " TO anon" not in SQL and " TO authenticated" not in SQL
    assert "NOTIFY pgrst,'reload schema'" in SQL


def test_no_parallel_review_exposure_or_learning_system():
    assert "CREATE TABLE IF NOT EXISTS public.ml_" not in SQL
    assert "CREATE TABLE IF NOT EXISTS public.feedback_exposures" not in SQL
    assert "ack_feedback_v3_service_render_v1" in SQL
    assert "ack_mlc2_rendered_exposure_v1" in SQL
    assert "INSERT INTO public.ml_judgments" not in SQL
    assert "dataset_release" not in SQL


def test_exact_policy_and_response_fences_are_literal():
    assert "rooting-coverage-30-80-100-v1" in SQL
    assert "x.response='confident_yes'" in SQL
    assert "confident_in_between" in SQL
    assert "eligible_owner_proposal" in SQL
    assert "actor_provenance='blind_coach'" in SQL


def test_d5_prepared_presentation_is_not_a_render_or_response():
    preparation = SQL.split(
        "CREATE OR REPLACE FUNCTION public.prepare_confident_moment_bundle_v1", 1
    )[1].split("END $$;", 1)[0]
    assert "p_bundle_subject_candidate_id" in preparation
    assert "canonical_feedback_presentation_id" in preparation
    assert "INSERT INTO public.feedback_exposures" not in preparation
    assert "feedback_v3_service_render_receipts" not in preparation
    assert "feedback_v3_owner_responses" not in preparation
    assert "shown_at=" not in preparation


def test_d5_visible_render_reuses_the_canonical_v3_transition():
    render = SQL.split(
        "CREATE OR REPLACE FUNCTION public.ack_confident_moment_bundle_item_render_v3",
        1,
    )[1].split("END $$;", 1)[0]
    assert "ack_feedback_v3_service_render_v1" in render
    assert "bundle_subject_candidate_id=p_bundle_id" in render
    assert "a.canonical_feedback_presentation_id<>p_feedback_exposure_id" in render
    assert "'presentation_id'" not in render
    assert "confident-moment-bundle-item-render-v3" in render
    assert render.count("require_feedback_v3_service_membership_live_v1") == 3
    assert "m.document_snapshot_id<>a.document_snapshot_id" in render
    assert "INSERT INTO public.feedback_exposures" not in render
    assert "render_receipt_id" in render
    assert "r.id=r.feedback_exposure_id" in render


def test_d15_projection_exposes_exact_family_and_feedback_exposure_identity():
    projection = SQL.split(
        "CREATE OR REPLACE FUNCTION public.project_confident_moment_bundles_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "'feedback_family',attachment.feedback_family" in projection
    assert "'canonical_feedback_exposure_id',attachment.canonical_feedback_presentation_id" in projection
    assert "'family',attachment.feedback_family" in projection
    assert "'feedback_exposure',attachment.canonical_feedback_presentation_id" in projection


def test_coach_update_render_is_bound_to_the_exact_revision_and_surface():
    render = SQL.split(
        "CREATE OR REPLACE FUNCTION public.ack_feedback_language_revision_render_v3",
        1,
    )[1].split("END $$;", 1)[0]
    assert "artifact_id=d.revision_id" in render
    assert "learning_surface_id=(CASE revision.output_kind" in render
    assert "coach_comment_generation" in render
    assert "correction_generation" in render
    assert "praise_generation" in render
    assert "p_bundle_attachment_id" in render
    assert "bundle_subject_candidate_id=p_bundle_id" in render
    assert "feedback-language-revision-render-v3" in render
    assert "e.idempotency_key<>p_idempotency_key" in render
    assert "attached_candidate_id=revision.feedback_candidate_id" in render
    assert "feedback-language-delivery-subject:" in render
    assert "feedback-language-revision-head:" in render
    assert "successor.supersedes_delivery_id=delivery.id" in render
    assert "successor.supersedes_id=revision.id" in render


def test_projection_unread_is_derived_from_canonical_render_exposure():
    projection = SQL.split(
        "CREATE OR REPLACE FUNCTION public.project_confident_moment_bundles_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "'render_state'" in projection
    assert "JOIN public.ml_presentations p ON p.artifact_id=d.revision_id" in projection
    assert "LEFT JOIN public.ml_rendered_exposures e" in projection
    assert "unread:=current_rendered_exposure_id IS NULL" in projection
    assert "'rendered_exposure',current_rendered_exposure_id" in projection
    assert "d.delivery_state LIKE 'scheduled_%'" not in projection


def test_only_reviewed_atomic_boundaries_write_ideal_text_parts():
    assert "p_expected_part_revision_id bigint" in SQL
    helper = SQL.split(
        "CREATE OR REPLACE FUNCTION public.transition_ideal_text_root_state_v1", 1
    )[1].split("END $$;", 1)[0]
    assert "UPDATE public.ideal_text_part" in helper
    assert "INSERT INTO public.ideal_text_part_revision" in helper
    outside = SQL.replace(helper, "")
    update = outside.split(
        "CREATE OR REPLACE FUNCTION public.apply_confident_moment_bundle_text_update_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "UPDATE public.ideal_text_part SET" in update
    assert "INSERT INTO public.ideal_text_part_revision" in update
    outside = outside.replace(update, "")
    ordinary = outside.split(
        "CREATE OR REPLACE FUNCTION public.compare_and_set_user_ideal_edit_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "UPDATE public.ideal_text_part SET" in ordinary
    assert "INSERT INTO public.ideal_text_part_revision" in ordinary
    outside = outside.replace(ordinary, "")
    assert "UPDATE public.ideal_text_part SET" not in outside
    assert "PERFORM public.transition_ideal_text_root_state_v1" in outside
    assert "CONFIDENT_MOMENT_LEGACY_ACTIVATION_SHAPE_DRIFT" in outside
    assert "CONFIDENT_MOMENT_LEGACY_REMOVAL_SHAPE_DRIFT" in outside


def test_d25_lock_helper_has_closed_three_phase_order():
    helper = SQL.split(
        "CREATE OR REPLACE FUNCTION public.lock_confident_moment_position_100_v1",
        1,
    )[1].split("END $$;", 1)[0]
    phase_a = helper.index("^root-block:")
    phase_b = helper.index("^ideal-root-transition:")
    phase_c = helper.index("^ideal-text-part-revision-head:")
    assert phase_a < phase_b < phase_c
    assert helper.count("pg_advisory_xact_lock") == 3
    assert helper.count("SELECT DISTINCT value") == 3
    assert helper.count("ORDER BY convert_to(value,'UTF8')") == 3


def test_coach_publish_uses_prewrite_authority_and_postrevision_source_guard():
    body = SQL.split(
        "CREATE OR REPLACE FUNCTION public.publish_confident_moment_coach_feedback_language_v1",
        1,
    )[1].split("END $$;", 1)[0]
    revision_call = body.index("record_feedback_language_coach_revision_v2")
    post_guard = body.index("require_feedback_language_coach_source_live_v1")
    assert body.index("require_coach_guidance_reviewer_access_v1") < revision_call
    assert body.index("require_coach_guidance_assignment_live_v1") < revision_call
    assert body.index("require_mlc3_service_access_v2") < revision_call
    assert revision_call < post_guard
    assert "created_revision_id,a.acquisition_principal_id,a.feedback_membership_id" in body
    assert "output_hash:=public.feedback_candidate_output_sha256_v1" in body


def test_d20_d24_structural_storage_is_present_and_non_learning():
    required_tables = (
        "ideal_text_user_edit_cas_operations",
        "confident_moment_bundle_text_update_bindings",
        "confident_moment_coach_authorability_inventories",
        "confident_moment_coach_authorability_items",
        "confident_moment_blind_assignment_bindings",
        "confident_moment_coach_wording_authority_bindings",
        "feedback_language_delivery_materialization_jobs",
    )
    for table in required_tables:
        definition = SQL.split(f"CREATE TABLE IF NOT EXISTS public.{table}", 1)[1]
        definition = definition.split(";", 1)[0]
        assert "serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user)" in definition
        assert "dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible)" in definition
    assert "CHECK(source_document_snapshot_id=result_document_snapshot_id)" in SQL
    assert "user_text_revision bigint NULL" in SQL
    for action in (
        "owner_part_created",
        "owner_part_text_updated",
        "owner_part_reordered",
        "owner_part_text_updated_and_reordered",
        "owner_part_removed",
    ):
        assert action in SQL


def test_d6_root_source_matrix_and_practice_guard_are_closed():
    assert "root_phrase_product_action_v2_source_matrix_check" in SQL
    assert "interaction_action='activate_automatic_root'" in SQL
    assert "interaction_action='save_owner_selected_root'" in SQL
    assert "interaction_action IN('lock_current_root','unlock_current_root','remove_current_root')" in SQL
    assert "interaction_action='restore_previous_root'" in SQL
    guard = SQL.split(
        "CREATE OR REPLACE FUNCTION public.require_root_phrase_practice_source_live_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "least(lineage.recording_attempt_id,attempt.processing_recording_attempt_id)" in guard
    assert "greatest(lineage.recording_attempt_id,attempt.processing_recording_attempt_id)" in guard
    assert "require_practice_source_live_v1" in guard
    assert "require_exercise_service_offer_live_v1" in guard
    assert guard.count("resolve_confident_moment_target_speaker_binding_v1") == 2
    assert "source_binding.speaker_id<>practice_binding.speaker_id" in guard
    assert "ROOTING_PHRASE_SPEAKER_IDENTITY_INVALID" in guard
    assert "INSERT INTO public.exercise_pair_revisions" not in guard
    assert "INSERT INTO public.ml_judgments" not in guard


def test_d11_secure_projection_is_database_owned_and_denylisted():
    projection = SQL.split(
        "CREATE OR REPLACE FUNCTION public.project_confident_moment_bundles_v1", 1
    )[1].split("END $$;", 1)[0]
    for lock in (
        "mlc3-rollout-policy-v2",
        "mlc3-service-principal:",
        "confident-moment-project-inventory:",
        "confident-moment-take-inventory:",
        "feedback-v3-membership-inventory:",
        "feedback-v3-membership-current:",
        "ideal-text-document-head:",
        "ideal-text-document-snapshot:",
        "mlc3-speaker-attempt:",
        "mlc3-processing-audio-object:",
        "confident-moment-bundle-subject:",
        "root-block:",
        "feedback-language-candidate:",
        "feedback-language-delivery-subject:",
        "feedback-language-revision-head:",
    ):
        assert lock in SQL
    assert "CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED" in projection
    assert "require_mlc3_service_access_v2" in projection
    assert "require_feedback_v3_service_membership_live_v1" in projection
    assert "'exercise',NULL" in projection
    for forbidden in ("candidate_score", "rank_evidence", "coach_judgment", "qualification_state", "authorization_receipt_id"):
        assert f"'{forbidden}'" not in projection


def test_d11_revision_and_delivery_heads_are_immutable_chains():
    assert "feedback_language_coach_revision_original_idx" in SQL
    assert "feedback_language_coach_revision_supersedes_idx" in SQL
    assert "feedback_language_delivery_original_v2_idx" in SQL
    assert "feedback_language_delivery_successor_v2_idx" in SQL
    assert "supersedes_delivery_id" in SQL
    assert "delivery_explicitly_invalidated" in SQL
    assert "record_feedback_language_coach_revision_v2" in SQL
    assert "transition_feedback_language_delivery_v2" in SQL


def test_d11_exact_replay_precedes_expected_head_comparison():
    revision_v1 = SQL.split(
        "CREATE OR REPLACE FUNCTION public.record_feedback_language_coach_revision_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert revision_v1.index("IF r.id IS NOT NULL THEN") < revision_v1.index(
        "IF p_supersedes_revision_id IS NOT NULL"
    )
    revision = SQL.split(
        "CREATE OR REPLACE FUNCTION public.record_feedback_language_coach_revision_v2",
        1,
    )[1].split("END $$;", 1)[0]
    assert revision.index("SELECT * INTO replay_revision") < revision.index(
        "current_head IS DISTINCT FROM p_expected_current_revision_id"
    )
    assert "current_head IS DISTINCT FROM replay_revision.id" in revision
    assert "replay_revision.revision_sha256<>requested_sha256" in revision

    delivery = SQL.split(
        "CREATE OR REPLACE FUNCTION public.transition_feedback_language_delivery_v2",
        1,
    )[1].split("END $$;", 1)[0]
    assert delivery.index("IF result.id IS NOT NULL THEN") < delivery.index(
        "current_delivery.id IS DISTINCT FROM p_expected_current_delivery_id"
    )
    assert "current_delivery.id IS DISTINCT FROM result.id" in delivery
    assert "result.delivery_sha256<>delivery_hash" in delivery


def test_d11_legacy_root_global_order_is_injected_and_verified():
    rewrite = SQL.split("DO $$ DECLARE body text; original text; BEGIN", 1)[1].split(
        "CREATE OR REPLACE FUNCTION public.record_root_phrase_product_action_v2", 1
    )[0]
    assert rewrite.count("D11 legacy root writer: global inventory before root block") >= 2
    assert rewrite.count("lock_confident_moment_inventory_v1") >= 2
    assert "position('root-block:' in installed.body)" in SQL


def test_canonical_tables_revoke_every_direct_table_privilege():
    assert (
        "REVOKE ALL ON TABLE public.feedback_revisions,"
        "public.root_phrase_product_actions FROM PUBLIC,anon,authenticated,service_role"
    ) in SQL


def test_d11_external_writer_registry_is_exact_and_fail_closed():
    signatures = (
        "freeze_synthetic_feedback_v3_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text,text)",
        "freeze_feedback_v3_service_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text)",
        "publish_ideal_text_document_snapshot_v1(text,text,uuid,uuid,uuid,integer,bigint,text,jsonb,jsonb)",
        "ack_feedback_v3_service_render_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,timestamptz,text,text)",
        "register_mlc3_general_rollout_v2(uuid,uuid,jsonb,jsonb,uuid,timestamptz,text)",
        "halt_mlc3_service_rollout_v1(text,text)",
        "ensure_mlc3_service_enrollment_v2(uuid,uuid,text)",
        "activate_phase1_policy_v1(text,text,text)",
        "accept_phase1_processing_authorization_v1(uuid,text,text,text,text,text,text,boolean,text,text,text,timestamptz,text)",
        "mark_phase1_storage_object_purged_v1(uuid,text,uuid,text,text,text,text)",
        "finalize_phase1_purge_v3(uuid,text)",
    )
    for signature in signatures:
        assert f"public.{signature}" in SQL
    for marker in (
        "D11 writer: synthetic membership",
        "D11 writer: service membership",
        "D11 writer: document snapshot",
        "D11 writer: canonical render",
        "D11 writer: rollout revision",
        "D11 writer: rollout halt",
        "D11 writer: enrollment",
        "D11 writer: policy activation",
        "D11 writer: authorization receipt",
        "D11 writer: object purge",
        "D11 writer: purge finalize",
    ):
        assert marker in SQL
    assert "CONFIDENT_MOMENT_WRITER_REGISTRY_DRIFT" in SQL
    assert "CONFIDENT_MOMENT_WRITER_OVERLOAD_DRIFT" in SQL


def test_d11_trigger_registry_and_ordered_leaf_serializers_are_closed():
    for trigger in (
        "confident_moment_projection_item_lineage_v1",
        "coach_ideal_text_advances_document_generation",
        "user_ideal_edit_advances_document_generation",
        "ideal_text_part_advances_document_generation",
        "ready_take_advances_ideal_text_document_generation",
        "data_purge_requests_mlc3_service_serialization",
        "processing_audio_deletion_mlc3_serialization",
        "processing_audio_object_mlc3_serialization",
        "feedback_v3_membership_complete",
    ):
        assert f"'{trigger}'" in SQL
    assert "D11 trigger writer: document generation" in SQL
    assert "D11 trigger writer: purge request" in SQL
    assert "D11 trigger writer: audio leaf" in SQL
    assert "CONFIDENT_MOMENT_TRIGGER_REGISTRY_DRIFT" in SQL
    assert SQL.index("'mlc3-speaker-attempt:'") < SQL.index(
        "'mlc3-processing-audio-object:'"
    )


def test_d11_projection_revalidates_blind_coach_and_delivery_authority():
    projection = SQL.split(
        "CREATE OR REPLACE FUNCTION public.project_confident_moment_bundles_v1", 1
    )[1].split("END $$;", 1)[0]
    shared_guard = SQL.split(
        "CREATE OR REPLACE FUNCTION public.require_feedback_language_coach_source_live_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "require_feedback_language_coach_source_live_v1" in projection
    for required in (
        "coach_guidance_reveal_accesses",
        "coach_guidance_reveal_grants",
        "coach_guidance_reveal_grant_judgments",
        "coach_guidance_review_frame_items",
        "coach_inline_source_roles",
        "ml_judgments",
        "actor_provenance='blind_coach'",
        "require_coach_guidance_reviewer_access_v1",
        "require_coach_guidance_assignment_live_v1",
        "feedback_candidate_output_sha256_v1(revision_row.feedback_candidate_id)=p_candidate_output_sha256",
    ):
        assert required in shared_guard


def test_d11_delivery_locks_source_and_target_and_revalidates_currentness():
    delivery = SQL.split(
        "CREATE OR REPLACE FUNCTION public.transition_feedback_language_delivery_v2",
        1,
    )[1].split("END $$;", 1)[0]
    assert "VALUES(membership.take_id),(p_target_take_id)" in delivery
    assert "ORDER BY id" in delivery
    assert "require_feedback_v3_service_membership_live_v1" in delivery
    assert "require_coach_guidance_reviewer_access_v1" in delivery
    assert "require_coach_guidance_assignment_live_v1" in delivery
    assert "actor_provenance='blind_coach'" in delivery


def test_d11_runtime_rpc_caller_registry_is_exact():
    affected = {
        "ensure_mlc3_service_enrollment_v2",
        "freeze_feedback_v3_service_membership_v1",
        "ack_feedback_v3_service_render_v1",
        "record_confident_moment_bundle_family_response_v1",
        "publish_ideal_text_document_snapshot_v1",
        "accept_phase1_processing_authorization_v1",
        "mark_phase1_storage_object_purged_v1",
        "finalize_phase1_purge_v3",
    }
    expected = {
        ("services/first_client_repository.py", "ensure_service_enrollment", "ensure_mlc3_service_enrollment_v2"),
        ("services/first_client_repository.py", "freeze_feedback_v3_service_membership", "freeze_feedback_v3_service_membership_v1"),
        ("services/first_client_repository.py", "ack_feedback_v3_service_render", "ack_feedback_v3_service_render_v1"),
        ("services/confident_moment_bundle_repository.py", "record_family_response", "record_confident_moment_bundle_family_response_v1"),
        ("services/db.py", "publish_ideal_text_document_snapshot", "publish_ideal_text_document_snapshot_v1"),
        ("services/processing_authorization.py", "accept", "accept_phase1_processing_authorization_v1"),
        ("services/data_purge.py", "_resolve_object", "mark_phase1_storage_object_purged_v1"),
        ("services/data_purge.py", "finalize", "finalize_phase1_purge_v3"),
    }
    actual: set[tuple[str, str, str]] = set()
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if "tests" in relative.parts or any(
            part in {"venv", ".venv", ".venv-ci", "build", "dist"}
            for part in relative.parts
        ):
            continue
        with tokenize.open(path) as source:
            tree = ast.parse(source.read(), filename=str(path))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "rpc"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value in affected
            ):
                continue
            owner: ast.AST = node
            while owner in parents and not isinstance(
                owner, (ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                owner = parents[owner]
            actual.add((relative.as_posix(), getattr(owner, "name", "<module>"), node.args[0].value))
    assert actual == expected
    monitor = (ROOT / "scripts/monitor_mlc3_general_service.py").read_text()
    assert monitor.count("halt_mlc3_service_rollout_v1") == 1


def test_bundle_text_update_binding_is_part_of_root_action_identity():
    sql = SQL.lower()
    assert "source_text_update_binding_id uuid" in sql
    assert "r.source_text_update_binding_id is distinct from p_source_text_update_binding_id" in sql
    assert "'text_update_binding',p_source_text_update_binding_id" in sql
    assert "source_ideal_text_revision_id,source_text_update_binding_id,source_target_speaker_binding_id" in sql


def test_d29_d37_delivery_scheduler_contract_is_closed_and_dark():
    for table in (
        "feedback_language_delivery_job_claim_attempts",
        "feedback_language_delivery_job_claim_heads",
        "feedback_language_delivery_job_due_heads",
        "feedback_language_delivery_scan_runs",
        "feedback_language_delivery_stalled_scan_halt_receipts",
    ):
        assert f"CREATE TABLE IF NOT EXISTS public.{table}" in SQL
    assert "CREATE INDEX IF NOT EXISTS feedback_language_delivery_due_pending_idx" in SQL
    scanner = SQL.split(
        "CREATE OR REPLACE FUNCTION public.scan_due_feedback_language_delivery_jobs_v1", 1
    )[1].split("END $$;", 1)[0]
    assert "p_limit IS DISTINCT FROM 3" in scanner
    assert "ORDER BY h.next_probe_at,h.job_id LIMIT 3" in scanner
    assert "FOR UPDATE NOWAIT" in scanner
    assert "SKIP LOCKED" not in scanner
    assert "contention_nowait_count" in scanner
    assert "currentness_miss_count" in scanner
    assert "CONFIDENT_MOMENT_DELIVERY_SCAN_SERVER_BUDGET_EXCEEDED" in scanner
    assert "require_mlc3_service_access_v2" not in scanner
    assert "DROP FUNCTION IF EXISTS public.claim_due_feedback_language_delivery_jobs_v1" in SQL
    assert "dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible)" in SQL


def test_d29_core_v2_has_exact_snapshot_shape_and_database_hash():
    core = SQL.split(
        "CREATE OR REPLACE FUNCTION public.read_ideal_text_document_core_v2", 1
    )[1].split("END $$;", 1)[0]
    for key in (
        "'id'", "'arc_id'", "'actor_id'", "'acquisition_principal_id'",
        "'project_id'", "'source_take_session_id'", "'version'",
        "'source_generation'", "'source_fingerprint_sha256'", "'payload_sha256'",
        "'payload'", "'enrichment_seed'", "'supersedes_id'", "'created_at'",
    ):
        assert key in core
    assert "YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"" in core
    assert "read_sha256" in core
    assert "to_jsonb(s)" not in core and "to_jsonb(snapshot)" not in core


def test_d43_source_playback_authority_is_internal_exact_and_bounded():
    body = SQL.split(
        "CREATE OR REPLACE FUNCTION public.resolve_confident_moment_source_playback_authority_v1",
        1,
    )[1].split("END $$;", 1)[0]
    for token in (
        "pg_try_advisory_xact_lock",
        "'lock_timeout','50ms'",
        "processing_audio_object_deletion_events",
        "data_purge_requests",
        "byte_size BETWEEN 1 AND 26214400",
        "require_mlc3_service_access_v2",
        "require_feedback_v3_service_membership_live_v1",
        "'confident-moment-source-playback-authority-v1'",
        "'authority_sha256'",
        "'dataset_eligible',false",
    ):
        assert token in body
    assert "presigned" not in body.lower()
    assert "INSERT INTO" not in body and "UPDATE public." not in body
    assert (
        "GRANT EXECUTE ON FUNCTION public.resolve_confident_moment_source_playback_authority_v1(uuid,uuid,uuid) TO service_role"
        in SQL
    )


def test_d43_exercise_correlation_has_closed_family_scope_and_no_writes():
    body = SQL.split(
        "CREATE OR REPLACE FUNCTION public.resolve_confident_moment_exercise_offer_v1",
        1,
    )[1].split("END $$;", 1)[0]
    for token in (
        "family<>'confident_voice'",
        "a.bundle_subject_kind<>'confidence_anchor'",
        "feedback_v3_service_response_bindings",
        "require_feedback_v3_service_response_v1",
        "require_exercise_service_offer_live_v1",
        "'confident-moment-exercise-correlation-v2'",
        "'status','not_supplied'",
        "'status','available'",
        "'dataset_eligible',false",
    ):
        assert token in body
    assert "INSERT INTO" not in body and "UPDATE public." not in body


def test_d43_owner_decision_is_persisted_and_changes_projection_identity():
    projection = SQL.split(
        "CREATE OR REPLACE FUNCTION public.project_confident_moment_bundles_v1", 1
    )[1].split("END $$;", 1)[0]
    assert "derive_confident_moment_owner_decision_v1" in projection
    assert "'owner_decisions'" in projection
    assert "'owner_decision',owner_decision" in projection
    assert "ADD COLUMN IF NOT EXISTS owner_decision jsonb NULL" in SQL
    assert "confident_moment_owner_decision_bindings" in projection


def test_d46_emit_authorization_is_stateless_closed_and_rederives_authority():
    body = SQL.split(
        "CREATE OR REPLACE FUNCTION public.authorize_confident_moment_source_playback_emit_v1",
        1,
    )[1].split("END $$;", 1)[0]
    for token in (
        "resolve_confident_moment_source_playback_authority_v1",
        "p_expected_authority_sha256",
        "p_buffered_bytes_sha256",
        "p_playback_request_id",
        "'confident-moment-source-playback-emit-v1'",
        "'emit_authorized',true",
        "'emit_authorization_sha256'",
        "'dataset_eligible',false",
        "CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED",
        "CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID",
    ):
        assert token in body
    assert "INSERT INTO" not in body
    assert "UPDATE public." not in body
    assert "DELETE FROM" not in body
    assert "expires_at" not in body
    assert (
        "GRANT EXECUTE ON FUNCTION public.authorize_confident_moment_source_playback_emit_v1(uuid,uuid,uuid,text,text,uuid) TO service_role"
        in SQL
    )


def test_d48_exercise_correlation_and_practice_guard_bind_exact_speaker_ids():
    correlation = SQL.split(
        "CREATE OR REPLACE FUNCTION public.resolve_confident_moment_exercise_offer_v1",
        1,
    )[1].split("END $$;", 1)[0]
    for token in (
        "source_target_speaker_binding_id",
        "resolve_confident_moment_target_speaker_binding_v1",
        "source_binding_result",
    ):
        assert token in correlation
    not_supplied = correlation.split("'status','not_supplied'", 1)[1].split("RETURN", 1)[0]
    assert "source_target_speaker_binding_id" not in not_supplied
    guard = SQL.split(
        "CREATE OR REPLACE FUNCTION public.require_root_phrase_practice_source_live_v1",
        1,
    )[1].split("END $$;", 1)[0]
    for token in (
        "resolve_confident_moment_exercise_offer_v1",
        "correlation->>'source_target_speaker_binding_id'",
        "practice_result",
        "source_result",
        "practice_binding.acquisition_principal_id<>p_acquisition_principal_id",
        "CONFIDENT_MOMENT_PROJECTION_INVALID",
    ):
        assert token in guard


def test_d49_owner_decision_binding_is_exact_append_only_and_projection_owned():
    assert "CREATE TABLE IF NOT EXISTS public.confident_moment_owner_decision_bindings" in SQL
    assert "UNIQUE(bundle_attachment_id)" in SQL
    assert "'confident_moment_owner_decision_bindings'" in SQL
    assert "t||'_append_only'" in SQL
    assert "'confident-moment-owner-decision:'" in SQL
    projection = SQL.split(
        "CREATE OR REPLACE FUNCTION public.project_confident_moment_bundles_v1", 1
    )[1].split("END $$;", 1)[0]
    assert "confident_moment_owner_decision_bindings" in projection
    assert "feedback_v3_service_response_bindings b WHERE" not in projection
    assert "'feedback_language_shape_version','feedback-language-items-v2'" in projection


def test_d49_owner_decision_writers_are_in_the_closed_overload_registry():
    registry = SQL.split("expected_functions text[]:=ARRAY[", 1)[1].split(
        "];\n signature text;", 1
    )[0]
    for signature in (
        "public.record_feedback_human_decision_v1(uuid,uuid,uuid,text,text,text,text,text)",
        "public.record_feedback_human_decision_v1(uuid,uuid,uuid,uuid,uuid,uuid,text,text,text,text)",
        "public.record_confident_moment_bundle_family_response_v1(uuid,uuid,uuid,uuid,uuid,text,text)",
    ):
        assert registry.count(signature) == 1

    overload_names = SQL.split("procedure.proname=ANY(ARRAY[", 1)[1].split("]);", 1)[0]
    assert overload_names.count("'record_feedback_human_decision_v1'") == 1
    assert overload_names.count("'record_confident_moment_bundle_family_response_v1'") == 1


def test_d49_canonical_speaker_resolver_is_the_only_binding_currentness_rule():
    resolver = SQL.split(
        "CREATE OR REPLACE FUNCTION public.resolve_confident_moment_target_speaker_binding_v1",
        1,
    )[1].split("END $$;", 1)[0]
    for token in (
        "CONFIDENT_MOMENT_TARGET_SPEAKER_INVALID",
        "supersedes_revision_id=r.id",
        "supersedes_binding_id=b.id",
        "speaker_identity_status='resolved'",
        "b.clip_id=p_clip_id",
        "b.practice_attempt_id=p_practice_attempt_id",
        "'confident-moment-target-speaker-binding-v1'",
    ):
        assert token in resolver
    correlation = SQL.split(
        "CREATE OR REPLACE FUNCTION public.resolve_confident_moment_exercise_offer_v1", 1
    )[1].split("END $$;", 1)[0]
    guard = SQL.split(
        "CREATE OR REPLACE FUNCTION public.require_root_phrase_practice_source_live_v1", 1
    )[1].split("END $$;", 1)[0]
    assert "resolve_confident_moment_target_speaker_binding_v1" in correlation
    assert guard.count("resolve_confident_moment_target_speaker_binding_v1") == 2


def test_d49_practice_guard_precedes_root_lock_and_timeout_claim_is_truthful():
    root = SQL.split(
        "CREATE OR REPLACE FUNCTION public.record_root_phrase_product_action_v2", 1
    )[1].split("END $$;", 1)[0]
    first_guard = root.index("require_root_phrase_practice_source_live_v1")
    first_root_lock = root.index("'root-block:'")
    assert first_guard < first_root_lock
    playback = SQL.split(
        "CREATE OR REPLACE FUNCTION public.resolve_confident_moment_source_playback_authority_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "set_config('statement_timeout'" not in playback
    assert "pg_try_advisory_xact_lock" in playback
    assert "FOR SHARE NOWAIT" in playback


def test_root_only_ideal_text_updates_do_not_invalidate_semantic_snapshot():
    body = SQL.split(
        "CREATE OR REPLACE FUNCTION public.advance_ideal_text_document_generation_v1",
        1,
    )[1].split("END $$;", 1)[0]
    root_only_guard = body.split(
        "IF TG_TABLE_NAME='ideal_text_part' AND TG_OP='UPDATE' THEN", 1
    )[1].split("SELECT capability_id INTO cap", 1)[0]
    assert "NEW.text IS NOT DISTINCT FROM OLD.text" in root_only_guard
    assert "NEW.ord IS NOT DISTINCT FROM OLD.ord" in root_only_guard
    assert "RETURN NEW" in root_only_guard
