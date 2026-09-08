from pathlib import Path

import pytest

from services.rooting_phrase_qualification_v1 import (
    RPQ_V1_RUNTIME_ENABLED,
    controls_for_state,
    runtime_is_enabled,
)


ROOT = Path(__file__).resolve().parents[1]
RPQ_SQL = (ROOT / "migrations/pending/add_rooting_phrase_qualification_v1.sql").read_text()
P1_SQL = (
    ROOT / "migrations/pending/add_mlc3_practice_foundation_restoration.sql"
).read_text()
P2_SQL = (
    ROOT
    / "migrations/pending/add_mlc3_fresh_offer_and_paired_review_restoration.sql"
).read_text()
V3_SQL = (
    ROOT / "migrations/pending/add_feedback_v3_serving_restoration.sql"
).read_text()
MANIFEST = (ROOT / "migrations/manifest.txt").read_text()


def test_runtime_and_all_persisted_surfaces_are_structurally_disabled():
    assert RPQ_V1_RUNTIME_ENABLED is False
    assert runtime_is_enabled() is False
    for sql in (RPQ_SQL, P1_SQL, P2_SQL, V3_SQL):
        assert "serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user)" in sql
        assert "dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)" in sql
    for filename in (
        "add_rooting_phrase_qualification_v1.sql",
        "add_mlc3_practice_foundation_restoration.sql",
        "add_mlc3_fresh_offer_and_paired_review_restoration.sql",
        "add_feedback_v3_serving_restoration.sql",
    ):
        assert filename not in MANIFEST


@pytest.mark.parametrize(
    ("state", "primary", "secondary", "coverage"),
    [
        (
            "eligible_direct",
            "lock_and_make_rooting_phrase",
            "lock_only",
            "ready",
        ),
        (
            "eligible_after_rerecord",
            "make_rooting_phrase",
            "not_now",
            "ready",
        ),
        ("pending_recording", "practice_this_phrase", None, "pending"),
        (
            "pending_owner_alignment_confirmation",
            "confirm_phrase_anchors_point",
            "reject_for_slide",
            "pending",
        ),
        ("blocked_semantic_mismatch", None, None, "pending"),
    ],
)
def test_qualitative_controls_never_surface_scores(
    state, primary, secondary, coverage
):
    controls = controls_for_state(state)
    assert (controls.primary_action, controls.secondary_action) == (primary, secondary)
    assert controls.coverage_state == coverage
    assert "score" not in repr(controls).lower()


def test_v3_budget_is_preserved_independently_of_root_coverage():
    assert "one relative-best confident voice item" in V3_SQL.lower()
    assert "vocal_coverage_complete" not in V3_SQL
    assert "root_phrase" not in V3_SQL
    assert "membership.take_index = 1" in V3_SQL
    assert "feedback_family = 'rewrite_clarity'" in V3_SQL
    assert "feedback_family = 'great_formulation'" in V3_SQL


def test_rpq_requires_exact_feedback_and_practice_lineage():
    for required in (
        "require_synthetic_root_content_live_v1",
        "offer_row.feedback_membership_id =",
        "content.feedback_membership_id",
        "offer_item.slide_index=content.slide_index",
        "offer_item.block_key=content.block_key",
        "source_offer_id",
        "selected_first_valid",
        "root-transcript-normalization-v1",
        "exact_bytes_sha256 = attempt.exact_audio_sha256",
        "response.response IS DISTINCT FROM 'confident_yes'",
        "source_correction_decision_id",
        "candidate.generated_output->>'quote'",
        "candidate.generated_output->>'proposed_text'",
        "candidate.generated_output->>'quote' = evidence.exact_text",
        "candidate.generated_output->>'proposed_text' =\n                        evidence.replacement_text",
        "later_decision.supersedes_id = decision.id",
        "decision.candidate_id = candidate.id",
        "decision.feedback_membership_id = membership.id",
        "feedback_membership_id IS NOT NULL",
        "feedback_exposure_id IS NOT NULL",
        "correction_decision_membership_candidate_fk",
        "correction_decision_exposure_candidate_fk",
        "FEEDBACK_EXACT_IDENTITY_REQUIRED",
        "decision.candidate_output_sha256 =",
        "feedback_candidate_output_sha256_v1(candidate.id)",
        "feedback-candidate-output-v1",
        "correction_decision_candidate_evidence_fk",
        "ROOT_MANAGER_EVIDENCE_MISMATCH",
        "revision.action = 'user_edit'",
        "require_exercise_assignment_authority_v1",
        "freeze_synthetic_root_semantic_input_v1",
        "require_practice_source_live_v1",
    ):
        assert required in RPQ_SQL
    for forbidden in (
        "INSERT INTO public.ml_judgments",
        "INSERT INTO public.ml_canonical_events",
        "INSERT INTO public.dataset_release",
    ):
        assert forbidden not in RPQ_SQL


def test_lock_root_replace_and_remove_are_distinct_retry_safe_actions():
    for action in (
        "'paragraph_lock'",
        "'root_activate'",
        "'root_replace'",
        "'root_remove'",
    ):
        assert action in RPQ_SQL
    assert "remove_synthetic_root_phrase_v1" in RPQ_SQL
    assert "ROOT_ACTIVATION_REPLAY_CONFLICT" in RPQ_SQL
    assert "ROOT_REMOVAL_REPLAY_CONFLICT" in RPQ_SQL
    assert "interaction_state_revision" in RPQ_SQL
    assert "UPDATE public.ideal_text_part" in RPQ_SQL
    assert "SET locked_at = clock_timestamp()" in RPQ_SQL
    assert "ROOT_CANONICAL_LOCK_FAILED" in RPQ_SQL
    assert "ROOT_CANONICAL_ROOT_FAILED" in RPQ_SQL


def test_core_read_reports_stable_paragraph_and_honest_slide_coverage():
    for required in (
        "get_synthetic_root_core_state_v1",
        "content_snapshot_id",
        "interaction_state_revision",
        "slide_minimum_ready",
        "slide_pending",
        "full_density",
        "phrase_start",
        "phrase_end",
    ):
        assert required in RPQ_SQL
    assert "fallback" not in RPQ_SQL.lower()


def test_practice_restoration_preserves_first_valid_and_deletion_boundaries():
    for required in (
        "pending_earlier_attempt",
        "selected_first_valid",
        "exercise_practice_upload_recoveries",
        "PRACTICE_REQUIRES_READ_COMMITTED",
        "require_practice_processing_authority_v1",
        "deleted_at IS NULL",
        "data_purge_requests",
    ):
        assert required in P1_SQL
    assert "storage_provider = 'local_synthetic'" in P1_SQL


def test_paired_review_preserves_blindness_and_five_distinct_answers():
    for answer in (
        "prefer_left",
        "prefer_right",
        "same",
        "not_sure",
        "audio_unusable",
    ):
        assert answer in P2_SQL
    assert "known_prior_context" in P2_SQL
    assert "exercise-reviewer-context:" in P2_SQL
    assert "chronology_revealed" in P2_SQL
    assert "EXERCISE_SERVICE_EXPOSURE_DISABLED" in P2_SQL
