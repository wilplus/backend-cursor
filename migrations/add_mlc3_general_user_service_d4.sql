-- MLC-3 General-User Service Rollout D4 -- release migration 0326.
--
-- The migration is deliberately dark. It creates the rollout-aware access,
-- enrollment, speaker and capacity provenance required for a later reviewed
-- activation, but seeds only a disabled rollout. Dataset, training,
-- evaluation and promotion behavior is not created or enabled here.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.processing_recording_attempts'::regclass
           AND conname = 'processing_recording_attempts_id_principal_key'
    ) THEN
        ALTER TABLE public.processing_recording_attempts
            ADD CONSTRAINT processing_recording_attempts_id_principal_key
            UNIQUE (id, acquisition_principal_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.processing_audio_objects'::regclass
           AND conname = 'processing_audio_objects_id_principal_attempt_key'
    ) THEN
        ALTER TABLE public.processing_audio_objects
            ADD CONSTRAINT processing_audio_objects_id_principal_attempt_key
            UNIQUE (id, acquisition_principal_id, recording_attempt_id);
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.mlc3_service_cohort_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cohort_version TEXT NOT NULL CHECK (length(btrim(cohort_version)) > 0),
    member_count INTEGER NOT NULL CHECK (member_count >= 0),
    maximum_member_count INTEGER NOT NULL CHECK (
        maximum_member_count BETWEEN 1 AND 10000
        AND member_count <= maximum_member_count
    ),
    membership_sha256 TEXT NOT NULL CHECK (
        membership_sha256 ~ '^[0-9a-f]{64}$'
    ),
    activation_opens_at TIMESTAMPTZ NOT NULL,
    activation_closes_at TIMESTAMPTZ NOT NULL CHECK (
        activation_closes_at > activation_opens_at
    ),
    capacity_policy JSONB NOT NULL CHECK (
        jsonb_typeof(capacity_policy) = 'object'
    ),
    exit_criteria JSONB NOT NULL CHECK (jsonb_typeof(exit_criteria) = 'object'),
    approving_evidence_sha256 TEXT NOT NULL CHECK (
        approving_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    cohort_sha256 TEXT NOT NULL UNIQUE CHECK (
        cohort_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

CREATE TABLE IF NOT EXISTS public.mlc3_service_cohort_members (
    cohort_set_id UUID NOT NULL
        REFERENCES public.mlc3_service_cohort_sets(id) ON DELETE RESTRICT,
    member_ordinal INTEGER NOT NULL CHECK (member_ordinal > 0),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    membership_reason TEXT NOT NULL CHECK (length(btrim(membership_reason)) > 0),
    addition_evidence_sha256 TEXT NOT NULL CHECK (
        addition_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    added_by_user_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    PRIMARY KEY (cohort_set_id, member_ordinal),
    UNIQUE (cohort_set_id, acquisition_principal_id)
);

CREATE TABLE IF NOT EXISTS public.mlc3_service_activation_risk_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_kind TEXT NOT NULL CHECK (decision_kind = 'founder_skip_cohort_v1'),
    design_sha256 TEXT NOT NULL CHECK (design_sha256 ~ '^[0-9a-f]{64}$'),
    production_backend_commit TEXT NOT NULL CHECK (
        production_backend_commit ~ '^[0-9a-f]{40}$'
    ),
    production_frontend_commit TEXT NOT NULL CHECK (
        production_frontend_commit ~ '^[0-9a-f]{40}$'
    ),
    absent_cohort_reason TEXT NOT NULL CHECK (
        length(btrim(absent_cohort_reason)) BETWEEN 1 AND 1000
    ),
    capacity_policy_sha256 TEXT NOT NULL CHECK (
        capacity_policy_sha256 ~ '^[0-9a-f]{64}$'
    ),
    founder_user_id UUID NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    signature_identity TEXT NOT NULL CHECK (
        length(btrim(signature_identity)) > 0
    ),
    evidence_sha256 TEXT NOT NULL UNIQUE CHECK (
        evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    review_state TEXT NOT NULL CHECK (review_state IN ('pending', 'accepted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

CREATE TABLE IF NOT EXISTS public.mlc3_service_rollout_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    revision_number INTEGER NOT NULL UNIQUE CHECK (revision_number > 0),
    previous_revision_id UUID UNIQUE
        REFERENCES public.mlc3_service_rollout_revisions(id) ON DELETE RESTRICT,
    rollout_state TEXT NOT NULL CHECK (
        rollout_state IN (
            'disabled', 'explicit_cohort', 'generally_available',
            'halted', 'retired'
        )
    ),
    service_contract_version TEXT NOT NULL CHECK (
        service_contract_version = 'mlc3-first-client-service-v1'
    ),
    rollout_contract_version TEXT NOT NULL CHECK (
        rollout_contract_version = 'mlc3-general-user-service-d4'
    ),
    rollout_policy_sha256 TEXT NOT NULL CHECK (
        rollout_policy_sha256 ~ '^[0-9a-f]{64}$'
    ),
    access_resolver_version TEXT NOT NULL CHECK (
        access_resolver_version = 'require-mlc3-service-access-v2'
    ),
    operation_mode_registry_version TEXT NOT NULL CHECK (
        operation_mode_registry_version = 'mlc3-operation-mode-registry-v2'
    ),
    required_policy_id UUID REFERENCES public.processing_policy_versions(id)
        ON DELETE RESTRICT,
    personalized_purpose_id TEXT NOT NULL CHECK (
        personalized_purpose_id = 'personalized_exercise_recommendation'
    ),
    coach_review_purpose_id TEXT NOT NULL CHECK (
        coach_review_purpose_id = 'coach_review'
    ),
    approved_need_id TEXT NOT NULL CHECK (
        approved_need_id = 'rushed_phrase_endings'
    ),
    cohort_set_id UUID REFERENCES public.mlc3_service_cohort_sets(id)
        ON DELETE RESTRICT,
    activation_risk_decision_id UUID
        REFERENCES public.mlc3_service_activation_risk_decisions(id)
        ON DELETE RESTRICT,
    capacity_policy JSONB NOT NULL CHECK (
        jsonb_typeof(capacity_policy) = 'object'
        AND (capacity_policy->>'max_concurrent_enrollments')::INTEGER > 0
        AND (capacity_policy->>'max_new_enrollments_per_hour')::INTEGER > 0
        AND (capacity_policy->>'max_concurrent_uploads')::INTEGER > 0
        AND (capacity_policy->>'max_uploads_per_principal')::INTEGER > 0
        AND (capacity_policy->>'max_outstanding_assignments')::INTEGER > 0
        AND (capacity_policy->>'max_assignments_per_coach')::INTEGER > 0
        AND (capacity_policy->>'max_queue_age_hours')::INTEGER > 0
        AND (capacity_policy->>'max_media_bytes_per_day')::BIGINT > 0
        AND (capacity_policy->>'max_unresolved_recoveries')::INTEGER > 0
        AND (capacity_policy->>'max_recovery_age_minutes')::INTEGER > 0
    ),
    capacity_policy_sha256 TEXT NOT NULL CHECK (
        capacity_policy_sha256 ~ '^[0-9a-f]{64}$'
    ),
    policy_versions JSONB NOT NULL CHECK (jsonb_typeof(policy_versions) = 'object'),
    backend_gate_contract_version TEXT NOT NULL,
    frontend_gate_contract_version TEXT NOT NULL,
    monitor_contract_version TEXT NOT NULL,
    emergency_disable_contract_version TEXT NOT NULL,
    activating_user_id UUID,
    authorization_evidence_sha256 TEXT NOT NULL CHECK (
        authorization_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    effective_at TIMESTAMPTZ,
    rollout_sha256 TEXT NOT NULL UNIQUE CHECK (
        rollout_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK (
        (rollout_state = 'explicit_cohort' AND cohort_set_id IS NOT NULL
         AND activation_risk_decision_id IS NULL)
        OR (rollout_state = 'generally_available' AND cohort_set_id IS NULL)
        OR (rollout_state IN ('disabled', 'halted', 'retired'))
    ),
    CHECK (
        (rollout_state IN ('explicit_cohort', 'generally_available')
         AND effective_at IS NOT NULL AND required_policy_id IS NOT NULL
         AND activating_user_id IS NOT NULL)
        OR rollout_state IN ('disabled', 'halted', 'retired')
    )
);

CREATE TABLE IF NOT EXISTS public.mlc3_service_enrollment_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    owner_user_id UUID NOT NULL,
    rollout_revision_id UUID NOT NULL
        REFERENCES public.mlc3_service_rollout_revisions(id) ON DELETE RESTRICT,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    supersedes_enrollment_revision_id UUID
        REFERENCES public.mlc3_service_enrollment_revisions(id)
        ON DELETE RESTRICT,
    enrollment_state TEXT NOT NULL CHECK (
        enrollment_state IN ('active', 'withdrawn', 'blocked', 'revoked')
    ),
    operation_mode TEXT NOT NULL CHECK (
        operation_mode IN ('cohort_service', 'general_service')
    ),
    authorization_receipt_id UUID NOT NULL
        REFERENCES public.processing_authorization_receipts(id)
        ON DELETE RESTRICT,
    authorization_policy_id UUID NOT NULL
        REFERENCES public.processing_policy_versions(id) ON DELETE RESTRICT,
    personalized_purpose_id TEXT NOT NULL CHECK (
        personalized_purpose_id = 'personalized_exercise_recommendation'
    ),
    coach_review_purpose_id TEXT NOT NULL CHECK (
        coach_review_purpose_id = 'coach_review'
    ),
    account_binding_sha256 TEXT NOT NULL CHECK (
        account_binding_sha256 ~ '^[0-9a-f]{64}$'
    ),
    access_resolver_version TEXT NOT NULL CHECK (
        access_resolver_version = 'require-mlc3-service-access-v2'
    ),
    idempotency_key TEXT NOT NULL CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    enrollment_sha256 TEXT NOT NULL UNIQUE CHECK (
        enrollment_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (acquisition_principal_id, revision_number),
    UNIQUE (rollout_revision_id, acquisition_principal_id, idempotency_key),
    UNIQUE (id, acquisition_principal_id, rollout_revision_id)
);

CREATE TABLE IF NOT EXISTS public.mlc3_service_access_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL,
    rollout_revision_id UUID NOT NULL,
    enrollment_revision_id UUID NOT NULL,
    operation_mode TEXT NOT NULL CHECK (
        operation_mode IN ('cohort_service', 'general_service')
    ),
    operation_kind TEXT NOT NULL CHECK (length(btrim(operation_kind)) > 0),
    access_result TEXT NOT NULL CHECK (
        access_result IN ('authorized', 'backpressure', 'rejected')
    ),
    typed_reason TEXT,
    idempotency_key TEXT NOT NULL CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    access_sha256 TEXT NOT NULL UNIQUE CHECK (access_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (
        enrollment_revision_id, acquisition_principal_id, rollout_revision_id
    ) REFERENCES public.mlc3_service_enrollment_revisions(
        id, acquisition_principal_id, rollout_revision_id
    ) ON DELETE RESTRICT,
    UNIQUE (rollout_revision_id, acquisition_principal_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS public.mlc3_speaker_acquisition_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    recording_attempt_id UUID NOT NULL
        REFERENCES public.processing_recording_attempts(id) ON DELETE RESTRICT,
    audio_object_id UUID NOT NULL
        REFERENCES public.processing_audio_objects(id) ON DELETE RESTRICT,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    supersedes_revision_id UUID
        REFERENCES public.mlc3_speaker_acquisition_revisions(id)
        ON DELETE RESTRICT,
    speaker_count_status TEXT NOT NULL CHECK (
        speaker_count_status IN ('single', 'multiple', 'unknown')
    ),
    speaker_identity_status TEXT NOT NULL CHECK (
        speaker_identity_status IN ('resolved', 'unresolved')
    ),
    speaker_id UUID REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    count_policy_version TEXT NOT NULL,
    identity_policy_version TEXT NOT NULL,
    evidence_source TEXT NOT NULL CHECK (
        evidence_source IN ('self_speaker', 'reviewed_segmentation', 'unresolved')
    ),
    audio_sha256 TEXT NOT NULL CHECK (audio_sha256 ~ '^[0-9a-f]{64}$'),
    binding_sha256 TEXT NOT NULL UNIQUE CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (recording_attempt_id, revision_number),
    UNIQUE (id, acquisition_principal_id, recording_attempt_id, audio_object_id),
    CHECK (
        (speaker_identity_status = 'resolved' AND speaker_id IS NOT NULL)
        OR (speaker_identity_status = 'unresolved' AND speaker_id IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.mlc3_self_speaker_assertions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    owner_user_id UUID NOT NULL,
    recording_attempt_id UUID NOT NULL,
    audio_object_id UUID NOT NULL,
    authorization_receipt_id UUID NOT NULL
        REFERENCES public.processing_authorization_receipts(id)
        ON DELETE RESTRICT,
    authorization_policy_id UUID NOT NULL
        REFERENCES public.processing_policy_versions(id) ON DELETE RESTRICT,
    assertion_value TEXT NOT NULL CHECK (assertion_value = 'this_is_my_voice'),
    target_start_ms INTEGER NOT NULL CHECK (target_start_ms >= 0),
    target_duration_ms INTEGER NOT NULL CHECK (target_duration_ms > 0),
    policy_version TEXT NOT NULL CHECK (
        policy_version = 'mlc3-self-speaker-assertion-v1'
    ),
    idempotency_key TEXT NOT NULL CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    assertion_sha256 TEXT NOT NULL UNIQUE CHECK (
        assertion_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (
        recording_attempt_id, acquisition_principal_id
    ) REFERENCES public.processing_recording_attempts(
        id, acquisition_principal_id
    ) ON DELETE RESTRICT,
    FOREIGN KEY (
        audio_object_id, acquisition_principal_id, recording_attempt_id
    ) REFERENCES public.processing_audio_objects(
        id, acquisition_principal_id, recording_attempt_id
    ) ON DELETE RESTRICT,
    UNIQUE (acquisition_principal_id, recording_attempt_id, idempotency_key),
    UNIQUE (id, acquisition_principal_id, recording_attempt_id, audio_object_id)
);

CREATE TABLE IF NOT EXISTS public.mlc3_target_speaker_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    recording_attempt_id UUID NOT NULL,
    audio_object_id UUID NOT NULL,
    acquisition_revision_id UUID NOT NULL,
    speaker_id UUID NOT NULL REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    self_speaker_assertion_id UUID
        REFERENCES public.mlc3_self_speaker_assertions(id) ON DELETE RESTRICT,
    reviewed_segmentation_id UUID,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    supersedes_binding_id UUID
        REFERENCES public.mlc3_target_speaker_bindings(id) ON DELETE RESTRICT,
    binding_state TEXT NOT NULL CHECK (binding_state IN ('active', 'superseded')),
    clip_id UUID NULL,
    practice_attempt_id UUID NULL
        REFERENCES public.exercise_practice_attempts(id) ON DELETE RESTRICT,
    target_start_ms INTEGER NOT NULL CHECK (target_start_ms >= 0),
    target_duration_ms INTEGER NOT NULL CHECK (target_duration_ms > 0),
    transcript_span JSONB NOT NULL CHECK (jsonb_typeof(transcript_span) = 'object'),
    transcript_sha256 TEXT NOT NULL CHECK (
        transcript_sha256 ~ '^[0-9a-f]{64}$'
    ),
    audio_sha256 TEXT NOT NULL CHECK (audio_sha256 ~ '^[0-9a-f]{64}$'),
    segmentation_policy_version TEXT NOT NULL,
    segmentation_run_version TEXT NOT NULL,
    target_binding_sha256 TEXT NOT NULL UNIQUE CHECK (
        target_binding_sha256 ~ '^[0-9a-f]{64}$'
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (
        acquisition_revision_id, acquisition_principal_id,
        recording_attempt_id, audio_object_id
    ) REFERENCES public.mlc3_speaker_acquisition_revisions(
        id, acquisition_principal_id, recording_attempt_id, audio_object_id
    ) ON DELETE RESTRICT,
    CHECK (
        (self_speaker_assertion_id IS NOT NULL) <>
        (reviewed_segmentation_id IS NOT NULL)
    ),
    CHECK ((clip_id IS NOT NULL) <> (practice_attempt_id IS NOT NULL)),
    UNIQUE (recording_attempt_id, revision_number),
    UNIQUE (id, speaker_id, recording_attempt_id, audio_object_id),
    UNIQUE (id, acquisition_principal_id, speaker_id)
);

ALTER TABLE public.mlc3_target_speaker_bindings
    ADD COLUMN IF NOT EXISTS practice_attempt_id UUID NULL
        REFERENCES public.exercise_practice_attempts(id) ON DELETE RESTRICT;
ALTER TABLE public.mlc3_target_speaker_bindings
    ALTER COLUMN clip_id DROP NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.mlc3_target_speaker_bindings'::regclass
           AND conname = 'mlc3_target_speaker_binding_exact_span_check'
    ) THEN
        ALTER TABLE public.mlc3_target_speaker_bindings
            ADD CONSTRAINT mlc3_target_speaker_binding_exact_span_check
            CHECK ((clip_id IS NOT NULL) <> (practice_attempt_id IS NOT NULL));
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.mlc3_comparison_speaker_eligibility_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    source_recording_attempt_id UUID NOT NULL
        REFERENCES public.processing_recording_attempts(id) ON DELETE RESTRICT,
    practice_recording_attempt_id UUID NOT NULL
        REFERENCES public.processing_recording_attempts(id) ON DELETE RESTRICT,
    source_target_binding_id UUID
        REFERENCES public.mlc3_target_speaker_bindings(id) ON DELETE RESTRICT,
    practice_target_binding_id UUID
        REFERENCES public.mlc3_target_speaker_bindings(id) ON DELETE RESTRICT,
    source_speaker_id UUID REFERENCES public.ml_speakers(id),
    practice_speaker_id UUID REFERENCES public.ml_speakers(id),
    eligibility_result TEXT NOT NULL CHECK (
        eligibility_result IN (
            'same_speaker_eligible',
            'speaker_identity_mismatch_or_unresolved'
        )
    ),
    exclusion_reason TEXT,
    revision_number INTEGER NOT NULL CHECK (revision_number > 0),
    supersedes_revision_id UUID
        REFERENCES public.mlc3_comparison_speaker_eligibility_revisions(id)
        ON DELETE RESTRICT,
    eligibility_sha256 TEXT NOT NULL UNIQUE CHECK (
        eligibility_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key TEXT NOT NULL CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (
        source_target_binding_id, acquisition_principal_id, source_speaker_id
    ) REFERENCES public.mlc3_target_speaker_bindings(
        id, acquisition_principal_id, speaker_id
    ) ON DELETE RESTRICT,
    FOREIGN KEY (
        practice_target_binding_id, acquisition_principal_id,
        practice_speaker_id
    ) REFERENCES public.mlc3_target_speaker_bindings(
        id, acquisition_principal_id, speaker_id
    ) ON DELETE RESTRICT,
    UNIQUE (acquisition_principal_id, idempotency_key),
    CHECK (
        (eligibility_result = 'same_speaker_eligible'
         AND source_target_binding_id IS NOT NULL
         AND practice_target_binding_id IS NOT NULL
         AND source_speaker_id = practice_speaker_id
         AND exclusion_reason IS NULL)
        OR (eligibility_result = 'speaker_identity_mismatch_or_unresolved'
            AND exclusion_reason = 'speaker_identity_mismatch_or_unresolved')
    )
);

CREATE TABLE IF NOT EXISTS public.mlc3_service_backpressure_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rollout_revision_id UUID NOT NULL
        REFERENCES public.mlc3_service_rollout_revisions(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    typed_state TEXT NOT NULL CHECK (
        typed_state IN (
            'MLC3_ENROLLMENT_CAPACITY_REACHED',
            'MLC3_UPLOAD_CAPACITY_REACHED',
            'MLC3_COACH_QUEUE_BACKPRESSURE',
            'MLC3_MEDIA_BUDGET_REACHED',
            'MLC3_RECOVERY_BACKLOG_BLOCKED',
            'MLC3_ROLLOUT_HALTED'
        )
    ),
    counter_snapshot JSONB NOT NULL CHECK (
        jsonb_typeof(counter_snapshot) = 'object'
    ),
    event_sha256 TEXT NOT NULL UNIQUE CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

-- Literal declarations are intentional: the release security scanner proves
-- each newly created public table enables RLS in its defining migration.
ALTER TABLE public.mlc3_service_cohort_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_cohort_sets FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_cohort_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_cohort_members FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_activation_risk_decisions
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_activation_risk_decisions
    FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_rollout_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_rollout_revisions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_enrollment_revisions
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_enrollment_revisions
    FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_access_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_access_events FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_speaker_acquisition_revisions
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_speaker_acquisition_revisions
    FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_self_speaker_assertions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_self_speaker_assertions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_target_speaker_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_target_speaker_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_comparison_speaker_eligibility_revisions
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_comparison_speaker_eligibility_revisions
    FORCE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_backpressure_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_backpressure_events FORCE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.reject_mlc3_general_service_mutation_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    RAISE EXCEPTION 'MLC3_GENERAL_SERVICE_APPEND_ONLY';
END;
$$;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'mlc3_service_cohort_sets', 'mlc3_service_cohort_members',
        'mlc3_service_activation_risk_decisions',
        'mlc3_service_rollout_revisions',
        'mlc3_service_enrollment_revisions', 'mlc3_service_access_events',
        'mlc3_speaker_acquisition_revisions', 'mlc3_self_speaker_assertions',
        'mlc3_target_speaker_bindings',
        'mlc3_comparison_speaker_eligibility_revisions',
        'mlc3_service_backpressure_events'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format('ALTER TABLE public.%I FORCE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON public.%I',
            table_name || '_append_only', table_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'public.reject_mlc3_general_service_mutation_v1()',
            table_name || '_append_only', table_name
        );
        EXECUTE format(
            'REVOKE ALL ON TABLE public.%I FROM PUBLIC, anon, authenticated, service_role',
            table_name
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.resolve_mlc3_dual_purpose_receipt_v2(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    receipt public.processing_authorization_receipts;
    wall_now TIMESTAMPTZ := clock_timestamp();
BEGIN
    SELECT receipt_row.* INTO receipt
      FROM public.processing_authorization_receipts receipt_row
      JOIN public.processing_policy_versions policy
        ON policy.id = receipt_row.policy_id
       AND policy.status = 'active'
       AND policy.activated_at <= wall_now
       AND (policy.retired_at IS NULL OR policy.retired_at > wall_now)
     WHERE receipt_row.acquisition_principal_id = p_acquisition_principal_id
       AND NOT EXISTS (
           SELECT 1 FROM public.processing_service_blocks block
            WHERE block.acquisition_principal_id = p_acquisition_principal_id
              AND block.effective_at <= wall_now
       )
       AND NOT EXISTS (
           SELECT 1 FROM public.data_purge_requests purge
            WHERE purge.acquisition_principal_id = p_acquisition_principal_id
              AND purge.state <> 'done'
       )
       AND NOT EXISTS (
           SELECT 1
             FROM (VALUES
                 ('personalized_exercise_recommendation'::TEXT),
                 ('coach_review'::TEXT)
             ) required(purpose_id)
            WHERE NOT EXISTS (
                SELECT 1
                  FROM public.processing_authorization_receipt_purposes rp
                  JOIN public.processing_policy_purposes pp
                    ON pp.policy_id = receipt_row.policy_id
                   AND pp.purpose_id = rp.purpose_id
                  JOIN public.processing_purpose_registry registry
                    ON registry.id = rp.purpose_id
                   AND registry.operational
                   AND registry.authorizes_processing
                 WHERE rp.receipt_id = receipt_row.id
                   AND rp.purpose_id = required.purpose_id
            )
       )
     ORDER BY receipt_row.accepted_at DESC, receipt_row.id DESC
     LIMIT 1
     FOR SHARE OF receipt_row;
    IF receipt.id IS NULL THEN
        RAISE EXCEPTION 'MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED';
    END IF;
    RETURN jsonb_build_object(
        'receipt_id', receipt.id,
        'policy_id', receipt.policy_id,
        'personalized_purpose_id', 'personalized_exercise_recommendation',
        'coach_review_purpose_id', 'coach_review'
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.current_mlc3_operation_mode_v2()
RETURNS TEXT LANGUAGE plpgsql STABLE SET search_path = public AS $$
DECLARE mode_value TEXT;
BEGIN
    mode_value := NULLIF(
        current_setting('willab.mlc3_operation_mode', true), ''
    );
    IF mode_value NOT IN (
        'allowlisted_service', 'cohort_service', 'general_service'
    ) THEN
        RETURN 'allowlisted_service';
    END IF;
    RETURN mode_value;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_mlc3_service_access_event_v1(
    p_acquisition_principal_id UUID,
    p_rollout_revision_id UUID,
    p_enrollment_revision_id UUID,
    p_operation_mode TEXT,
    p_operation_kind TEXT,
    p_idempotency_key TEXT
) RETURNS public.mlc3_service_access_events
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    existing public.mlc3_service_access_events;
    result_hash TEXT;
BEGIN
    IF p_operation_mode NOT IN ('cohort_service', 'general_service')
       OR COALESCE(btrim(p_operation_kind), '') = ''
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN RAISE EXCEPTION 'MLC3_ACCESS_EVENT_INVALID'; END IF;
    result_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-service-access-event-v1',
        'acquisition_principal_id', p_acquisition_principal_id,
        'rollout_revision_id', p_rollout_revision_id,
        'enrollment_revision_id', p_enrollment_revision_id,
        'operation_mode', p_operation_mode,
        'operation_kind', p_operation_kind,
        'access_result', 'authorized',
        'idempotency_key', p_idempotency_key
    ));
    SELECT * INTO existing
      FROM public.mlc3_service_access_events row
     WHERE row.rollout_revision_id = p_rollout_revision_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.access_sha256 <> result_hash
        THEN RAISE EXCEPTION 'MLC3_ACCESS_EVENT_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.mlc3_service_access_events (
        acquisition_principal_id, rollout_revision_id,
        enrollment_revision_id, operation_mode, operation_kind,
        access_result, idempotency_key, access_sha256
    ) VALUES (
        p_acquisition_principal_id, p_rollout_revision_id,
        p_enrollment_revision_id, p_operation_mode, p_operation_kind,
        'authorized', p_idempotency_key, result_hash
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.ensure_mlc3_service_enrollment_v2(
    p_acquisition_principal_id UUID,
    p_owner_user_id UUID,
    p_idempotency_key TEXT
) RETURNS public.mlc3_service_enrollment_revisions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    rollout public.mlc3_service_rollout_revisions;
    existing public.mlc3_service_enrollment_revisions;
    authority JSONB;
    next_revision INTEGER;
    mode_value TEXT;
    enrollment_hash TEXT;
    cohort_member_count INTEGER;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'MLC3_SERVICE_REQUIRES_READ_COMMITTED';
    END IF;
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'MLC3_ENROLLMENT_IDEMPOTENCY_REQUIRED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-rollout-policy-v2', 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-principal:' || p_acquisition_principal_id::TEXT, 0
    ));
    SELECT * INTO rollout
      FROM public.mlc3_service_rollout_revisions row
     ORDER BY row.revision_number DESC
     LIMIT 1 FOR SHARE;
    IF rollout.id IS NULL OR rollout.rollout_state NOT IN (
        'explicit_cohort', 'generally_available'
    ) OR rollout.effective_at > clock_timestamp() THEN
        RAISE EXCEPTION 'MLC3_ROLLOUT_NOT_ACTIVE';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.mlc3_service_contracts contract
         WHERE contract.contract_version = rollout.service_contract_version
           AND contract.state = 'active'
           AND contract.active_from <= clock_timestamp()
           AND (contract.retired_at IS NULL
                OR contract.retired_at > clock_timestamp())
    ) THEN RAISE EXCEPTION 'MLC3_SERVICE_CONTRACT_NOT_ACTIVE'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.owner_principals principal
         WHERE principal.id = p_acquisition_principal_id
           AND principal.user_id = p_owner_user_id
           AND principal.guest_secret_hash IS NULL
    ) OR EXISTS (
        SELECT 1 FROM public.owner_principals other
         WHERE other.user_id = p_owner_user_id
           AND other.id <> p_acquisition_principal_id
    ) THEN RAISE EXCEPTION 'MLC3_ACCOUNT_PRINCIPAL_AMBIGUOUS'; END IF;
    IF rollout.rollout_state = 'explicit_cohort' AND NOT EXISTS (
        SELECT 1 FROM public.mlc3_service_cohort_members member
         WHERE member.cohort_set_id = rollout.cohort_set_id
           AND member.acquisition_principal_id = p_acquisition_principal_id
    ) THEN RAISE EXCEPTION 'MLC3_COHORT_MEMBERSHIP_REQUIRED'; END IF;
    authority := public.resolve_mlc3_dual_purpose_receipt_v2(
        p_acquisition_principal_id
    );
    IF (authority->>'policy_id')::UUID <> rollout.required_policy_id THEN
        RAISE EXCEPTION 'MLC3_ROLLOUT_POLICY_AUTHORITY_MISMATCH';
    END IF;
    SELECT * INTO existing
      FROM public.mlc3_service_enrollment_revisions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    mode_value := CASE rollout.rollout_state
        WHEN 'explicit_cohort' THEN 'cohort_service'
        ELSE 'general_service'
    END;
    IF existing.id IS NOT NULL
       AND existing.enrollment_state = 'active'
       AND existing.rollout_revision_id = rollout.id
       AND existing.authorization_receipt_id =
           (authority->>'receipt_id')::UUID
       AND existing.authorization_policy_id =
           (authority->>'policy_id')::UUID
       AND existing.owner_user_id = p_owner_user_id
       AND existing.operation_mode = mode_value
    THEN
        PERFORM public.record_mlc3_service_access_event_v1(
            p_acquisition_principal_id, rollout.id, existing.id,
            mode_value, 'http_service_entry', p_idempotency_key
        );
        PERFORM set_config('willab.mlc3_rollout_revision_id', rollout.id::TEXT, true);
        PERFORM set_config('willab.mlc3_enrollment_revision_id', existing.id::TEXT, true);
        PERFORM set_config('willab.mlc3_operation_mode', mode_value, true);
        RETURN existing;
    END IF;
    IF (
        SELECT count(*)
          FROM public.mlc3_service_enrollment_revisions row
         WHERE row.enrollment_state = 'active'
           AND row.created_at >= clock_timestamp() - INTERVAL '1 hour'
    ) >= (rollout.capacity_policy->>'max_new_enrollments_per_hour')::INTEGER
    THEN
        RAISE EXCEPTION 'MLC3_ENROLLMENT_CAPACITY_REACHED';
    END IF;
    SELECT COALESCE(max(row.revision_number), 0) + 1 INTO next_revision
      FROM public.mlc3_service_enrollment_revisions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id;
    enrollment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-general-user-service-d4',
        'acquisition_principal_id', p_acquisition_principal_id,
        'owner_user_id', p_owner_user_id,
        'rollout_revision_id', rollout.id,
        'revision_number', next_revision,
        'supersedes_id', existing.id,
        'operation_mode', mode_value,
        'receipt_id', authority->>'receipt_id',
        'policy_id', authority->>'policy_id',
        'idempotency_key', p_idempotency_key
    ));
    INSERT INTO public.mlc3_service_enrollment_revisions (
        acquisition_principal_id, owner_user_id, rollout_revision_id,
        revision_number, supersedes_enrollment_revision_id, enrollment_state,
        operation_mode, authorization_receipt_id, authorization_policy_id,
        personalized_purpose_id, coach_review_purpose_id,
        account_binding_sha256, access_resolver_version, idempotency_key,
        enrollment_sha256
    ) VALUES (
        p_acquisition_principal_id, p_owner_user_id, rollout.id,
        next_revision, existing.id, 'active', mode_value,
        (authority->>'receipt_id')::UUID, (authority->>'policy_id')::UUID,
        'personalized_exercise_recommendation', 'coach_review',
        public.exercise_json_sha256_v1(jsonb_build_object(
            'principal_id', p_acquisition_principal_id,
            'user_id', p_owner_user_id
        )), 'require-mlc3-service-access-v2', p_idempotency_key,
        enrollment_hash
    ) RETURNING * INTO existing;
    PERFORM public.record_mlc3_service_access_event_v1(
        p_acquisition_principal_id, rollout.id, existing.id,
        mode_value, 'http_service_entry', p_idempotency_key
    );
    PERFORM set_config('willab.mlc3_rollout_revision_id', rollout.id::TEXT, true);
    PERFORM set_config('willab.mlc3_enrollment_revision_id', existing.id::TEXT, true);
    PERFORM set_config('willab.mlc3_operation_mode', mode_value, true);
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_mlc3_service_access_v2(
    p_acquisition_principal_id UUID,
    p_expected_rollout_revision_id UUID DEFAULT NULL,
    p_expected_enrollment_revision_id UUID DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    rollout public.mlc3_service_rollout_revisions;
    enrollment public.mlc3_service_enrollment_revisions;
    authority JSONB;
    mode_value TEXT;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'MLC3_SERVICE_REQUIRES_READ_COMMITTED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-rollout-policy-v2', 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-principal:' || p_acquisition_principal_id::TEXT, 0
    ));
    SELECT * INTO rollout
      FROM public.mlc3_service_rollout_revisions row
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    IF rollout.id IS NULL OR rollout.rollout_state NOT IN (
        'explicit_cohort', 'generally_available'
    ) OR rollout.effective_at > clock_timestamp()
       OR (p_expected_rollout_revision_id IS NOT NULL
           AND rollout.id <> p_expected_rollout_revision_id)
    THEN RAISE EXCEPTION 'MLC3_ROLLOUT_NOT_ACTIVE'; END IF;
    SELECT * INTO enrollment
      FROM public.mlc3_service_enrollment_revisions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    mode_value := CASE rollout.rollout_state
        WHEN 'explicit_cohort' THEN 'cohort_service'
        ELSE 'general_service'
    END;
    IF enrollment.id IS NULL OR enrollment.enrollment_state <> 'active'
       OR enrollment.rollout_revision_id <> rollout.id
       OR enrollment.operation_mode <> mode_value
       OR (p_expected_enrollment_revision_id IS NOT NULL
           AND enrollment.id <> p_expected_enrollment_revision_id)
    THEN RAISE EXCEPTION 'MLC3_CURRENT_ENROLLMENT_REQUIRED'; END IF;
    IF rollout.rollout_state = 'explicit_cohort' AND NOT EXISTS (
        SELECT 1 FROM public.mlc3_service_cohort_members member
         WHERE member.cohort_set_id = rollout.cohort_set_id
           AND member.acquisition_principal_id = p_acquisition_principal_id
    ) THEN RAISE EXCEPTION 'MLC3_COHORT_MEMBERSHIP_REQUIRED'; END IF;
    authority := public.resolve_mlc3_dual_purpose_receipt_v2(
        p_acquisition_principal_id
    );
    IF (authority->>'policy_id')::UUID <> rollout.required_policy_id
       OR enrollment.authorization_receipt_id <>
           (authority->>'receipt_id')::UUID
       OR enrollment.authorization_policy_id <>
           (authority->>'policy_id')::UUID
    THEN RAISE EXCEPTION 'MLC3_ENROLLMENT_AUTHORITY_STALE'; END IF;
    PERFORM set_config('willab.mlc3_rollout_revision_id', rollout.id::TEXT, true);
    PERFORM set_config('willab.mlc3_enrollment_revision_id', enrollment.id::TEXT, true);
    PERFORM set_config('willab.mlc3_operation_mode', mode_value, true);
    RETURN jsonb_build_object(
        'rollout_revision_id', rollout.id,
        'enrollment_revision_id', enrollment.id,
        'operation_mode', mode_value,
        'authorization_receipt_id', enrollment.authorization_receipt_id,
        'authorization_policy_id', enrollment.authorization_policy_id,
        'access_resolver_version', enrollment.access_resolver_version
    );
END;
$$;

-- Retain the historical signature for installed reviewed functions, but make
-- its authority rollout-aware. Direct runtime execution is revoked below.
CREATE OR REPLACE FUNCTION public.require_mlc3_service_principal_v1(
    p_acquisition_principal_id UUID
) RETURNS public.mlc3_service_contracts
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE contract public.mlc3_service_contracts;
BEGIN
    PERFORM public.require_mlc3_service_access_v2(
        p_acquisition_principal_id, NULL, NULL
    );
    SELECT * INTO STRICT contract
      FROM public.mlc3_service_contracts row
     WHERE row.contract_version = 'mlc3-first-client-service-v1'
       AND row.state = 'active'
       AND row.active_from <= clock_timestamp()
       AND (row.retired_at IS NULL OR row.retired_at > clock_timestamp())
     FOR SHARE;
    RETURN contract;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_mlc3_self_speaker_target_v1(
    p_acquisition_principal_id UUID,
    p_owner_user_id UUID,
    p_recording_attempt_id UUID,
    p_audio_object_id UUID,
    p_clip_id UUID,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    access_row JSONB;
    attempt public.processing_recording_attempts;
    audio public.processing_audio_objects;
    clip public.snippets;
    practice_attempt public.exercise_practice_attempts;
    existing_assertion public.mlc3_self_speaker_assertions;
    acquisition_revision public.mlc3_speaker_acquisition_revisions;
    target_binding public.mlc3_target_speaker_bindings;
    speaker_value UUID;
    transcript_hash TEXT;
    assertion_hash TEXT;
    acquisition_hash TEXT;
    binding_hash TEXT;
    next_acquisition_revision INTEGER;
    next_target_revision INTEGER;
    target_start INTEGER;
    target_duration INTEGER;
    target_text TEXT;
    target_clip_id UUID;
    target_practice_attempt_id UUID;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'MLC3_SELF_SPEAKER_IDEMPOTENCY_REQUIRED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-principal:' || p_acquisition_principal_id::TEXT, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-self-speaker:' || p_recording_attempt_id::TEXT, 0
    ));
    -- Every identity writer shares this lock with eligibility, assignment and
    -- judgment readers. A later correction therefore cannot cross a frozen
    -- comparison boundary while the reader is committing.
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-speaker-attempt:' || p_recording_attempt_id::TEXT, 0
    ));
    access_row := public.require_mlc3_service_access_v2(
        p_acquisition_principal_id, NULL, NULL
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.owner_principals principal
         WHERE principal.id = p_acquisition_principal_id
           AND principal.user_id = p_owner_user_id
           AND principal.guest_secret_hash IS NULL
    ) THEN RAISE EXCEPTION 'MLC3_SELF_SPEAKER_OWNER_REQUIRED'; END IF;
    SELECT * INTO STRICT attempt
     FROM public.processing_recording_attempts row
     WHERE row.id = p_recording_attempt_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.status IN ('completed', 'accepted')
     FOR SHARE;
    SELECT * INTO STRICT audio
      FROM public.processing_audio_objects row
     WHERE row.id = p_audio_object_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = attempt.id
       AND row.verified_at IS NOT NULL
       AND row.deleted_at IS NULL
     FOR SHARE;
    IF EXISTS (
        SELECT 1 FROM public.processing_audio_object_deletion_events event
         WHERE event.audio_object_id = audio.id
    ) THEN RAISE EXCEPTION 'MLC3_SELF_SPEAKER_AUDIO_NOT_LIVE'; END IF;
    IF p_clip_id IS NOT NULL THEN
        SELECT * INTO STRICT clip
          FROM public.snippets row
         WHERE row.id = p_clip_id
           AND row.recording_id = attempt.recording_id
           AND row.start_offset_ms >= 0
           AND row.duration_ms > 0
           AND length(btrim(COALESCE(row.transcript, ''))) > 0
         FOR SHARE;
        target_start := clip.start_offset_ms;
        target_duration := clip.duration_ms;
        target_text := clip.transcript;
        target_clip_id := clip.id;
        target_practice_attempt_id := NULL;
    ELSE
        SELECT * INTO STRICT practice_attempt
          FROM public.exercise_practice_attempts row
         WHERE row.processing_recording_attempt_id = attempt.id
           AND row.processing_audio_object_id = audio.id
           AND row.acquisition_principal_id = p_acquisition_principal_id
           AND row.transcript_state = 'available'
           AND row.state NOT IN ('cancelled', 'quarantined')
           AND length(btrim(COALESCE(row.transcript_text, ''))) > 0
         FOR SHARE;
        target_start := 0;
        target_duration := practice_attempt.duration_ms;
        target_text := practice_attempt.transcript_text;
        target_clip_id := NULL;
        target_practice_attempt_id := practice_attempt.id;
    END IF;
    transcript_hash := public.exercise_json_sha256_v1(
        jsonb_build_object('transcript', target_text)
    );
    assertion_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-self-speaker-assertion-v1',
        'acquisition_principal_id', p_acquisition_principal_id,
        'owner_user_id', p_owner_user_id,
        'recording_attempt_id', attempt.id,
        'audio_object_id', audio.id,
        'audio_sha256', audio.exact_bytes_sha256,
        'clip_id', target_clip_id,
        'practice_attempt_id', target_practice_attempt_id,
        'start_offset_ms', target_start,
        'duration_ms', target_duration,
        'transcript_sha256', transcript_hash,
        'authorization_receipt_id', access_row->>'authorization_receipt_id',
        'authorization_policy_id', access_row->>'authorization_policy_id',
        'assertion', 'this_is_my_voice',
        'idempotency_key', p_idempotency_key
    ));
    SELECT * INTO existing_assertion
      FROM public.mlc3_self_speaker_assertions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = attempt.id
       AND row.idempotency_key = p_idempotency_key;
    IF existing_assertion.id IS NOT NULL THEN
        IF existing_assertion.assertion_sha256 <> assertion_hash
           OR existing_assertion.audio_object_id <> audio.id
        THEN RAISE EXCEPTION 'MLC3_SELF_SPEAKER_REPLAY_CONFLICT'; END IF;
        SELECT * INTO STRICT target_binding
          FROM public.mlc3_target_speaker_bindings row
         WHERE row.self_speaker_assertion_id = existing_assertion.id;
        RETURN jsonb_build_object(
            'assertion_id', existing_assertion.id,
            'speaker_id', target_binding.speaker_id,
            'target_binding_id', target_binding.id,
            'replayed', true
        );
    END IF;
    SELECT link.speaker_id INTO speaker_value
      FROM public.ml_speaker_principals link
     WHERE link.acquisition_principal_id = p_acquisition_principal_id
     FOR SHARE;
    IF speaker_value IS NULL THEN
        speaker_value := gen_random_uuid();
        INSERT INTO public.ml_speakers(id) VALUES (speaker_value);
        INSERT INTO public.ml_speaker_principals(
            speaker_id, acquisition_principal_id
        ) VALUES (speaker_value, p_acquisition_principal_id);
    END IF;
    INSERT INTO public.mlc3_self_speaker_assertions (
        acquisition_principal_id, owner_user_id, recording_attempt_id,
        audio_object_id, authorization_receipt_id, authorization_policy_id,
        assertion_value, target_start_ms, target_duration_ms, policy_version,
        idempotency_key, assertion_sha256
    ) VALUES (
        p_acquisition_principal_id, p_owner_user_id, attempt.id, audio.id,
        (access_row->>'authorization_receipt_id')::UUID,
        (access_row->>'authorization_policy_id')::UUID,
        'this_is_my_voice', target_start, target_duration,
        'mlc3-self-speaker-assertion-v1', p_idempotency_key, assertion_hash
    ) RETURNING * INTO existing_assertion;
    SELECT COALESCE(max(row.revision_number), 0) + 1
      INTO next_acquisition_revision
      FROM public.mlc3_speaker_acquisition_revisions row
     WHERE row.recording_attempt_id = attempt.id;
    acquisition_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'recording_attempt_id', attempt.id,
        'audio_object_id', audio.id,
        'speaker_count_status', 'unknown',
        'speaker_identity_status', 'resolved',
        'speaker_id', speaker_value,
        'assertion_id', existing_assertion.id,
        'revision_number', next_acquisition_revision
    ));
    INSERT INTO public.mlc3_speaker_acquisition_revisions (
        acquisition_principal_id, recording_attempt_id, audio_object_id,
        revision_number, supersedes_revision_id, speaker_count_status,
        speaker_identity_status, speaker_id, count_policy_version,
        identity_policy_version, evidence_source, audio_sha256, binding_sha256
    ) SELECT
        p_acquisition_principal_id, attempt.id, audio.id,
        next_acquisition_revision,
        (SELECT row.id FROM public.mlc3_speaker_acquisition_revisions row
          WHERE row.recording_attempt_id = attempt.id
          ORDER BY row.revision_number DESC LIMIT 1),
        'unknown', 'resolved', speaker_value,
        'self-speaker-count-v1', 'self-speaker-identity-v1', 'self_speaker',
        audio.exact_bytes_sha256, acquisition_hash
    RETURNING * INTO acquisition_revision;
    SELECT COALESCE(max(row.revision_number), 0) + 1
      INTO next_target_revision
      FROM public.mlc3_target_speaker_bindings row
     WHERE row.recording_attempt_id = attempt.id;
    binding_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'acquisition_revision_id', acquisition_revision.id,
        'speaker_id', speaker_value,
        'clip_id', target_clip_id,
        'practice_attempt_id', target_practice_attempt_id,
        'audio_sha256', audio.exact_bytes_sha256,
        'start_offset_ms', target_start,
        'duration_ms', target_duration,
        'transcript_sha256', transcript_hash,
        'assertion_id', existing_assertion.id,
        'revision_number', next_target_revision
    ));
    INSERT INTO public.mlc3_target_speaker_bindings (
        acquisition_principal_id, recording_attempt_id, audio_object_id,
        acquisition_revision_id, speaker_id, self_speaker_assertion_id,
        revision_number, supersedes_binding_id, binding_state, clip_id,
        practice_attempt_id,
        target_start_ms, target_duration_ms, transcript_span,
        transcript_sha256, audio_sha256, segmentation_policy_version,
        segmentation_run_version, target_binding_sha256
    ) SELECT
        p_acquisition_principal_id, attempt.id, audio.id,
        acquisition_revision.id, speaker_value, existing_assertion.id,
        next_target_revision,
        (SELECT row.id FROM public.mlc3_target_speaker_bindings row
          WHERE row.recording_attempt_id = attempt.id
          ORDER BY row.revision_number DESC LIMIT 1),
        'active', target_clip_id, target_practice_attempt_id,
        target_start, target_duration,
        jsonb_build_object(
            'snippet_id', target_clip_id,
            'practice_attempt_id', target_practice_attempt_id,
            'text', target_text
        ),
        transcript_hash, audio.exact_bytes_sha256,
        'self-speaker-target-span-v1', 'explicit-user-assertion-v1',
        binding_hash
    RETURNING * INTO target_binding;
    RETURN jsonb_build_object(
        'assertion_id', existing_assertion.id,
        'speaker_id', speaker_value,
        'acquisition_revision_id', acquisition_revision.id,
        'target_binding_id', target_binding.id,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.record_mlc3_feedback_self_speaker_target_v1(
    p_acquisition_principal_id UUID,
    p_owner_user_id UUID,
    p_membership_id UUID,
    p_candidate_id UUID,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    membership public.feedback_v3_memberships;
    item public.feedback_v3_membership_items;
    lineage public.exercise_audio_lineages;
BEGIN
    membership := public.require_feedback_v3_service_membership_live_v1(
        p_membership_id, p_acquisition_principal_id
    );
    SELECT * INTO STRICT item
      FROM public.feedback_v3_membership_items row
     WHERE row.membership_id = membership.id
       AND row.candidate_id = p_candidate_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.feedback_family = 'confident_voice'
       AND row.selected
       AND row.eligibility = 'eligible'
       AND row.operation_mode = public.current_mlc3_operation_mode_v2();
    SELECT source.* INTO STRICT lineage
      FROM public.exercise_n1_pattern_snapshots snapshot
      JOIN public.exercise_candidate_sets candidate_set
        ON candidate_set.id = snapshot.candidate_set_id
       AND candidate_set.acquisition_principal_id =
           snapshot.acquisition_principal_id
      JOIN public.exercise_audio_lineages source
        ON source.id = candidate_set.audio_lineage_id
       AND source.acquisition_principal_id =
           candidate_set.acquisition_principal_id
     WHERE snapshot.acquisition_principal_id = p_acquisition_principal_id
       AND candidate_set.source_candidate_id = item.candidate_key
       AND source.take_id = membership.take_id
       AND source.snippet_id = item.snippet_id
     ORDER BY candidate_set.assigned_at DESC, candidate_set.id DESC
     LIMIT 1 FOR SHARE OF source;
    RETURN public.record_mlc3_self_speaker_target_v1(
        p_acquisition_principal_id, p_owner_user_id,
        lineage.recording_attempt_id, lineage.processing_audio_object_id,
        lineage.snippet_id, p_idempotency_key
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.record_mlc3_practice_self_speaker_target_v1(
    p_acquisition_principal_id UUID,
    p_owner_user_id UUID,
    p_practice_attempt_id UUID,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE attempt public.exercise_practice_attempts;
BEGIN
    SELECT * INTO STRICT attempt
      FROM public.exercise_practice_attempts row
     WHERE row.id = p_practice_attempt_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = public.current_mlc3_operation_mode_v2()
       AND row.transcript_state = 'available'
       AND row.state NOT IN ('cancelled', 'quarantined')
     FOR SHARE;
    RETURN public.record_mlc3_self_speaker_target_v1(
        p_acquisition_principal_id, p_owner_user_id,
        attempt.processing_recording_attempt_id,
        attempt.processing_audio_object_id, NULL, p_idempotency_key
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.freeze_mlc3_same_speaker_eligibility_v1(
    p_acquisition_principal_id UUID,
    p_source_recording_attempt_id UUID,
    p_practice_recording_attempt_id UUID,
    p_idempotency_key TEXT
) RETURNS public.mlc3_comparison_speaker_eligibility_revisions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    source_revision public.mlc3_speaker_acquisition_revisions;
    practice_revision public.mlc3_speaker_acquisition_revisions;
    source_binding public.mlc3_target_speaker_bindings;
    practice_binding public.mlc3_target_speaker_bindings;
    existing public.mlc3_comparison_speaker_eligibility_revisions;
    result_value TEXT;
    result_hash TEXT;
    next_revision INTEGER;
BEGIN
    IF p_source_recording_attempt_id = p_practice_recording_attempt_id
       OR COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'MLC3_SPEAKER_COMPARISON_REQUEST_INVALID';
    END IF;
    PERFORM public.require_mlc3_service_access_v2(
        p_acquisition_principal_id, NULL, NULL
    );
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-speaker-attempt:' || least(
            p_source_recording_attempt_id, p_practice_recording_attempt_id
        )::TEXT, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-speaker-attempt:' || greatest(
            p_source_recording_attempt_id, p_practice_recording_attempt_id
        )::TEXT, 0
    ));
    SELECT * INTO source_revision
      FROM public.mlc3_speaker_acquisition_revisions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = p_source_recording_attempt_id
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    SELECT * INTO practice_revision
      FROM public.mlc3_speaker_acquisition_revisions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = p_practice_recording_attempt_id
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    IF source_revision.id IS NOT NULL THEN
        SELECT * INTO source_binding
          FROM public.mlc3_target_speaker_bindings row
         WHERE row.acquisition_revision_id = source_revision.id
         ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    END IF;
    IF practice_revision.id IS NOT NULL THEN
        SELECT * INTO practice_binding
          FROM public.mlc3_target_speaker_bindings row
         WHERE row.acquisition_revision_id = practice_revision.id
         ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    END IF;
    result_value := CASE
        WHEN source_revision.speaker_identity_status = 'resolved'
         AND practice_revision.speaker_identity_status = 'resolved'
         AND source_binding.id IS NOT NULL
         AND practice_binding.id IS NOT NULL
         AND source_binding.binding_state = 'active'
         AND practice_binding.binding_state = 'active'
         AND source_binding.recording_attempt_id = source_revision.recording_attempt_id
         AND practice_binding.recording_attempt_id = practice_revision.recording_attempt_id
         AND source_binding.acquisition_revision_id = source_revision.id
         AND practice_binding.acquisition_revision_id = practice_revision.id
         AND source_binding.speaker_id = practice_binding.speaker_id
        THEN 'same_speaker_eligible'
        ELSE 'speaker_identity_mismatch_or_unresolved'
    END;
    result_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-same-speaker-comparison-v1',
        'acquisition_principal_id', p_acquisition_principal_id,
        'source_recording_attempt_id', p_source_recording_attempt_id,
        'practice_recording_attempt_id', p_practice_recording_attempt_id,
        'source_acquisition_revision_id', source_revision.id,
        'practice_acquisition_revision_id', practice_revision.id,
        'source_target_binding_id', source_binding.id,
        'practice_target_binding_id', practice_binding.id,
        'source_speaker_id', source_binding.speaker_id,
        'practice_speaker_id', practice_binding.speaker_id,
        'eligibility_result', result_value,
        'idempotency_key', p_idempotency_key
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-speaker-eligibility:' || p_idempotency_key, 0
    ));
    SELECT * INTO existing
      FROM public.mlc3_comparison_speaker_eligibility_revisions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.eligibility_sha256 <> result_hash THEN
            RAISE EXCEPTION 'MLC3_SPEAKER_ELIGIBILITY_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    SELECT COALESCE(max(row.revision_number), 0) + 1 INTO next_revision
      FROM public.mlc3_comparison_speaker_eligibility_revisions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.source_recording_attempt_id = p_source_recording_attempt_id
       AND row.practice_recording_attempt_id = p_practice_recording_attempt_id;
    INSERT INTO public.mlc3_comparison_speaker_eligibility_revisions (
        acquisition_principal_id, source_recording_attempt_id,
        practice_recording_attempt_id, source_target_binding_id,
        practice_target_binding_id, source_speaker_id, practice_speaker_id,
        eligibility_result, exclusion_reason, revision_number,
        supersedes_revision_id, eligibility_sha256, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_source_recording_attempt_id,
        p_practice_recording_attempt_id, source_binding.id,
        practice_binding.id, source_binding.speaker_id,
        practice_binding.speaker_id, result_value,
        CASE WHEN result_value = 'same_speaker_eligible' THEN NULL
             ELSE 'speaker_identity_mismatch_or_unresolved' END,
        next_revision,
        (SELECT row.id
           FROM public.mlc3_comparison_speaker_eligibility_revisions row
          WHERE row.acquisition_principal_id = p_acquisition_principal_id
            AND row.source_recording_attempt_id = p_source_recording_attempt_id
            AND row.practice_recording_attempt_id = p_practice_recording_attempt_id
          ORDER BY row.revision_number DESC LIMIT 1),
        result_hash, p_idempotency_key
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.confirm_mlc3_practice_speaker_and_pair_v1(
    p_acquisition_principal_id UUID,
    p_owner_user_id UUID,
    p_practice_attempt_id UUID,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    attempt public.exercise_practice_attempts;
    session_row public.exercise_practice_sessions;
    source_lineage public.exercise_audio_lineages;
    selection public.exercise_practice_selection_revisions;
    speaker_target JSONB;
    eligibility public.mlc3_comparison_speaker_eligibility_revisions;
    pair_row public.exercise_pair_revisions;
    assignment public.exercise_pair_assignments;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'MLC3_PRACTICE_SPEAKER_CONFIRMATION_KEY_REQUIRED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-practice-speaker-pair:' || p_practice_attempt_id::TEXT, 0
    ));
    SELECT * INTO STRICT attempt
      FROM public.exercise_practice_attempts row
     WHERE row.id = p_practice_attempt_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = public.current_mlc3_operation_mode_v2()
       AND row.state NOT IN ('cancelled', 'quarantined')
     FOR SHARE;
    SELECT * INTO STRICT session_row
      FROM public.require_exercise_practice_service_live_v1(
          attempt.session_id, p_acquisition_principal_id
      );
    SELECT * INTO STRICT source_lineage
      FROM public.exercise_audio_lineages row
     WHERE row.id = session_row.source_audio_lineage_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
     FOR SHARE;
    SELECT * INTO STRICT selection
      FROM public.exercise_practice_selection_revisions row
     WHERE row.session_id = session_row.id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.selected_attempt_id = attempt.id
       AND row.selection_state = 'selected_first_valid'
       AND row.operation_mode = public.current_mlc3_operation_mode_v2()
     ORDER BY row.revision DESC, row.id DESC LIMIT 1 FOR SHARE;
    speaker_target := public.record_mlc3_practice_self_speaker_target_v1(
        p_acquisition_principal_id, p_owner_user_id, attempt.id,
        p_idempotency_key || ':speaker'
    );
    eligibility := public.freeze_mlc3_same_speaker_eligibility_v1(
        p_acquisition_principal_id, source_lineage.recording_attempt_id,
        attempt.processing_recording_attempt_id,
        p_idempotency_key || ':eligibility'
    );
    IF eligibility.eligibility_result <> 'same_speaker_eligible' THEN
        RETURN jsonb_build_object(
            'speaker_target', speaker_target,
            'eligibility_result', eligibility.eligibility_result,
            'owner_pair', NULL,
            'dataset_eligible', false
        );
    END IF;
    pair_row := public.freeze_exercise_service_pair_v1(
        session_row.id, p_acquisition_principal_id, selection.id,
        selection.revision, p_idempotency_key || ':pair'
    );
    assignment := public.assign_exercise_service_owner_pair_v1(
        pair_row.id, p_acquisition_principal_id,
        p_idempotency_key || ':owner-pair'
    );
    RETURN jsonb_build_object(
        'speaker_target', speaker_target,
        'eligibility_result', eligibility.eligibility_result,
        'owner_pair', jsonb_build_object(
            'pair_revision_id', pair_row.id,
            'pair_assignment_id', assignment.id,
            'left_clip', assignment.left_clip,
            'right_clip', assignment.right_clip,
            'answer_taxonomy_version',
                'paired-listening-preference-five-state-v1'
        ),
        'dataset_eligible', false
    );
END;
$$;

ALTER TABLE public.exercise_pair_revisions
    ADD COLUMN IF NOT EXISTS speaker_eligibility_revision_id UUID
        REFERENCES public.mlc3_comparison_speaker_eligibility_revisions(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS speaker_identity_sha256 TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'public.exercise_pair_revisions'::regclass
           AND conname = 'exercise_pair_revisions_speaker_identity_check'
    ) THEN
        ALTER TABLE public.exercise_pair_revisions
            ADD CONSTRAINT exercise_pair_revisions_speaker_identity_check
            CHECK (
                operation_mode NOT IN ('cohort_service', 'general_service')
                OR (speaker_eligibility_revision_id IS NOT NULL
                    AND speaker_identity_sha256 ~ '^[0-9a-f]{64}$')
            );
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.prepare_mlc3_pair_speaker_identity_v1()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    source_attempt_id UUID;
    practice_attempt_id UUID;
    eligibility public.mlc3_comparison_speaker_eligibility_revisions;
BEGIN
    IF public.current_mlc3_operation_mode_v2() NOT IN (
        'cohort_service', 'general_service'
    ) THEN RETURN NEW; END IF;
    SELECT lineage.recording_attempt_id, attempt.processing_recording_attempt_id
      INTO STRICT source_attempt_id, practice_attempt_id
      FROM public.exercise_practice_sessions session_row
      JOIN public.exercise_audio_lineages lineage
        ON lineage.id = session_row.source_audio_lineage_id
       AND lineage.acquisition_principal_id = NEW.acquisition_principal_id
      JOIN public.exercise_practice_attempts attempt
        ON attempt.id = NEW.practice_attempt_id
       AND attempt.session_id = session_row.id
       AND attempt.acquisition_principal_id = NEW.acquisition_principal_id
     WHERE session_row.id = NEW.practice_session_id
       AND session_row.acquisition_principal_id = NEW.acquisition_principal_id;
    eligibility := public.freeze_mlc3_same_speaker_eligibility_v1(
        NEW.acquisition_principal_id, source_attempt_id, practice_attempt_id,
        'pair:' || NEW.idempotency_key
    );
    IF eligibility.eligibility_result <> 'same_speaker_eligible' THEN
        RAISE EXCEPTION 'speaker_identity_mismatch_or_unresolved';
    END IF;
    NEW.speaker_eligibility_revision_id := eligibility.id;
    NEW.speaker_identity_sha256 := eligibility.eligibility_sha256;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_mlc3_offer_source_speaker_v1()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE source_attempt_id UUID;
DECLARE source_revision public.mlc3_speaker_acquisition_revisions;
DECLARE source_binding public.mlc3_target_speaker_bindings;
BEGIN
    IF public.current_mlc3_operation_mode_v2() NOT IN (
        'cohort_service', 'general_service'
    ) THEN RETURN NEW; END IF;
    SELECT lineage.recording_attempt_id INTO STRICT source_attempt_id
      FROM public.exercise_audio_lineages lineage
     WHERE lineage.id = NEW.source_audio_lineage_id
       AND lineage.acquisition_principal_id = NEW.acquisition_principal_id
       AND lineage.take_id = NEW.source_take_id
     FOR SHARE;
    SELECT * INTO source_revision
      FROM public.mlc3_speaker_acquisition_revisions row
     WHERE row.acquisition_principal_id = NEW.acquisition_principal_id
       AND row.recording_attempt_id = source_attempt_id
       AND row.speaker_identity_status = 'resolved'
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    IF source_revision.id IS NOT NULL THEN
        SELECT * INTO source_binding
          FROM public.mlc3_target_speaker_bindings row
         WHERE row.acquisition_revision_id = source_revision.id
           AND row.clip_id = (
               SELECT lineage.snippet_id
                 FROM public.exercise_audio_lineages lineage
                WHERE lineage.id = NEW.source_audio_lineage_id
           )
           AND row.binding_state = 'active'
         ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    END IF;
    IF source_binding.id IS NULL
       OR source_binding.speaker_id <> source_revision.speaker_id
    THEN RAISE EXCEPTION 'speaker_identity_mismatch_or_unresolved'; END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS a0_mlc3_offer_source_speaker
    ON public.exercise_service_offers;
CREATE TRIGGER a0_mlc3_offer_source_speaker
BEFORE INSERT ON public.exercise_service_offers FOR EACH ROW
EXECUTE FUNCTION public.require_mlc3_offer_source_speaker_v1();

DROP TRIGGER IF EXISTS a0_mlc3_pair_speaker_identity
    ON public.exercise_pair_revisions;
CREATE TRIGGER a0_mlc3_pair_speaker_identity
BEFORE INSERT ON public.exercise_pair_revisions FOR EACH ROW
EXECUTE FUNCTION public.prepare_mlc3_pair_speaker_identity_v1();

-- Revalidate the exact speaker evidence frozen into a pair at every later
-- assignment/judgment boundary. The two attempt locks are ordered so a
-- correction and a preference can never commit across one another.
CREATE OR REPLACE FUNCTION public.require_mlc3_current_pair_speaker_identity_v1(
    p_pair_revision_id UUID,
    p_acquisition_principal_id UUID
) RETURNS public.mlc3_comparison_speaker_eligibility_revisions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    pair_row public.exercise_pair_revisions;
    eligibility public.mlc3_comparison_speaker_eligibility_revisions;
    source_revision public.mlc3_speaker_acquisition_revisions;
    practice_revision public.mlc3_speaker_acquisition_revisions;
    source_binding public.mlc3_target_speaker_bindings;
    practice_binding public.mlc3_target_speaker_bindings;
BEGIN
    SELECT * INTO STRICT pair_row
      FROM public.exercise_pair_revisions row
     WHERE row.id = p_pair_revision_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode IN ('cohort_service', 'general_service')
       AND row.speaker_eligibility_revision_id IS NOT NULL
       AND row.speaker_identity_sha256 IS NOT NULL;
    SELECT * INTO STRICT eligibility
      FROM public.mlc3_comparison_speaker_eligibility_revisions row
     WHERE row.id = pair_row.speaker_eligibility_revision_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.eligibility_result = 'same_speaker_eligible'
       AND row.eligibility_sha256 = pair_row.speaker_identity_sha256;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-speaker-attempt:' || least(
            eligibility.source_recording_attempt_id,
            eligibility.practice_recording_attempt_id
        )::TEXT, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-speaker-attempt:' || greatest(
            eligibility.source_recording_attempt_id,
            eligibility.practice_recording_attempt_id
        )::TEXT, 0
    ));
    PERFORM public.require_mlc3_service_access_v2(
        p_acquisition_principal_id,
        pair_row.rollout_revision_id,
        pair_row.enrollment_revision_id
    );
    SELECT * INTO STRICT pair_row
      FROM public.exercise_pair_revisions row
     WHERE row.id = p_pair_revision_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.speaker_eligibility_revision_id = eligibility.id
       AND row.speaker_identity_sha256 = eligibility.eligibility_sha256
     FOR SHARE;
    SELECT * INTO STRICT eligibility
      FROM public.mlc3_comparison_speaker_eligibility_revisions row
     WHERE row.id = pair_row.speaker_eligibility_revision_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.eligibility_result = 'same_speaker_eligible'
       AND row.eligibility_sha256 = pair_row.speaker_identity_sha256
     FOR SHARE;
    SELECT * INTO source_revision
      FROM public.mlc3_speaker_acquisition_revisions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = eligibility.source_recording_attempt_id
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    SELECT * INTO practice_revision
      FROM public.mlc3_speaker_acquisition_revisions row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = eligibility.practice_recording_attempt_id
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    SELECT * INTO source_binding
      FROM public.mlc3_target_speaker_bindings row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = eligibility.source_recording_attempt_id
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    SELECT * INTO practice_binding
      FROM public.mlc3_target_speaker_bindings row
     WHERE row.acquisition_principal_id = p_acquisition_principal_id
       AND row.recording_attempt_id = eligibility.practice_recording_attempt_id
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    IF source_revision.id IS NULL OR practice_revision.id IS NULL
       OR source_binding.id IS NULL OR practice_binding.id IS NULL
       OR source_binding.binding_state <> 'active'
       OR practice_binding.binding_state <> 'active'
       OR source_revision.speaker_identity_status <> 'resolved'
       OR practice_revision.speaker_identity_status <> 'resolved'
       OR source_revision.id <> source_binding.acquisition_revision_id
       OR practice_revision.id <> practice_binding.acquisition_revision_id
       OR source_binding.id <> eligibility.source_target_binding_id
       OR practice_binding.id <> eligibility.practice_target_binding_id
       OR source_binding.speaker_id <> source_revision.speaker_id
       OR practice_binding.speaker_id <> practice_revision.speaker_id
       OR source_binding.speaker_id <> practice_binding.speaker_id
       OR source_binding.speaker_id <> eligibility.source_speaker_id
       OR practice_binding.speaker_id <> eligibility.practice_speaker_id
    THEN
        RAISE EXCEPTION 'speaker_identity_mismatch_or_unresolved';
    END IF;
    RETURN eligibility;
END;
$$;

-- Expand service-mode constraints without touching historical values.
DO $$
DECLARE item RECORD; definition TEXT; expanded TEXT;
BEGIN
    FOR item IN
        SELECT constraint_row.oid, relation.relname AS table_name,
               constraint_row.conname
          FROM pg_constraint constraint_row
          JOIN pg_class relation ON relation.oid = constraint_row.conrelid
          JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace
         WHERE namespace.nspname = 'public'
           AND constraint_row.contype = 'c'
           AND pg_get_constraintdef(constraint_row.oid)
               LIKE '%operation_mode%allowlisted_service%'
           AND pg_get_constraintdef(constraint_row.oid)
               NOT LIKE '%general_service%'
    LOOP
        definition := pg_get_constraintdef(item.oid);
        expanded := replace(
            definition,
            'ARRAY[''synthetic_dark''::text, ''allowlisted_service''::text]',
            'ARRAY[''synthetic_dark''::text, ''allowlisted_service''::text, '
            '''cohort_service''::text, ''general_service''::text]'
        );
        expanded := replace(
            expanded,
            'operation_mode = ''allowlisted_service''::text',
            'operation_mode = ANY (ARRAY[''allowlisted_service''::text, '
            '''cohort_service''::text, ''general_service''::text])'
        );
        EXECUTE format(
            'ALTER TABLE public.%I DROP CONSTRAINT %I',
            item.table_name, item.conname
        );
        EXECUTE format(
            'ALTER TABLE public.%I ADD CONSTRAINT %I %s',
            item.table_name, item.conname, expanded
        );
    END LOOP;
END;
$$;

-- Add exact rollout lineage to every principal-bound operation-mode table.
DO $$
DECLARE table_name TEXT;
BEGIN
    FOR table_name IN
        SELECT DISTINCT column_row.table_name
          FROM information_schema.columns column_row
         WHERE column_row.table_schema = 'public'
           AND column_row.column_name = 'operation_mode'
           AND column_row.table_name NOT LIKE 'mlc3\_%' ESCAPE '\'
           AND EXISTS (
               SELECT 1 FROM information_schema.columns principal_column
                WHERE principal_column.table_schema = 'public'
                  AND principal_column.table_name = column_row.table_name
                  AND principal_column.column_name = 'acquisition_principal_id'
           )
    LOOP
        EXECUTE format(
            'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS '
            'rollout_revision_id UUID REFERENCES '
            'public.mlc3_service_rollout_revisions(id) ON DELETE RESTRICT',
            table_name
        );
        EXECUTE format(
            'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS '
            'enrollment_revision_id UUID REFERENCES '
            'public.mlc3_service_enrollment_revisions(id) ON DELETE RESTRICT',
            table_name
        );
        EXECUTE format(
            'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS '
            'access_resolver_version TEXT', table_name
        );
        EXECUTE format(
            'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS '
            'rollout_identity_sha256 TEXT', table_name
        );
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint constraint_row
             JOIN pg_class relation ON relation.oid = constraint_row.conrelid
            WHERE relation.relname = table_name
              AND constraint_row.conname =
                  table_name || '_rollout_lineage_check'
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK ('
                'operation_mode NOT IN (''cohort_service'', ''general_service'') '
                'OR (rollout_revision_id IS NOT NULL '
                'AND enrollment_revision_id IS NOT NULL '
                'AND access_resolver_version = '
                '''require-mlc3-service-access-v2'' '
                'AND rollout_identity_sha256 ~ ''^[0-9a-f]{64}$''))',
                table_name, table_name || '_rollout_lineage_check'
            );
        END IF;
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.prepare_mlc3_rollout_service_row_v2()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    rollout_id UUID;
    enrollment_id UUID;
    mode_value TEXT;
BEGIN
    mode_value := NULLIF(
        current_setting('willab.mlc3_operation_mode', true), ''
    );
    IF NEW.operation_mode IN ('cohort_service', 'general_service')
       AND mode_value NOT IN ('cohort_service', 'general_service') THEN
        RAISE EXCEPTION 'MLC3_EXACT_ROLLOUT_LINEAGE_REQUIRED';
    END IF;
    IF mode_value NOT IN ('cohort_service', 'general_service') THEN
        RETURN NEW;
    END IF;
    rollout_id := NULLIF(
        current_setting('willab.mlc3_rollout_revision_id', true), ''
    )::UUID;
    enrollment_id := NULLIF(
        current_setting('willab.mlc3_enrollment_revision_id', true), ''
    )::UUID;
    IF rollout_id IS NULL OR enrollment_id IS NULL THEN
        RAISE EXCEPTION 'MLC3_EXACT_ROLLOUT_LINEAGE_REQUIRED';
    END IF;
    -- Released wrappers either write the historical allowlisted literal or
    -- omit the column and receive the historical synthetic_dark default.
    -- Transaction-local authority from the central resolver is required
    -- before either legacy default can be promoted into a D4 service mode.
    IF NEW.operation_mode IN ('allowlisted_service', 'synthetic_dark') THEN
        NEW.operation_mode := mode_value;
    ELSIF NEW.operation_mode <> mode_value THEN
        RAISE EXCEPTION 'MLC3_OPERATION_MODE_REPLAY_CONFLICT';
    END IF;
    NEW.rollout_revision_id := rollout_id;
    NEW.enrollment_revision_id := enrollment_id;
    NEW.access_resolver_version := 'require-mlc3-service-access-v2';
    IF COALESCE(to_jsonb(NEW)->>'dataset_eligible', 'false') = 'true' THEN
        RAISE EXCEPTION 'MLC3_GENERAL_SERVICE_DATASET_FORBIDDEN';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.mlc3_service_enrollment_revisions enrollment
         WHERE enrollment.id = enrollment_id
           AND enrollment.rollout_revision_id = rollout_id
           AND enrollment.acquisition_principal_id =
               NEW.acquisition_principal_id
           AND enrollment.operation_mode = mode_value
           AND enrollment.enrollment_state = 'active'
    ) THEN RAISE EXCEPTION 'MLC3_EXACT_ROLLOUT_LINEAGE_REQUIRED'; END IF;
    NEW.rollout_identity_sha256 := public.exercise_json_sha256_v1(
        jsonb_build_object(
            'table_name', TG_TABLE_NAME,
            'row_id', to_jsonb(NEW)->>'id',
            'service_identity_sha256',
                to_jsonb(NEW)->>'service_identity_sha256',
            'rollout_revision_id', rollout_id,
            'enrollment_revision_id', enrollment_id,
            'operation_mode', mode_value,
            'speaker_eligibility_revision_id',
                to_jsonb(NEW)->>'speaker_eligibility_revision_id',
            'speaker_identity_sha256',
                to_jsonb(NEW)->>'speaker_identity_sha256',
            'access_resolver_version', 'require-mlc3-service-access-v2'
        )
    );
    RETURN NEW;
END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOR table_name IN
        SELECT DISTINCT column_row.table_name
          FROM information_schema.columns column_row
         WHERE column_row.table_schema = 'public'
           AND column_row.column_name = 'operation_mode'
           AND column_row.table_name NOT LIKE 'mlc3\_%' ESCAPE '\'
           AND EXISTS (
               SELECT 1 FROM information_schema.columns principal_column
                WHERE principal_column.table_schema = 'public'
                  AND principal_column.table_name = column_row.table_name
                  AND principal_column.column_name = 'acquisition_principal_id'
           )
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS a_mlc3_rollout_lineage_v2 ON public.%I',
            table_name
        );
        EXECUTE format(
            'CREATE TRIGGER a_mlc3_rollout_lineage_v2 BEFORE INSERT ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'public.prepare_mlc3_rollout_service_row_v2()',
            table_name
        );
    END LOOP;
END;
$$;

-- Tables that pre-date operation_mode still need the same exact rollout and
-- enrollment identity. Keep their historical rows nullable and stamp only
-- newly created cohort/general service rows after the central resolver has
-- established transaction-local authority.
CREATE OR REPLACE FUNCTION public.prepare_mlc3_rollout_subject_row_v2()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
DECLARE
    rollout_id UUID;
    enrollment_id UUID;
    mode_value TEXT;
BEGIN
    mode_value := NULLIF(
        current_setting('willab.mlc3_operation_mode', true), ''
    );
    IF mode_value NOT IN ('cohort_service', 'general_service') THEN
        RETURN NEW;
    END IF;
    rollout_id := NULLIF(
        current_setting('willab.mlc3_rollout_revision_id', true), ''
    )::UUID;
    enrollment_id := NULLIF(
        current_setting('willab.mlc3_enrollment_revision_id', true), ''
    )::UUID;
    IF rollout_id IS NULL OR enrollment_id IS NULL THEN
        RAISE EXCEPTION 'MLC3_EXACT_ROLLOUT_LINEAGE_REQUIRED';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.mlc3_service_enrollment_revisions enrollment
         WHERE enrollment.id = enrollment_id
           AND enrollment.rollout_revision_id = rollout_id
           AND enrollment.acquisition_principal_id =
               NEW.acquisition_principal_id
           AND enrollment.operation_mode = mode_value
           AND enrollment.enrollment_state = 'active'
    ) THEN RAISE EXCEPTION 'MLC3_EXACT_ROLLOUT_LINEAGE_REQUIRED'; END IF;
    NEW.rollout_revision_id := rollout_id;
    NEW.enrollment_revision_id := enrollment_id;
    NEW.access_resolver_version := 'require-mlc3-service-access-v2';
    NEW.rollout_operation_mode := mode_value;
    NEW.rollout_identity_sha256 := public.exercise_json_sha256_v1(
        jsonb_build_object(
            'table_name', TG_TABLE_NAME,
            'row_id', to_jsonb(NEW)->>'id',
            'rollout_revision_id', rollout_id,
            'enrollment_revision_id', enrollment_id,
            'operation_mode', mode_value,
            'access_resolver_version', 'require-mlc3-service-access-v2'
        )
    );
    IF COALESCE(to_jsonb(NEW)->>'dataset_eligible', 'false') = 'true' THEN
        RAISE EXCEPTION 'MLC3_GENERAL_SERVICE_DATASET_FORBIDDEN';
    END IF;
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    target_table TEXT;
    has_mode BOOLEAN;
    constraint_name TEXT;
BEGIN
    FOREACH target_table IN ARRAY ARRAY[
        'coach_guidance_attachment_versions', 'coach_guidance_attachments',
        'coach_guidance_independent_media_reviews',
        'coach_guidance_lifecycle_events', 'coach_guidance_media_bindings',
        'coach_guidance_media_validity_events',
        'coach_guidance_reveal_accesses',
        'coach_guidance_reveal_grant_judgments',
        'coach_guidance_reveal_grants', 'coach_guidance_review_batches',
        'coach_guidance_review_frame_items', 'coach_guidance_review_frames',
        'coach_guidance_upload_events', 'coach_guidance_upload_permits',
        'coach_guidance_upload_recoveries',
        'coach_inline_context_assessments', 'coach_inline_exercise_drafts',
        'coach_inline_exercise_eligibility_reviews',
        'coach_inline_source_roles', 'exercise_practice_attempts',
        'exercise_practice_events', 'exercise_practice_measurement_revisions',
        'exercise_practice_selection_revisions',
        'exercise_practice_sessions', 'exercise_practice_transcription_runs',
        'exercise_practice_upload_recoveries',
        'exercise_practice_validity_assessments',
        'exercise_service_acquisition_receipts',
        'exercise_service_blind_reveal_accesses',
        'exercise_service_blind_reveal_grants',
        'exercise_service_blind_review_sets',
        'exercise_service_confidence_assignments',
        'exercise_service_confidence_judgments',
        'exercise_service_confidence_render_receipts',
        'exercise_service_offer_candidates', 'exercise_service_offer_events',
        'exercise_service_offers', 'exercise_service_requests',
        'feedback_v3_membership_items', 'feedback_v3_memberships',
        'feedback_v3_owner_responses', 'feedback_v3_service_render_receipts',
        'feedback_v3_service_response_bindings'
    ] LOOP
        IF to_regclass('public.' || target_table) IS NULL THEN
            RAISE EXCEPTION 'MLC3_RUNTIME_TABLE_MISSING:%', target_table;
        END IF;
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns column_row
             WHERE column_row.table_schema = 'public'
               AND column_row.table_name = target_table
               AND column_row.column_name = 'operation_mode'
        ) INTO has_mode;
        EXECUTE format(
            'ALTER TABLE public.%I '
            'ADD COLUMN IF NOT EXISTS rollout_revision_id UUID NULL '
            'REFERENCES public.mlc3_service_rollout_revisions(id) '
            'ON DELETE RESTRICT, '
            'ADD COLUMN IF NOT EXISTS enrollment_revision_id UUID NULL '
            'REFERENCES public.mlc3_service_enrollment_revisions(id) '
            'ON DELETE RESTRICT, '
            'ADD COLUMN IF NOT EXISTS access_resolver_version TEXT NULL, '
            'ADD COLUMN IF NOT EXISTS rollout_identity_sha256 TEXT NULL',
            target_table
        );
        constraint_name := substr(target_table, 1, 35) ||
            '_rollout_principal_fk';
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint constraint_row
             WHERE constraint_row.conrelid =
                   to_regclass('public.' || target_table)
               AND constraint_row.conname = constraint_name
        ) THEN
            EXECUTE format(
                'ALTER TABLE public.%I ADD CONSTRAINT %I FOREIGN KEY '
                '(enrollment_revision_id, acquisition_principal_id, '
                'rollout_revision_id) REFERENCES '
                'public.mlc3_service_enrollment_revisions('
                'id, acquisition_principal_id, rollout_revision_id) '
                'ON DELETE RESTRICT', target_table, constraint_name
            );
        END IF;
        IF NOT has_mode THEN
            EXECUTE format(
                'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS '
                'rollout_operation_mode TEXT NULL', target_table
            );
            constraint_name := substr(target_table, 1, 35) ||
                '_rollout_subject_check';
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint constraint_row
                 WHERE constraint_row.conrelid =
                       to_regclass('public.' || target_table)
                   AND constraint_row.conname = constraint_name
            ) THEN
                EXECUTE format(
                    'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK ('
                    'rollout_operation_mode IS NULL OR ('
                    'rollout_operation_mode IN ('
                    '''cohort_service'',''general_service'') AND '
                    'rollout_revision_id IS NOT NULL AND '
                    'enrollment_revision_id IS NOT NULL AND '
                    'access_resolver_version = '
                    '''require-mlc3-service-access-v2'' AND '
                    'rollout_identity_sha256 ~ ''^[0-9a-f]{64}$''))',
                    target_table, constraint_name
                );
            END IF;
            EXECUTE format(
                'DROP TRIGGER IF EXISTS a_mlc3_rollout_lineage_v2 '
                'ON public.%I', target_table
            );
            EXECUTE format(
                'CREATE TRIGGER a_mlc3_rollout_lineage_v2 BEFORE INSERT '
                'ON public.%I FOR EACH ROW EXECUTE FUNCTION '
                'public.prepare_mlc3_rollout_subject_row_v2()', target_table
            );
        END IF;
    END LOOP;
END;
$$;

-- Deterministically replace the old service-mode literal only inside the
-- exact reviewed runtime functions that still carry it. Reapply is a no-op.
DO $$
DECLARE signature TEXT; function_oid REGPROCEDURE; definition TEXT;
BEGIN
    FOREACH signature IN ARRAY ARRAY[
        'public.ack_exercise_practice_service_upload_v1(uuid,uuid,text,bigint,text)',
        'public.assign_exercise_service_owner_pair_v1(uuid,uuid,text)',
        'public.attach_exercise_practice_service_attempt_v1(uuid,uuid,uuid,uuid,uuid,text,integer,timestamptz,timestamptz,jsonb,text)',
        'public.authorize_exercise_practice_transcription_v1(uuid,uuid,uuid,uuid,uuid,text,text,text,text,text,text,text)',
        'public.create_coach_guidance_service_attachment_v1(uuid,uuid,uuid,uuid,text,text,text,uuid,uuid,uuid,uuid,text,text,text,text,text)',
        'public.create_coach_inline_exercise_attachment_v1(uuid,uuid,uuid,uuid,uuid,text,uuid,uuid,uuid,text,text,text,text,text)',
        'public.create_coach_inline_exercise_draft_v1(uuid,uuid,text,text,text,text[],text)',
        'public.create_exercise_practice_service_session_v1(uuid,uuid,uuid,text)',
        'public.finalize_coach_guidance_service_media_v1(uuid,uuid,text,boolean,text,text,text,text,text,text)',
        'public.finalize_exercise_practice_service_media_v1(uuid,uuid,uuid,uuid,text,text)',
        'public.freeze_exercise_practice_service_selection_v1(uuid,uuid,integer,integer,text)',
        'public.freeze_exercise_service_blind_review_set_v1(uuid,uuid,text)',
        'public.freeze_exercise_service_offer_v2(uuid,uuid,uuid,uuid,text)',
        'public.freeze_exercise_service_pair_v1(uuid,uuid,uuid,integer,text)',
        'public.freeze_feedback_v3_service_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text)',
        'public.prepare_coach_inline_blind_batch_v1(uuid,uuid,uuid,text)',
        'public.prepare_coach_inline_guidance_context_v1(uuid,uuid,uuid,text)',
        'public.prepare_exercise_practice_service_row_v1()',
        'public.prepare_exercise_service_row_v1()',
        'public.prepare_feedback_v3_service_context_v1(uuid,uuid,uuid,text)',
        'public.prepare_feedback_v3_service_row_v1()',
        'public.publish_coach_guidance_service_exercise_v1(uuid,uuid,text,text,text,text)',
        'public.record_coach_guidance_service_event_v1(uuid,uuid,text,uuid,jsonb,text)',
        'public.record_coach_guidance_service_upload_event_v1(uuid,uuid,text,text,bigint,text)',
        'public.record_exercise_offer_service_event_v1(uuid,uuid,uuid,text,uuid,text,jsonb,timestamptz,text)',
        'public.record_exercise_practice_service_event_v1(uuid,uuid,uuid,uuid,text,uuid,text,jsonb,timestamptz,text)',
        'public.record_exercise_practice_service_measurement_v1(uuid,integer,text,text,jsonb,jsonb,text)',
        'public.record_exercise_practice_service_validity_v1(uuid,uuid,integer,text,text[],text,text)',
        'public.record_feedback_v3_service_response_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text)',
        'public.require_coach_guidance_service_access_v1(uuid,uuid,text)',
        'public.require_coach_guidance_service_media_live_v1(uuid,uuid)',
        'public.require_exercise_practice_service_live_v1(uuid,uuid)',
        'public.require_feedback_v3_service_membership_live_v1(uuid,uuid)',
        'public.reserve_coach_guidance_service_upload_v1(uuid,uuid,text,text,text,text,bigint,text,timestamptz,text)',
        'public.reserve_exercise_practice_service_upload_v1(uuid,uuid,uuid,text,bigint,text,text,text,integer)',
        'public.resolve_coach_guidance_service_media_read_v1(uuid,uuid)',
        'public.resolve_exercise_practice_media_read_v1(uuid,uuid)',
        'public.resolve_exercise_service_offer_read_v1(uuid,uuid)',
        'public.submit_exercise_service_owner_pair_judgment_v1(uuid,uuid,text,text)'
    ] LOOP
        function_oid := to_regprocedure(signature);
        IF function_oid IS NULL THEN
            RAISE EXCEPTION 'MLC3_RUNTIME_FUNCTION_MISSING: %', signature;
        END IF;
        definition := pg_get_functiondef(function_oid);
        IF position('''allowlisted_service''' IN definition) > 0 THEN
            definition := replace(
                definition,
                '''allowlisted_service''',
                'public.current_mlc3_operation_mode_v2()'
            );
            EXECUTE definition;
        ELSIF position('current_mlc3_operation_mode_v2()' IN definition) = 0 THEN
            RAISE EXCEPTION 'MLC3_RUNTIME_FUNCTION_CUTOVER_CONFLICT: %', signature;
        END IF;
    END LOOP;
END;
$$;

-- Cut every runtime wrapper over to the rollout-aware resolver. The sole
-- wrapper that needs the content-contract row resolves it separately after
-- authorization; it does not use the historical resolver as authority.
DO $$
DECLARE signature TEXT; function_oid REGPROCEDURE; definition TEXT;
BEGIN
    FOREACH signature IN ARRAY ARRAY[
        'public.create_exercise_practice_service_session_v1(uuid,uuid,uuid,text)',
        'public.freeze_feedback_v3_service_membership_v1(uuid,uuid,uuid,uuid,uuid,text,jsonb,text)',
        'public.issue_exercise_service_authority_v1(uuid,uuid,uuid,text,text)',
        'public.record_exercise_offer_service_event_v1(uuid,uuid,uuid,text,uuid,text,jsonb,timestamptz,text)',
        'public.record_exercise_service_acquisition_receipt_v1(uuid,text,uuid,uuid,uuid,uuid,text)',
        'public.record_feedback_v3_service_candidate_set_v1(uuid,uuid,uuid,jsonb)',
        'public.record_feedback_v3_service_response_v1(uuid,uuid,uuid,uuid,uuid,uuid,uuid,uuid,text,text)',
        'public.require_coach_guidance_service_access_v1(uuid,uuid,text)',
        'public.require_exercise_practice_service_live_v1(uuid,uuid)',
        'public.require_feedback_v3_service_membership_live_v1(uuid,uuid)',
        'public.require_feedback_v3_service_response_v1(uuid,uuid,uuid,uuid,uuid)',
        'public.resolve_exercise_service_offer_read_v1(uuid,uuid)'
    ] LOOP
        function_oid := to_regprocedure(signature);
        IF function_oid IS NULL THEN
            RAISE EXCEPTION 'MLC3_RUNTIME_FUNCTION_MISSING: %', signature;
        END IF;
        definition := pg_get_functiondef(function_oid);
        IF position('require_mlc3_service_principal_v1' IN definition) > 0 THEN
            definition := replace(
                definition,
                'public.require_mlc3_service_principal_v1(',
                'public.require_mlc3_service_access_v2('
            );
            EXECUTE definition;
        ELSIF position('require_mlc3_service_access_v2' IN definition) = 0 THEN
            RAISE EXCEPTION 'MLC3_RUNTIME_RESOLVER_CUTOVER_CONFLICT: %',
                signature;
        END IF;
    END LOOP;

    signature :=
        'public.reserve_exercise_practice_service_upload_v1(uuid,uuid,uuid,text,bigint,text,text,text,integer)';
    function_oid := to_regprocedure(signature);
    IF function_oid IS NULL THEN
        RAISE EXCEPTION 'MLC3_RUNTIME_FUNCTION_MISSING: %', signature;
    END IF;
    definition := pg_get_functiondef(function_oid);
    IF position('contract := public.require_mlc3_service_principal_v1' IN definition) > 0 THEN
        definition := replace(
            definition,
            'contract := public.require_mlc3_service_principal_v1('
            || E'\n        p_acquisition_principal_id\n    );',
            'PERFORM public.require_mlc3_service_access_v2('
            || E'\n        p_acquisition_principal_id, NULL, NULL\n    );'
            || E'\n    SELECT * INTO STRICT contract'
            || E'\n      FROM public.mlc3_service_contracts row'
            || E'\n     WHERE row.contract_version = '
            || '''mlc3-first-client-service-v1'';'
        );
        IF position('require_mlc3_service_principal_v1' IN definition) > 0 THEN
            RAISE EXCEPTION 'MLC3_RUNTIME_RESOLVER_CUTOVER_CONFLICT: %',
                signature;
        END IF;
        EXECUTE definition;
    ELSIF position('require_mlc3_service_access_v2' IN definition) = 0 THEN
        RAISE EXCEPTION 'MLC3_RUNTIME_RESOLVER_CUTOVER_CONFLICT: %',
            signature;
    END IF;
END;
$$;

-- Rebuild the service owner pair boundaries explicitly so assignment,
-- judgment creation and exact replay all retain the ordered identity locks
-- held by the current-pair guard.
CREATE OR REPLACE FUNCTION public.assign_exercise_service_owner_pair_v1(
    p_pair_revision_id UUID,
    p_acquisition_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_pair_assignments
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    pair_row public.exercise_pair_revisions;
    practice public.exercise_practice_sessions;
    eligibility public.mlc3_comparison_speaker_eligibility_revisions;
    existing public.exercise_pair_assignments;
    assignment_hash TEXT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_PAIR_ASSIGNMENT_INVALID';
    END IF;
    SELECT * INTO STRICT pair_row
      FROM public.exercise_pair_revisions row
     WHERE row.id = p_pair_revision_id
       AND row.acquisition_principal_id = p_acquisition_principal_id;
    eligibility := public.require_mlc3_current_pair_speaker_identity_v1(
        pair_row.id, p_acquisition_principal_id
    );
    IF pair_row.operation_mode <> public.current_mlc3_operation_mode_v2() THEN
        RAISE EXCEPTION 'MLC3_PAIR_ROLLOUT_IDENTITY_MISMATCH';
    END IF;
    practice := public.require_exercise_practice_service_live_v1(
        pair_row.practice_session_id, p_acquisition_principal_id
    );
    assignment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'pair_revision_id', pair_row.id,
        'pair_sha256', pair_row.pair_sha256,
        'speaker_eligibility_revision_id', eligibility.id,
        'speaker_identity_sha256', eligibility.eligibility_sha256,
        'reviewer_principal_id', p_acquisition_principal_id,
        'reviewer_role', 'owner',
        'left_clip', 'before',
        'right_clip', 'after',
        'context_state', 'owner_nonblind',
        'order_policy_version', 'paired-preference-order-v1',
        'operation_mode', public.current_mlc3_operation_mode_v2(),
        'service_contract_version', 'mlc3-first-client-service-v1'
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-pair-assignment:' || p_idempotency_key, 0
    ));
    practice := public.require_exercise_practice_service_live_v1(
        pair_row.practice_session_id, p_acquisition_principal_id
    );
    SELECT * INTO existing FROM public.exercise_pair_assignments row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.operation_mode <> public.current_mlc3_operation_mode_v2()
           OR existing.pair_revision_id <> pair_row.id
           OR existing.reviewer_principal_id <> p_acquisition_principal_id
           OR existing.assignment_sha256 <> assignment_hash
           OR existing.service_identity_sha256 <> assignment_hash THEN
            RAISE EXCEPTION 'EXERCISE_PAIR_ASSIGNMENT_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_pair_assignments (
        pair_revision_id, acquisition_principal_id,
        reviewer_principal_id, reviewer_role, left_clip, right_clip,
        context_state, order_policy_version, assignment_sha256,
        idempotency_key, operation_mode, service_contract_version,
        service_identity_sha256
    ) VALUES (
        pair_row.id, p_acquisition_principal_id,
        p_acquisition_principal_id, 'owner', 'before', 'after',
        'owner_nonblind', 'paired-preference-order-v1', assignment_hash,
        p_idempotency_key, public.current_mlc3_operation_mode_v2(),
        'mlc3-first-client-service-v1', assignment_hash
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.submit_exercise_service_owner_pair_judgment_v1(
    p_pair_assignment_id UUID,
    p_acquisition_principal_id UUID,
    p_answer TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_pair_judgments
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    assignment public.exercise_pair_assignments;
    pair_row public.exercise_pair_revisions;
    eligibility public.mlc3_comparison_speaker_eligibility_revisions;
    existing public.exercise_pair_judgments;
    judgment_hash TEXT;
BEGIN
    IF p_answer NOT IN (
        'prefer_left', 'prefer_right', 'same', 'not_sure', 'audio_unusable'
    ) OR COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_PAIR_JUDGMENT_INVALID';
    END IF;
    SELECT * INTO STRICT assignment
      FROM public.exercise_pair_assignments row
     WHERE row.id = p_pair_assignment_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.reviewer_principal_id = p_acquisition_principal_id
       AND row.reviewer_role = 'owner';
    SELECT * INTO STRICT pair_row
      FROM public.exercise_pair_revisions row
     WHERE row.id = assignment.pair_revision_id
       AND row.acquisition_principal_id = p_acquisition_principal_id;
    eligibility := public.require_mlc3_current_pair_speaker_identity_v1(
        pair_row.id, p_acquisition_principal_id
    );
    SELECT * INTO STRICT assignment
      FROM public.exercise_pair_assignments row
     WHERE row.id = p_pair_assignment_id
       AND row.pair_revision_id = pair_row.id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.reviewer_principal_id = p_acquisition_principal_id
       AND row.reviewer_role = 'owner'
       AND row.operation_mode = public.current_mlc3_operation_mode_v2()
     FOR SHARE;
    PERFORM public.require_exercise_practice_service_live_v1(
        pair_row.practice_session_id, p_acquisition_principal_id
    );
    judgment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'pair_assignment_id', assignment.id,
        'assignment_sha256', assignment.assignment_sha256,
        'speaker_eligibility_revision_id', eligibility.id,
        'speaker_identity_sha256', eligibility.eligibility_sha256,
        'reviewer_principal_id', p_acquisition_principal_id,
        'answer', p_answer,
        'answer_taxonomy_version',
            'paired-listening-preference-five-state-v1',
        'operation_mode', public.current_mlc3_operation_mode_v2(),
        'service_contract_version', 'mlc3-first-client-service-v1'
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-pair-judgment:' || assignment.id::TEXT, 0
    ));
    PERFORM public.require_exercise_practice_service_live_v1(
        pair_row.practice_session_id, p_acquisition_principal_id
    );
    SELECT * INTO existing FROM public.exercise_pair_judgments row
     WHERE row.pair_assignment_id = assignment.id
        OR row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.operation_mode <> public.current_mlc3_operation_mode_v2()
           OR existing.pair_assignment_id <> assignment.id
           OR existing.reviewer_principal_id <> p_acquisition_principal_id
           OR existing.answer <> p_answer
           OR existing.idempotency_key <> p_idempotency_key
           OR existing.service_identity_sha256 <> judgment_hash THEN
            RAISE EXCEPTION 'EXERCISE_PAIR_JUDGMENT_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_pair_judgments (
        pair_assignment_id, acquisition_principal_id,
        reviewer_principal_id, answer, answer_taxonomy_version,
        idempotency_key, operation_mode, service_contract_version,
        service_identity_sha256
    ) VALUES (
        assignment.id, p_acquisition_principal_id,
        p_acquisition_principal_id, p_answer,
        'paired-listening-preference-five-state-v1', p_idempotency_key,
        public.current_mlc3_operation_mode_v2(),
        'mlc3-first-client-service-v1', judgment_hash
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

-- Keep a versioned public D4 surface while preserving V1's authoritative
-- database allocation of attempt_index and its immutable replay checks.  The
-- released V1 signature has no caller-provided attempt index.
CREATE OR REPLACE FUNCTION public.reserve_exercise_practice_service_upload_v2(
    p_session_id UUID,
    p_acquisition_principal_id UUID,
    p_recording_id UUID,
    p_object_key TEXT,
    p_byte_size BIGINT,
    p_content_type TEXT,
    p_intended_exact_bytes_sha256 TEXT,
    p_idempotency_key TEXT,
    p_ttl_seconds INTEGER DEFAULT 900
) RETURNS public.exercise_practice_upload_recoveries
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
BEGIN
    PERFORM public.require_mlc3_service_access_v2(
        p_acquisition_principal_id, NULL, NULL
    );
    RETURN public.reserve_exercise_practice_service_upload_v1(
        p_session_id, p_acquisition_principal_id, p_recording_id,
        p_object_key, p_byte_size, p_content_type,
        p_intended_exact_bytes_sha256, p_idempotency_key, p_ttl_seconds
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.register_mlc3_activation_risk_decision_v1(
    p_design_sha256 TEXT,
    p_production_backend_commit TEXT,
    p_production_frontend_commit TEXT,
    p_absent_cohort_reason TEXT,
    p_capacity_policy_sha256 TEXT,
    p_founder_user_id UUID,
    p_decided_at TIMESTAMPTZ,
    p_signature_identity TEXT,
    p_evidence_sha256 TEXT
) RETURNS public.mlc3_service_activation_risk_decisions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE existing public.mlc3_service_activation_risk_decisions;
BEGIN
    IF p_design_sha256 <>
           '4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085'
       OR p_production_backend_commit !~ '^[0-9a-f]{40}$'
       OR p_production_frontend_commit !~ '^[0-9a-f]{40}$'
       OR p_capacity_policy_sha256 !~ '^[0-9a-f]{64}$'
       OR p_evidence_sha256 !~ '^[0-9a-f]{64}$'
       OR COALESCE(length(btrim(p_absent_cohort_reason)), 0) = 0
       OR COALESCE(length(btrim(p_signature_identity)), 0) = 0
       OR p_decided_at > clock_timestamp()
    THEN RAISE EXCEPTION 'MLC3_GA_RISK_DECISION_INVALID'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.owner_principals principal
         WHERE principal.user_id = p_founder_user_id
           AND principal.guest_secret_hash IS NULL
    ) THEN RAISE EXCEPTION 'MLC3_GA_FOUNDER_IDENTITY_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-founder-skip-cohort:' || p_evidence_sha256, 0
    ));
    SELECT * INTO existing
      FROM public.mlc3_service_activation_risk_decisions row
     WHERE row.evidence_sha256 = p_evidence_sha256;
    IF existing.id IS NOT NULL THEN
        IF existing.design_sha256 <> p_design_sha256
           OR existing.production_backend_commit <>
              p_production_backend_commit
           OR existing.production_frontend_commit <>
              p_production_frontend_commit
           OR existing.capacity_policy_sha256 <> p_capacity_policy_sha256
           OR existing.founder_user_id <> p_founder_user_id
        THEN RAISE EXCEPTION 'MLC3_GA_RISK_DECISION_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.mlc3_service_activation_risk_decisions (
        decision_kind, design_sha256, production_backend_commit,
        production_frontend_commit, absent_cohort_reason,
        capacity_policy_sha256, founder_user_id, decided_at,
        signature_identity, evidence_sha256, review_state
    ) VALUES (
        'founder_skip_cohort_v1', p_design_sha256,
        p_production_backend_commit, p_production_frontend_commit,
        p_absent_cohort_reason, p_capacity_policy_sha256, p_founder_user_id,
        p_decided_at, p_signature_identity, p_evidence_sha256, 'accepted'
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_mlc3_general_rollout_v2(
    p_required_policy_id UUID,
    p_activation_risk_decision_id UUID,
    p_capacity_policy JSONB,
    p_policy_versions JSONB,
    p_activating_user_id UUID,
    p_effective_at TIMESTAMPTZ,
    p_authorization_evidence_sha256 TEXT
) RETURNS public.mlc3_service_rollout_revisions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    prior public.mlc3_service_rollout_revisions;
    risk public.mlc3_service_activation_risk_decisions;
    result public.mlc3_service_rollout_revisions;
    next_revision INTEGER;
    capacity_hash TEXT;
    rollout_hash TEXT;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'MLC3_SERVICE_REQUIRES_READ_COMMITTED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-rollout-policy-v2', 0
    ));
    SELECT * INTO prior
      FROM public.mlc3_service_rollout_revisions row
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    IF prior.id IS NULL OR prior.rollout_state NOT IN ('disabled', 'halted')
       OR p_effective_at IS NULL
       OR p_authorization_evidence_sha256 !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_capacity_policy) <> 'object'
       OR jsonb_typeof(p_policy_versions) <> 'object'
    THEN RAISE EXCEPTION 'MLC3_GA_ACTIVATION_REQUEST_INVALID'; END IF;
    capacity_hash := public.exercise_json_sha256_v1(p_capacity_policy);
    SELECT * INTO STRICT risk
      FROM public.mlc3_service_activation_risk_decisions row
     WHERE row.id = p_activation_risk_decision_id
       AND row.decision_kind = 'founder_skip_cohort_v1'
       AND row.design_sha256 =
           '4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085'
       AND row.capacity_policy_sha256 = capacity_hash
       AND row.review_state = 'accepted'
     FOR SHARE;
    IF NOT EXISTS (
        SELECT 1
          FROM public.processing_policy_versions policy
         WHERE policy.id = p_required_policy_id
           AND policy.status = 'active'
           AND policy.activated_at <= clock_timestamp()
           AND (policy.retired_at IS NULL
                OR policy.retired_at > clock_timestamp())
           AND NOT EXISTS (
               SELECT 1 FROM (VALUES
                   ('personalized_exercise_recommendation'::TEXT),
                   ('coach_review'::TEXT)
               ) required(purpose_id)
                WHERE NOT EXISTS (
                    SELECT 1
                      FROM public.processing_policy_purposes policy_purpose
                      JOIN public.processing_purpose_registry registry
                        ON registry.id = policy_purpose.purpose_id
                       AND registry.operational
                       AND registry.authorizes_processing
                     WHERE policy_purpose.policy_id = policy.id
                       AND policy_purpose.purpose_id = required.purpose_id
                )
           )
    ) THEN RAISE EXCEPTION 'MLC3_GA_POLICY_NOT_OPERATIONAL'; END IF;
    next_revision := prior.revision_number + 1;
    rollout_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-general-user-service-d4',
        'revision_number', next_revision,
        'previous_revision_id', prior.id,
        'rollout_state', 'generally_available',
        'required_policy_id', p_required_policy_id,
        'activation_risk_decision_id', risk.id,
        'capacity_policy_sha256', capacity_hash,
        'policy_versions', p_policy_versions,
        'activating_user_id', p_activating_user_id,
        'effective_at', p_effective_at,
        'authorization_evidence_sha256', p_authorization_evidence_sha256
    ));
    INSERT INTO public.mlc3_service_rollout_revisions (
        revision_number, previous_revision_id, rollout_state,
        service_contract_version, rollout_contract_version,
        rollout_policy_sha256, access_resolver_version,
        operation_mode_registry_version, required_policy_id,
        personalized_purpose_id, coach_review_purpose_id, approved_need_id,
        activation_risk_decision_id, capacity_policy,
        capacity_policy_sha256, policy_versions,
        backend_gate_contract_version, frontend_gate_contract_version,
        monitor_contract_version, emergency_disable_contract_version,
        activating_user_id, authorization_evidence_sha256, effective_at,
        rollout_sha256
    ) VALUES (
        next_revision, prior.id, 'generally_available',
        'mlc3-first-client-service-v1', 'mlc3-general-user-service-d4',
        '4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085',
        'require-mlc3-service-access-v2',
        'mlc3-operation-mode-registry-v2', p_required_policy_id,
        'personalized_exercise_recommendation', 'coach_review',
        'rushed_phrase_endings', risk.id, p_capacity_policy, capacity_hash,
        p_policy_versions, 'mlc3-service-backend-gate-v2',
        'mlc3-service-frontend-gate-v2',
        'mlc3-general-service-monitor-v1', 'mlc3-five-part-disable-v2',
        p_activating_user_id, p_authorization_evidence_sha256,
        p_effective_at, rollout_hash
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.halt_mlc3_service_rollout_v1(
    p_reason TEXT,
    p_evidence_sha256 TEXT
) RETURNS public.mlc3_service_rollout_revisions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE prior public.mlc3_service_rollout_revisions;
DECLARE result public.mlc3_service_rollout_revisions;
DECLARE halt_hash TEXT;
BEGIN
    IF COALESCE(length(btrim(p_reason)), 0) = 0
       OR p_evidence_sha256 !~ '^[0-9a-f]{64}$'
    THEN RAISE EXCEPTION 'MLC3_ROLLOUT_HALT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-rollout-policy-v2', 0
    ));
    SELECT * INTO STRICT prior
      FROM public.mlc3_service_rollout_revisions row
     ORDER BY row.revision_number DESC LIMIT 1 FOR SHARE;
    IF prior.rollout_state IN ('disabled', 'halted', 'retired') THEN
        RETURN prior;
    END IF;
    halt_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'previous_revision_id', prior.id,
        'revision_number', prior.revision_number + 1,
        'state', 'halted',
        'reason', p_reason,
        'evidence_sha256', p_evidence_sha256
    ));
    INSERT INTO public.mlc3_service_rollout_revisions (
        revision_number, previous_revision_id, rollout_state,
        service_contract_version, rollout_contract_version,
        rollout_policy_sha256, access_resolver_version,
        operation_mode_registry_version, required_policy_id,
        personalized_purpose_id, coach_review_purpose_id, approved_need_id,
        cohort_set_id, activation_risk_decision_id, capacity_policy,
        capacity_policy_sha256, policy_versions,
        backend_gate_contract_version, frontend_gate_contract_version,
        monitor_contract_version, emergency_disable_contract_version,
        authorization_evidence_sha256, rollout_sha256
    ) VALUES (
        prior.revision_number + 1, prior.id, 'halted',
        prior.service_contract_version, prior.rollout_contract_version,
        prior.rollout_policy_sha256, prior.access_resolver_version,
        prior.operation_mode_registry_version, prior.required_policy_id,
        prior.personalized_purpose_id, prior.coach_review_purpose_id,
        prior.approved_need_id, prior.cohort_set_id,
        prior.activation_risk_decision_id, prior.capacity_policy,
        prior.capacity_policy_sha256, prior.policy_versions,
        prior.backend_gate_contract_version,
        prior.frontend_gate_contract_version,
        prior.monitor_contract_version,
        prior.emergency_disable_contract_version,
        p_evidence_sha256, halt_hash
    ) RETURNING * INTO result;
    INSERT INTO public.mlc3_service_backpressure_events (
        rollout_revision_id, typed_state, counter_snapshot, event_sha256
    ) VALUES (
        result.id, 'MLC3_ROLLOUT_HALTED',
        jsonb_build_object('reason', p_reason, 'previous_revision_id', prior.id),
        public.exercise_json_sha256_v1(jsonb_build_object(
            'rollout_revision_id', result.id,
            'typed_state', 'MLC3_ROLLOUT_HALTED',
            'evidence_sha256', p_evidence_sha256
        ))
    );
    RETURN result;
END;
$$;

-- Capacity is enforced where work is reserved, under one rollout-scoped lock.
-- The exception codes are the public, typed backpressure result; PostgreSQL
-- rolls back the rejected reservation so no partial media or assignment row
-- can survive. The aggregate monitor records observed threshold state
-- separately from the rejected transaction.
CREATE OR REPLACE FUNCTION public.enforce_mlc3_service_capacity_v1()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    operation_mode_value TEXT;
    rollout_id_value UUID;
    enrollment_id_value UUID;
    principal_id_value UUID;
    reviewer_id_value UUID;
    rollout public.mlc3_service_rollout_revisions;
    active_uploads BIGINT;
    principal_uploads BIGINT;
    outstanding_assignments BIGINT;
    reviewer_assignments BIGINT;
    oldest_assignment TIMESTAMPTZ;
    media_bytes BIGINT;
    requested_bytes BIGINT := 0;
    unresolved_recoveries BIGINT;
    oldest_recovery TIMESTAMPTZ;
BEGIN
    operation_mode_value := COALESCE(
        to_jsonb(NEW)->>'rollout_operation_mode',
        to_jsonb(NEW)->>'operation_mode'
    );
    IF operation_mode_value NOT IN ('cohort_service', 'general_service') THEN
        RETURN NEW;
    END IF;

    rollout_id_value := NEW.rollout_revision_id;
    enrollment_id_value := NEW.enrollment_revision_id;
    principal_id_value := NEW.acquisition_principal_id;
    reviewer_id_value := NULLIF(
        to_jsonb(NEW)->>'reviewer_principal_id', ''
    )::UUID;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-capacity:' || rollout_id_value::TEXT, 0
    ));
    SELECT * INTO STRICT rollout
      FROM public.mlc3_service_rollout_revisions row
     WHERE row.id = rollout_id_value
       AND row.rollout_state IN ('explicit_cohort', 'generally_available')
       AND row.effective_at <= clock_timestamp()
     FOR SHARE;
    PERFORM public.require_mlc3_service_access_v2(
        principal_id_value, rollout.id, enrollment_id_value
    );

    IF TG_TABLE_NAME IN (
        'exercise_practice_upload_recoveries',
        'coach_guidance_upload_permits'
    ) THEN
        SELECT
            (SELECT count(*)
               FROM public.exercise_practice_upload_recoveries recovery
              WHERE recovery.rollout_revision_id = rollout.id
                AND recovery.operation_mode IN (
                    'cohort_service', 'general_service'
                )
                AND recovery.status IN ('write_started', 'write_acknowledged')
                AND recovery.expires_at > clock_timestamp())
            +
            (SELECT count(*)
               FROM public.coach_guidance_upload_permits permit
              WHERE permit.rollout_revision_id = rollout.id
                AND permit.operation_mode IN (
                    'cohort_service', 'general_service'
                )
                AND permit.expires_at > clock_timestamp()
                AND NOT EXISTS (
                    SELECT 1 FROM public.coach_guidance_upload_events event
                     WHERE event.upload_permit_id = permit.id
                       AND event.event_kind IN ('finalized', 'abandoned')
                ))
          INTO active_uploads;
        IF active_uploads >=
           (rollout.capacity_policy->>'max_concurrent_uploads')::INTEGER
        THEN RAISE EXCEPTION 'MLC3_UPLOAD_CAPACITY_REACHED'; END IF;

        SELECT
            (SELECT count(*)
               FROM public.exercise_practice_upload_recoveries recovery
              WHERE recovery.rollout_revision_id = rollout.id
                AND recovery.acquisition_principal_id = principal_id_value
                AND recovery.status IN ('write_started', 'write_acknowledged')
                AND recovery.expires_at > clock_timestamp())
            +
            (SELECT count(*)
               FROM public.coach_guidance_upload_permits permit
              WHERE permit.rollout_revision_id = rollout.id
                AND permit.acquisition_principal_id = principal_id_value
                AND permit.expires_at > clock_timestamp()
                AND NOT EXISTS (
                    SELECT 1 FROM public.coach_guidance_upload_events event
                     WHERE event.upload_permit_id = permit.id
                       AND event.event_kind IN ('finalized', 'abandoned')
                ))
          INTO principal_uploads;
        IF principal_uploads >=
           (rollout.capacity_policy->>'max_uploads_per_principal')::INTEGER
        THEN RAISE EXCEPTION 'MLC3_UPLOAD_CAPACITY_REACHED'; END IF;

        requested_bytes := COALESCE(
            NULLIF(to_jsonb(NEW)->>'byte_size', '')::BIGINT,
            NULLIF(to_jsonb(NEW)->>'intended_byte_size', '')::BIGINT,
            0
        );
        SELECT
            COALESCE((SELECT sum(recovery.byte_size)
              FROM public.exercise_practice_upload_recoveries recovery
             WHERE recovery.rollout_revision_id = rollout.id
               AND recovery.operation_mode IN (
                   'cohort_service', 'general_service'
               )
               AND recovery.created_at >=
                   clock_timestamp() - interval '24 hours'), 0)
            +
            COALESCE((SELECT sum(permit.intended_byte_size)
              FROM public.coach_guidance_upload_permits permit
             WHERE permit.rollout_revision_id = rollout.id
               AND permit.operation_mode IN (
                   'cohort_service', 'general_service'
               )
               AND permit.created_at >=
                   clock_timestamp() - interval '24 hours'), 0)
          INTO media_bytes;
        IF media_bytes + requested_bytes >
           (rollout.capacity_policy->>'max_media_bytes_per_day')::BIGINT
        THEN RAISE EXCEPTION 'MLC3_MEDIA_BUDGET_REACHED'; END IF;

        SELECT
            (SELECT count(*)
               FROM public.exercise_practice_upload_recoveries recovery
              WHERE recovery.rollout_revision_id = rollout.id
                AND recovery.status IN (
                    'write_started', 'write_acknowledged', 'orphaned'
                ))
            +
            (SELECT count(*)
               FROM public.coach_guidance_upload_recoveries recovery
              WHERE recovery.rollout_revision_id = rollout.id
                AND NOT EXISTS (
                    SELECT 1 FROM public.coach_guidance_upload_events event
                     WHERE event.upload_recovery_id = recovery.id
                       AND event.event_kind IN ('finalized', 'abandoned')
                ))
          INTO unresolved_recoveries;
        SELECT min(created_at) INTO oldest_recovery FROM (
            SELECT recovery.created_at
              FROM public.exercise_practice_upload_recoveries recovery
             WHERE recovery.rollout_revision_id = rollout.id
               AND recovery.status IN (
                   'write_started', 'write_acknowledged', 'orphaned'
               )
            UNION ALL
            SELECT recovery.created_at
              FROM public.coach_guidance_upload_recoveries recovery
             WHERE recovery.rollout_revision_id = rollout.id
               AND NOT EXISTS (
                   SELECT 1 FROM public.coach_guidance_upload_events event
                    WHERE event.upload_recovery_id = recovery.id
                      AND event.event_kind IN ('finalized', 'abandoned')
               )
        ) unresolved;
        IF unresolved_recoveries >=
           (rollout.capacity_policy->>'max_unresolved_recoveries')::INTEGER
           OR (
               oldest_recovery IS NOT NULL
               AND oldest_recovery < clock_timestamp() - make_interval(
                   mins => (rollout.capacity_policy
                       ->>'max_recovery_age_minutes')::INTEGER
               )
           )
        THEN RAISE EXCEPTION 'MLC3_RECOVERY_BACKLOG_BLOCKED'; END IF;
    END IF;

    IF TG_TABLE_NAME = 'coach_inline_source_roles' THEN
        SELECT count(*), min(role.created_at)
          INTO outstanding_assignments, oldest_assignment
          FROM public.coach_inline_source_roles role
         WHERE role.rollout_revision_id = rollout.id
           AND role.rollout_operation_mode IN (
               'cohort_service', 'general_service'
           )
           AND NOT EXISTS (
               SELECT 1 FROM public.ml_judgments judgment
                WHERE judgment.review_assignment_id = role.review_assignment_id
           );
        SELECT count(*) INTO reviewer_assignments
          FROM public.coach_inline_source_roles role
         WHERE role.rollout_revision_id = rollout.id
           AND role.reviewer_principal_id = reviewer_id_value
           AND NOT EXISTS (
               SELECT 1 FROM public.ml_judgments judgment
                WHERE judgment.review_assignment_id = role.review_assignment_id
           );
        IF outstanding_assignments >=
               (rollout.capacity_policy
                   ->>'max_outstanding_assignments')::INTEGER
           OR reviewer_assignments >=
               (rollout.capacity_policy->>'max_assignments_per_coach')::INTEGER
           OR (
               oldest_assignment IS NOT NULL
               AND oldest_assignment < clock_timestamp() - make_interval(
                   hours => (rollout.capacity_policy
                       ->>'max_queue_age_hours')::INTEGER
               )
           )
        THEN RAISE EXCEPTION 'MLC3_COACH_QUEUE_BACKPRESSURE'; END IF;
    END IF;
    RETURN NEW;
END;
$$;

DO $$
DECLARE table_name_value TEXT;
BEGIN
    FOREACH table_name_value IN ARRAY ARRAY[
        'exercise_practice_upload_recoveries',
        'coach_guidance_upload_permits',
        'coach_inline_source_roles'
    ] LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS a1_mlc3_service_capacity ON public.%I',
            table_name_value
        );
        EXECUTE format(
            'DROP TRIGGER IF EXISTS b_mlc3_service_capacity ON public.%I',
            table_name_value
        );
        EXECUTE format(
            'CREATE TRIGGER b_mlc3_service_capacity BEFORE INSERT ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'public.enforce_mlc3_service_capacity_v1()',
            table_name_value
        );
    END LOOP;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_mlc3_general_service_monitor_v1()
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public AS $$
DECLARE rollout public.mlc3_service_rollout_revisions;
DECLARE result JSONB;
DECLARE registered_table RECORD;
DECLARE table_dataset_count BIGINT;
DECLARE dataset_count BIGINT := 0;
BEGIN
    SELECT * INTO STRICT rollout
      FROM public.mlc3_service_rollout_revisions row
     ORDER BY row.revision_number DESC LIMIT 1;
    FOR registered_table IN
        SELECT DISTINCT column_row.table_name
          FROM information_schema.columns column_row
         WHERE column_row.table_schema = 'public'
           AND column_row.column_name = 'dataset_eligible'
           AND EXISTS (
               SELECT 1 FROM information_schema.columns rollout_column
                WHERE rollout_column.table_schema = 'public'
                  AND rollout_column.table_name = column_row.table_name
                  AND rollout_column.column_name = 'rollout_revision_id'
           )
    LOOP
        EXECUTE format(
            'SELECT count(*) FROM public.%I '
            'WHERE rollout_revision_id=$1 AND dataset_eligible',
            registered_table.table_name
        ) INTO table_dataset_count USING rollout.id;
        dataset_count := dataset_count + table_dataset_count;
    END LOOP;
    SELECT jsonb_build_object(
        'monitor_contract_version', 'mlc3-general-service-monitor-v1',
        'rollout_revision_id', rollout.id,
        'rollout_state', rollout.rollout_state,
        'rollout_sha256', rollout.rollout_sha256,
        'capacity_policy_sha256', rollout.capacity_policy_sha256,
        'capacity_policy', rollout.capacity_policy,
        'active_enrollments', (
            SELECT count(*) FROM public.mlc3_service_enrollment_revisions row
             WHERE row.rollout_revision_id = rollout.id
               AND row.enrollment_state = 'active'
               AND NOT EXISTS (
                   SELECT 1 FROM public.mlc3_service_enrollment_revisions later
                    WHERE later.supersedes_enrollment_revision_id = row.id
               )
        ),
        'active_service_rows_without_enrollment', (
            SELECT count(*) FROM public.exercise_service_offers row
             WHERE row.rollout_revision_id = rollout.id
               AND row.operation_mode IN ('cohort_service', 'general_service')
               AND NOT EXISTS (
                   SELECT 1 FROM public.mlc3_service_enrollment_revisions enrolled
                    WHERE enrolled.id = row.enrollment_revision_id
                      AND enrolled.acquisition_principal_id =
                          row.acquisition_principal_id
                      AND enrolled.rollout_revision_id = row.rollout_revision_id
               )
        ),
        'speaker_status_counts', (
            SELECT jsonb_build_object(
                'resolved', count(*) FILTER (
                    WHERE row.speaker_identity_status = 'resolved'
                ),
                'unresolved', count(*) FILTER (
                    WHERE row.speaker_identity_status = 'unresolved'
                ),
                'multiple', count(*) FILTER (
                    WHERE row.speaker_count_status = 'multiple'
                ),
                'unknown', count(*) FILTER (
                    WHERE row.speaker_count_status = 'unknown'
                )
            ) FROM public.mlc3_speaker_acquisition_revisions row
        ),
        'unresolved_practice_recoveries', (
            SELECT count(*)
              FROM public.exercise_practice_upload_recoveries row
             WHERE row.rollout_revision_id = rollout.id
               AND row.status IN (
                   'write_started', 'write_acknowledged', 'orphaned'
               )
        ),
        'unresolved_coach_recoveries', (
            SELECT count(*)
              FROM public.coach_guidance_upload_recoveries recovery
             WHERE recovery.rollout_revision_id = rollout.id
               AND NOT EXISTS (
                   SELECT 1 FROM public.coach_guidance_upload_events event
                    WHERE event.upload_recovery_id = recovery.id
                      AND event.event_kind IN ('finalized', 'abandoned')
               )
        ),
        'oldest_unresolved_recovery_at', (
            SELECT min(created_at) FROM (
                SELECT recovery.created_at
                  FROM public.exercise_practice_upload_recoveries recovery
                 WHERE recovery.rollout_revision_id = rollout.id
                   AND recovery.status IN (
                       'write_started', 'write_acknowledged', 'orphaned'
                   )
                UNION ALL
                SELECT recovery.created_at
                  FROM public.coach_guidance_upload_recoveries recovery
                 WHERE recovery.rollout_revision_id = rollout.id
                   AND NOT EXISTS (
                       SELECT 1 FROM public.coach_guidance_upload_events event
                        WHERE event.upload_recovery_id = recovery.id
                          AND event.event_kind IN ('finalized', 'abandoned')
                   )
            ) unresolved
        ),
        'active_uploads', (
            SELECT
                (SELECT count(*)
                   FROM public.exercise_practice_upload_recoveries recovery
                  WHERE recovery.rollout_revision_id = rollout.id
                    AND recovery.status IN (
                        'write_started', 'write_acknowledged'
                    )
                    AND recovery.expires_at > clock_timestamp())
                +
                (SELECT count(*)
                   FROM public.coach_guidance_upload_permits permit
                  WHERE permit.rollout_revision_id = rollout.id
                    AND permit.expires_at > clock_timestamp()
                    AND NOT EXISTS (
                        SELECT 1 FROM public.coach_guidance_upload_events event
                         WHERE event.upload_permit_id = permit.id
                           AND event.event_kind IN ('finalized', 'abandoned')
                    ))
        ),
        'maximum_active_uploads_per_principal', (
            SELECT COALESCE(max(upload_count), 0) FROM (
                SELECT acquisition_principal_id, count(*) AS upload_count
                  FROM (
                    SELECT recovery.acquisition_principal_id
                      FROM public.exercise_practice_upload_recoveries recovery
                     WHERE recovery.rollout_revision_id = rollout.id
                       AND recovery.status IN (
                           'write_started', 'write_acknowledged'
                       )
                       AND recovery.expires_at > clock_timestamp()
                    UNION ALL
                    SELECT permit.acquisition_principal_id
                      FROM public.coach_guidance_upload_permits permit
                     WHERE permit.rollout_revision_id = rollout.id
                       AND permit.expires_at > clock_timestamp()
                       AND NOT EXISTS (
                           SELECT 1
                             FROM public.coach_guidance_upload_events event
                            WHERE event.upload_permit_id = permit.id
                              AND event.event_kind IN (
                                  'finalized', 'abandoned'
                              )
                       )
                  ) uploads GROUP BY acquisition_principal_id
            ) grouped_uploads
        ),
        'media_bytes_last_24_hours', (
            SELECT
                COALESCE((SELECT sum(recovery.byte_size)
                  FROM public.exercise_practice_upload_recoveries recovery
                 WHERE recovery.rollout_revision_id = rollout.id
                   AND recovery.created_at >=
                       clock_timestamp() - interval '24 hours'), 0)
                +
                COALESCE((SELECT sum(permit.intended_byte_size)
                  FROM public.coach_guidance_upload_permits permit
                 WHERE permit.rollout_revision_id = rollout.id
                   AND permit.created_at >=
                       clock_timestamp() - interval '24 hours'), 0)
        ),
        'outstanding_required_coach_assignments', (
            SELECT count(*)
              FROM public.coach_inline_source_roles role
             WHERE role.rollout_revision_id = rollout.id
               AND NOT EXISTS (
                   SELECT 1 FROM public.ml_judgments judgment
                    WHERE judgment.review_assignment_id =
                        role.review_assignment_id
               )
        ),
        'maximum_outstanding_assignments_per_coach', (
            SELECT COALESCE(max(assignment_count), 0) FROM (
                SELECT role.reviewer_principal_id,
                       count(*) AS assignment_count
                  FROM public.coach_inline_source_roles role
                 WHERE role.rollout_revision_id = rollout.id
                   AND NOT EXISTS (
                       SELECT 1 FROM public.ml_judgments judgment
                        WHERE judgment.review_assignment_id =
                            role.review_assignment_id
                   )
                 GROUP BY role.reviewer_principal_id
            ) coach_counts
        ),
        'oldest_required_coach_assignment_at', (
            SELECT min(role.created_at)
              FROM public.coach_inline_source_roles role
             WHERE role.rollout_revision_id = rollout.id
               AND NOT EXISTS (
                   SELECT 1 FROM public.ml_judgments judgment
                    WHERE judgment.review_assignment_id =
                        role.review_assignment_id
               )
        ),
        'service_failure_count', (
            SELECT
                (SELECT count(*)
                   FROM public.exercise_practice_transcription_runs row
                  WHERE row.rollout_revision_id = rollout.id
                    AND row.status IN ('uncertain', 'failed'))
                +
                (SELECT count(*)
                   FROM public.coach_guidance_publication_invalidations row
                  WHERE row.operation_mode IN (
                      'cohort_service', 'general_service'
                  ))
        ),
        'dataset_eligible_rows', dataset_count,
        'checked_at', clock_timestamp()
    ) INTO result;
    RETURN result;
END;
$$;

-- Seed only the disabled initial policy. Fixed identity makes reapply exact.
INSERT INTO public.mlc3_service_rollout_revisions (
    id, revision_number, rollout_state, service_contract_version,
    rollout_contract_version, rollout_policy_sha256,
    access_resolver_version, operation_mode_registry_version,
    personalized_purpose_id, coach_review_purpose_id, approved_need_id,
    capacity_policy, capacity_policy_sha256, policy_versions,
    backend_gate_contract_version, frontend_gate_contract_version,
    monitor_contract_version, emergency_disable_contract_version,
    authorization_evidence_sha256, rollout_sha256
) VALUES (
    '8e451a9f-bb89-4e12-ae21-2a24ef7df401', 1, 'disabled',
    'mlc3-first-client-service-v1', 'mlc3-general-user-service-d4',
    '4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085',
    'require-mlc3-service-access-v2', 'mlc3-operation-mode-registry-v2',
    'personalized_exercise_recommendation', 'coach_review',
    'rushed_phrase_endings',
    '{"max_concurrent_enrollments":20,"max_new_enrollments_per_hour":50,"max_concurrent_uploads":10,"max_uploads_per_principal":2,"max_outstanding_assignments":500,"max_assignments_per_coach":100,"max_queue_age_hours":72,"max_media_bytes_per_day":10737418240,"max_unresolved_recoveries":25,"max_recovery_age_minutes":15}'::JSONB,
    public.exercise_json_sha256_v1(
        '{"max_concurrent_enrollments":20,"max_new_enrollments_per_hour":50,"max_concurrent_uploads":10,"max_uploads_per_principal":2,"max_outstanding_assignments":500,"max_assignments_per_coach":100,"max_queue_age_hours":72,"max_media_bytes_per_day":10737418240,"max_unresolved_recoveries":25,"max_recovery_age_minutes":15}'::JSONB
    ),
    '{"language":"review-required","safety":"review-required","rights":"review-required","retention":"review-required","deletion":"review-required","media":"review-required"}'::JSONB,
    'mlc3-service-backend-gate-v2', 'mlc3-service-frontend-gate-v2',
    'mlc3-general-service-monitor-v1', 'mlc3-five-part-disable-v2',
    '4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085',
    public.exercise_json_sha256_v1(jsonb_build_object(
        'id', '8e451a9f-bb89-4e12-ae21-2a24ef7df401',
        'revision_number', 1,
        'rollout_state', 'disabled',
        'design_sha256',
            '4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085'
    ))
) ON CONFLICT (revision_number) DO NOTHING;

REVOKE ALL ON FUNCTION public.resolve_mlc3_dual_purpose_receipt_v2(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.current_mlc3_operation_mode_v2()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.record_mlc3_service_access_event_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_mlc3_service_access_v2(UUID,UUID,UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.require_mlc3_service_access_v2(UUID,UUID,UUID)
    TO service_role;
REVOKE ALL ON FUNCTION public.ensure_mlc3_service_enrollment_v2(UUID,UUID,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ensure_mlc3_service_enrollment_v2(UUID,UUID,TEXT)
    TO service_role;
REVOKE ALL ON FUNCTION public.require_mlc3_service_principal_v1(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_mlc3_current_pair_speaker_identity_v1(
    UUID,UUID) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.assign_synthetic_exercise_pair_v1(
    UUID,UUID,TEXT,TEXT) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.submit_synthetic_exercise_pair_judgment_v1(
    UUID,UUID,TEXT,TEXT) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.assign_exercise_service_owner_pair_v1(
    UUID,UUID,TEXT) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.assign_exercise_service_owner_pair_v1(
    UUID,UUID,TEXT) TO service_role;
REVOKE ALL ON FUNCTION public.submit_exercise_service_owner_pair_judgment_v1(
    UUID,UUID,TEXT,TEXT) FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.submit_exercise_service_owner_pair_judgment_v1(
    UUID,UUID,TEXT,TEXT) TO service_role;
REVOKE ALL ON FUNCTION public.reserve_exercise_practice_service_upload_v1(
    UUID,UUID,UUID,TEXT,BIGINT,TEXT,TEXT,TEXT,INTEGER
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.reserve_exercise_practice_service_upload_v2(
    UUID,UUID,UUID,TEXT,BIGINT,TEXT,TEXT,TEXT,INTEGER
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_exercise_practice_service_upload_v2(
    UUID,UUID,UUID,TEXT,BIGINT,TEXT,TEXT,TEXT,INTEGER
) TO service_role;
REVOKE ALL ON FUNCTION public.prepare_mlc3_rollout_service_row_v2()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.prepare_mlc3_rollout_subject_row_v2()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.reject_mlc3_general_service_mutation_v1()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.record_mlc3_self_speaker_target_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.record_mlc3_feedback_self_speaker_target_v1(
    UUID,UUID,UUID,UUID,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_mlc3_feedback_self_speaker_target_v1(
    UUID,UUID,UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_mlc3_practice_self_speaker_target_v1(
    UUID,UUID,UUID,TEXT
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.confirm_mlc3_practice_speaker_and_pair_v1(
    UUID,UUID,UUID,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.confirm_mlc3_practice_speaker_and_pair_v1(
    UUID,UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.freeze_mlc3_same_speaker_eligibility_v1(
    UUID,UUID,UUID,TEXT
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.prepare_mlc3_pair_speaker_identity_v1()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_mlc3_offer_source_speaker_v1()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.register_mlc3_activation_risk_decision_v1(
    TEXT,TEXT,TEXT,TEXT,TEXT,UUID,TIMESTAMPTZ,TEXT,TEXT
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.register_mlc3_general_rollout_v2(
    UUID,UUID,JSONB,JSONB,UUID,TIMESTAMPTZ,TEXT
) FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.halt_mlc3_service_rollout_v1(TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.enforce_mlc3_service_capacity_v1()
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.get_mlc3_general_service_monitor_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc3_general_service_monitor_v1()
    TO service_role;
GRANT EXECUTE ON FUNCTION public.halt_mlc3_service_rollout_v1(TEXT,TEXT)
    TO service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
