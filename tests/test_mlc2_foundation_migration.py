from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "add_mlc2_foundation.sql"
SQL = MIGRATION.read_text()


def _table(name: str) -> str:
    start = SQL.index(f"CREATE TABLE IF NOT EXISTS public.{name}")
    next_table = SQL.find("CREATE TABLE IF NOT EXISTS public.", start + 1)
    return SQL[start: next_table if next_table >= 0 else len(SQL)]


def test_manifest_appends_mlc2_foundation_as_0302():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert manifest[-1] == "0302\tadd_mlc2_foundation.sql"


def test_registry_is_table_authoritative_and_has_exactly_seven_surfaces():
    expected = {
        "confidence_classification",
        "correction_generation",
        "coach_comment_generation",
        "praise_generation",
        "praise_selection",
        "correction_selection",
        "ideal_text_generation",
    }
    seed = SQL[
        SQL.index("INSERT INTO public.ml_learning_surfaces"):
        SQL.index("CREATE TABLE IF NOT EXISTS public.ml_learning_surface_aliases")
    ]
    assert set(re.findall(r"\('([a-z_]+)',", seed)) == expected
    assert "CREATE TYPE ml_learning_surface" not in SQL
    assert "REFERENCES public.ml_learning_surfaces(id)" in SQL


def test_aliases_are_explicit_and_generic_moment_is_rejected():
    assert "('say_it_stronger', 'correction_generation', true" in SQL
    assert "('coach_comment_draft', 'coach_comment_generation', true" in SQL
    assert "('ideal_text', 'ideal_text_generation', true" in SQL
    assert "('moment_suggestion', NULL, false" in SQL
    enqueue = SQL[
        SQL.index("CREATE OR REPLACE FUNCTION public.enqueue_mlc2_outbox_event_v1"):
        SQL.index("CREATE OR REPLACE FUNCTION public.claim_mlc2_outbox_events_v1")
    ]
    assert "moment_suggestion is invalid for canonical writes" in enqueue


def test_semantic_boundaries_have_exact_locked_vocabularies():
    assert "('confident_voice'), ('great_formulation'), ('rewrite_clarity')" in SQL
    assert "('classify'), ('generate'), ('select')" in SQL
    for operation in (
        "replace", "lock", "unlock", "style_orange", "remove_orange", "none"
    ):
        assert f"'{operation}'" in _table("ml_product_operations")
    canonical = _table("ml_canonical_events")
    assert "feedback_family_id" in canonical
    assert "pipeline_stage_id" in canonical
    assert "product_operation_id" not in canonical


def test_paragraph_and_orange_decisions_exist_only_as_product_actions():
    actions = _table("ml_product_actions")
    judgments = _table("ml_judgments")
    for decision in (
        "paragraph_lock", "paragraph_leave_unlocked", "paragraph_unlock",
        "orange_apply", "orange_decline", "orange_remove",
    ):
        assert decision in actions
        assert decision not in judgments
    assert "REFERENCES public.ml_product_operations(id)" in actions


def test_speaker_split_is_speaker_disjoint_not_principal_disjoint():
    assignments = _table("ml_speaker_split_assignments")
    assert "speaker_id" in assignments
    assert "split_policy_version" in assignments
    assert "UNIQUE (speaker_id, split_policy_version)" in assignments
    assert "acquisition_principal_id" not in assignments
    split_function = SQL[
        SQL.index("CREATE OR REPLACE FUNCTION public.assign_ml_speaker_split_v1"):
        SQL.index("CREATE TABLE IF NOT EXISTS public.ml_product_legal_approvals")
    ]
    assert "digest(" in split_function
    assert "speaker-sha256-80-10-10-v1" in SQL


def test_consent_requires_documented_approval_and_two_purposes():
    policy = _table("ml_consent_policies")
    assert "product_legal_approval_id" in policy
    assert "required_for_service" in policy
    assert "bundled_ui" in policy
    purposes = _table("ml_consent_event_purposes")
    assert "personalized_coaching" in purposes
    assert "pooled_model_improvement" in purposes
    assert "6(1)(a)" in purposes
    assert "9(2)(a)" in purposes
    events = _table("ml_consent_events")
    assert "product_legal_approval_id" in events
    assert "accepted_copy_sha256" in events
    snapshot = _table("ml_consent_snapshots")
    assert "acquisition_principal_id" in snapshot
    assert "recording_attempt_id" in snapshot
    assert "take_id" in snapshot
    assert "ml_consent_snapshot_grant_fk" in snapshot
    assert "INSERT INTO public.ml_consent_policies" not in SQL
    grant = SQL[
        SQL.index("CREATE OR REPLACE FUNCTION public.record_mlc2_consent_grant_v1"):
        SQL.index("CREATE OR REPLACE FUNCTION public.record_mlc2_consent_withdrawal_v1")
    ]
    assert "consent does not match documented Product/legal approval" in grant
    assert "p_affirmative_action ->> 'copy_sha256'" in grant


def test_outbox_has_leased_at_least_once_delivery_and_atomic_finalization():
    outbox = _table("ml_outbox_events")
    assert "idempotency_key" in outbox
    assert "attempt_count" in outbox
    assert "lease_expires_at" in outbox
    claim = SQL[
        SQL.index("CREATE OR REPLACE FUNCTION public.claim_mlc2_outbox_events_v1"):
        SQL.index("CREATE OR REPLACE FUNCTION public.finalize_mlc2_outbox_event_v1")
    ]
    assert "FOR UPDATE SKIP LOCKED" in claim
    finalize = SQL[
        SQL.index("CREATE OR REPLACE FUNCTION public.finalize_mlc2_outbox_event_v1"):
        SQL.index("CREATE OR REPLACE FUNCTION public.fail_mlc2_outbox_event_v1")
    ]
    assert "INSERT INTO public.ml_canonical_events" in finalize
    assert "UPDATE public.ml_outbox_events" in finalize
    assert "source_outbox_event_id" in finalize


def test_envelope_binds_principal_speaker_consent_epoch_and_typed_payload():
    event = _table("ml_canonical_events")
    for required in (
        "learning_contract_version", "data_epoch", "learning_surface_id",
        "pipeline_stage_id", "acquisition_principal_id", "speaker_id",
        "consent_snapshot_id", "source_outbox_event_id", "payload_type",
        "payload", "source_event_id", "occurred_at",
    ):
        assert required in event
    assert "ml_canonical_event_speaker_principal_fk" in event
    assert "ml_canonical_event_consent_principal_fk" in event
    assert "ml_canonical_event_payload_type_check" in event


def test_rendered_exposure_is_client_confirmed_and_shadow_is_rejected():
    exposure = _table("ml_rendered_exposures")
    assert "client_rendered_at" in exposure
    assert "actor_principal_id" in exposure
    assert "render_instance_id" in exposure
    ack = SQL[
        SQL.index("CREATE OR REPLACE FUNCTION public.ack_mlc2_rendered_exposure_v1"):
        SQL.index("CREATE OR REPLACE FUNCTION public.reveal_ml_review_assignment_v1")
    ]
    assert "presentation.delivery_mode = 'shadow'" in ack
    assert "acknowledgement_token" in ack
    presentation = _table("ml_presentations")
    assert "delivery_mode <> 'shadow' OR evaluation_only" in presentation
    assert "evaluation_only = (delivery_mode = 'shadow')" not in presentation


def test_blind_review_requires_submission_before_reveal():
    assignment = _table("ml_review_assignments")
    assert "blind_packet_sha256" in assignment
    assert "blindness_policy_version" in assignment
    reveal = SQL[
        SQL.index("CREATE OR REPLACE FUNCTION public.reveal_ml_review_assignment_v1"):
        SQL.index("-- ── Immutability, access control")
    ]
    assert "event.event_kind = 'submitted'" in reveal
    assert "blind review may be revealed only after submission" in reveal


def test_practice_confidence_signals_are_separate_and_revealed_is_eval_only():
    judgments = _table("ml_judgments")
    assert "user_self_report" in judgments
    assert "blind_coach" in judgments
    assert "blind_peer" in judgments
    assert "professional_evaluation" in judgments
    for value in (
        "confident_yes", "confident_in_between", "confident_no",
        "confident_not_sure", "confident_audio_unclear",
        "rating_yes", "rating_in_between", "rating_no",
        "rating_not_sure", "rating_audio_unclear",
        "professional_yes", "professional_no", "professional_refine",
    ):
        assert value in judgments
    assert "training_eligibility = 'evaluation_only'" in judgments


def test_r2_hash_is_not_a_global_identity_and_verification_is_recorded():
    objects = _table("ml_object_artifacts")
    evidence = _table("ml_evidence_spans")
    assert "object_key               TEXT NOT NULL UNIQUE" in objects
    assert "sha256                   TEXT NOT NULL" in objects
    assert "sha256                   TEXT NOT NULL UNIQUE" not in objects
    assert "content_sha256           TEXT NOT NULL" in evidence
    assert "content_sha256           TEXT NOT NULL UNIQUE" not in evidence
    assert "ml_object_verifications" in SQL


def test_semantic_artifacts_cannot_be_used_as_prediction_storage():
    artifacts = _table("ml_semantic_artifacts")
    assert "'prediction'" not in artifacts
    assert "pipeline_stage_id = 'generate'" in artifacts
    assert "confidence_classification" not in artifacts[
        artifacts.index("ml_semantic_artifact_surface_type_check"):
    ]


def test_purge_is_append_only_and_traces_principal_and_speaker():
    requests = _table("ml_purge_requests")
    events = _table("ml_purge_events")
    assert "acquisition_principal_id" in requests
    assert "speaker_id" in requests
    assert "withdrawal_event_id" in requests
    assert "object_retained_shared" in events
    assert "lineage_invalidated" in events
    assert "'ml_purge_requests', 'ml_purge_events'" in SQL


def test_immutable_tables_are_rls_locked_and_release_training_stay_disabled():
    assert "ENABLE ROW LEVEL SECURITY" in SQL
    assert "REVOKE ALL ON TABLE public.%I FROM anon, authenticated" in SQL
    assert "GRANT SELECT ON TABLE public.%I TO service_role" in SQL
    assert "GRANT SELECT, INSERT ON TABLE public.%I TO service_role" not in SQL
    assert "GRANT SELECT, INSERT, UPDATE ON TABLE public.ml_outbox_events" not in SQL
    assert "reject_mlc2_immutable_mutation" in SQL
    epoch = _table("ml_contract_epochs")
    assert "dataset_creation_enabled   BOOLEAN NOT NULL DEFAULT false" in epoch
    assert "training_enabled           BOOLEAN NOT NULL DEFAULT false" in epoch
    assert "promotion_enabled          BOOLEAN NOT NULL DEFAULT false" in epoch
    assert "CREATE TABLE IF NOT EXISTS public.ml_dataset_releases" not in SQL
