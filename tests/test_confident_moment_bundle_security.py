import ast
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
        "CREATE OR REPLACE FUNCTION public.ack_confident_moment_bundle_item_render_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "ack_feedback_v3_service_render_v1" in render
    assert "a.canonical_feedback_presentation_id<>p_presentation_id" in render
    assert "INSERT INTO public.feedback_exposures" not in render


def test_coach_update_render_is_bound_to_the_exact_revision_and_surface():
    render = SQL.split(
        "CREATE OR REPLACE FUNCTION public.ack_feedback_language_revision_render_v1",
        1,
    )[1].split("END $$;", 1)[0]
    assert "artifact_id=d.revision_id" in render
    assert "learning_surface_id=(CASE revision.output_kind" in render
    assert "coach_comment_generation" in render
    assert "correction_generation" in render
    assert "praise_generation" in render
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


def test_canonical_ideal_text_helper_is_the_only_literal_root_writer():
    assert "p_expected_part_revision_id bigint" in SQL
    helper = SQL.split(
        "CREATE OR REPLACE FUNCTION public.transition_ideal_text_root_state_v1", 1
    )[1].split("END $$;", 1)[0]
    assert "UPDATE public.ideal_text_part" in helper
    assert "INSERT INTO public.ideal_text_part_revision" in helper
    outside = SQL.replace(helper, "")
    assert "UPDATE public.ideal_text_part SET" not in outside
    assert "PERFORM public.transition_ideal_text_root_state_v1" in outside
    assert "CONFIDENT_MOMENT_LEGACY_ACTIVATION_SHAPE_DRIFT" in outside
    assert "CONFIDENT_MOMENT_LEGACY_REMOVAL_SHAPE_DRIFT" in outside


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
    assert "source_binding.binding_state<>'active'" in guard
    assert "practice_binding.binding_state<>'active'" in guard
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
    for required in (
        "coach_guidance_reveal_accesses",
        "coach_guidance_reveal_grants",
        "ml_judgments",
        "actor_provenance='blind_coach'",
        "require_coach_guidance_reviewer_access_v1",
        "require_coach_guidance_assignment_live_v1",
        "candidate_output_sha256=public.feedback_candidate_output_sha256_v1",
    ):
        assert required in projection


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
        "publish_ideal_text_document_snapshot_v1",
        "accept_phase1_processing_authorization_v1",
        "mark_phase1_storage_object_purged_v1",
        "finalize_phase1_purge_v3",
    }
    expected = {
        ("services/first_client_repository.py", "ensure_service_enrollment", "ensure_mlc3_service_enrollment_v2"),
        ("services/first_client_repository.py", "freeze_feedback_v3_service_membership", "freeze_feedback_v3_service_membership_v1"),
        ("services/first_client_repository.py", "ack_feedback_v3_service_render", "ack_feedback_v3_service_render_v1"),
        ("services/db.py", "publish_ideal_text_document_snapshot", "publish_ideal_text_document_snapshot_v1"),
        ("services/processing_authorization.py", "accept", "accept_phase1_processing_authorization_v1"),
        ("services/data_purge.py", "_resolve_object", "mark_phase1_storage_object_purged_v1"),
        ("services/data_purge.py", "finalize", "finalize_phase1_purge_v3"),
    }
    actual: set[tuple[str, str, str]] = set()
    for path in ROOT.rglob("*.py"):
        relative = path.relative_to(ROOT)
        if "tests" in relative.parts or any(
            part in {"venv", ".venv", "build", "dist"} for part in relative.parts
        ):
            continue
        tree = ast.parse(path.read_text())
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
