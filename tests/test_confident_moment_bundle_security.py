from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations/pending/add_confident_moment_coaching_bundle_v1.sql").read_text()


def test_pending_migration_is_dark_rpc_only_and_unnumbered():
    assert "serves_user boolean NOT NULL DEFAULT false CHECK(NOT serves_user)" in SQL
    assert "dataset_eligible boolean NOT NULL DEFAULT false CHECK(NOT dataset_eligible)" in SQL
    assert "FORCE ROW LEVEL SECURITY" in SQL
    assert "FROM PUBLIC,anon,authenticated,service_role" in SQL
    assert "GRANT" not in SQL
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
    assert "learning_surface_id=(SELECT CASE revision_row.output_kind" in render
    assert "coach_comment_generation" in render
    assert "correction_generation" in render
    assert "praise_generation" in render


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
