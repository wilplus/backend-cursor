-- 0310 · ED-PLF-1.3 Phase-1 processing authorization and deletion boundary.
-- Additive and inactive by default: no policy is seeded or activated and no
-- Phase-2 learning capability is enabled.

BEGIN;

CREATE OR REPLACE FUNCTION public.reject_phase1_immutable_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Phase-1 evidence is append-only';
END;
$$;
REVOKE ALL ON FUNCTION public.reject_phase1_immutable_mutation()
    FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS public.processing_purpose_registry (
    id TEXT PRIMARY KEY,
    phase TEXT NOT NULL CHECK (phase IN ('phase1', 'phase2')),
    operational BOOLEAN NOT NULL DEFAULT false,
    authorizes_processing BOOLEAN NOT NULL DEFAULT false,
    capability_version TEXT,
    reviewed_at TIMESTAMPTZ,
    retention_control_version TEXT,
    deletion_control_version TEXT,
    rights_control_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT processing_purpose_operational_invariant CHECK (
        NOT authorizes_processing OR (
            operational AND capability_version IS NOT NULL
            AND reviewed_at IS NOT NULL
            AND retention_control_version IS NOT NULL
            AND deletion_control_version IS NOT NULL
            AND rights_control_version IS NOT NULL
        )
    )
);

INSERT INTO public.processing_purpose_registry (id, phase) VALUES
    ('recording_voice_processing', 'phase1'),
    ('transcription_feedback', 'phase1'),
    ('individual_learning_profile', 'phase1'),
    ('coach_review', 'phase1'),
    ('pooled_model_improvement', 'phase2'),
    ('personalized_exercise_recommendation', 'phase2')
ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.processing_legal_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_kind TEXT NOT NULL CHECK (artifact_kind IN (
        'product_legal_approval', 'power_score_classification',
        'article_50_assessment', 'retention_schedule', 'processor_inventory'
    )),
    version TEXT NOT NULL,
    approving_authority TEXT NOT NULL,
    approved_at TIMESTAMPTZ NOT NULL,
    object_key TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (artifact_kind, version)
);

CREATE TABLE IF NOT EXISTS public.processing_policy_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'approved', 'active', 'retired')
    ),
    product_legal_artifact_id UUID REFERENCES
        public.processing_legal_artifacts(id) ON DELETE RESTRICT,
    power_score_classification_artifact_id UUID REFERENCES
        public.processing_legal_artifacts(id) ON DELETE RESTRICT,
    article50_artifact_id UUID REFERENCES
        public.processing_legal_artifacts(id) ON DELETE RESTRICT,
    terms_version TEXT NOT NULL,
    terms_copy TEXT NOT NULL,
    terms_copy_sha256 TEXT NOT NULL CHECK (terms_copy_sha256 ~ '^[0-9a-f]{64}$'),
    privacy_version TEXT NOT NULL,
    privacy_copy TEXT NOT NULL,
    privacy_copy_sha256 TEXT NOT NULL CHECK (privacy_copy_sha256 ~ '^[0-9a-f]{64}$'),
    ai_notice_version TEXT NOT NULL,
    ai_notice_copy TEXT NOT NULL,
    ai_notice_copy_sha256 TEXT NOT NULL CHECK (ai_notice_copy_sha256 ~ '^[0-9a-f]{64}$'),
    agreement_copy TEXT NOT NULL,
    agreement_copy_sha256 TEXT NOT NULL CHECK (agreement_copy_sha256 ~ '^[0-9a-f]{64}$'),
    allowed_countries TEXT[] NOT NULL CHECK (cardinality(allowed_countries) > 0),
    minimum_age INTEGER NOT NULL DEFAULT 18 CHECK (minimum_age = 18),
    activated_at TIMESTAMPTZ,
    retired_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT NOT NULL,
    CONSTRAINT processing_policy_approved_check CHECK (
        status NOT IN ('approved', 'active') OR (
            product_legal_artifact_id IS NOT NULL
            AND power_score_classification_artifact_id IS NOT NULL
            AND article50_artifact_id IS NOT NULL
        )
    ),
    CONSTRAINT processing_policy_active_check CHECK (
        status <> 'active' OR activated_at IS NOT NULL
    ),
    CONSTRAINT processing_policy_retired_check CHECK (
        status <> 'retired' OR retired_at IS NOT NULL
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS processing_one_active_policy_idx
    ON public.processing_policy_versions ((status)) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS public.processing_policy_purposes (
    policy_id UUID NOT NULL REFERENCES
        public.processing_policy_versions(id) ON DELETE RESTRICT,
    purpose_id TEXT NOT NULL REFERENCES
        public.processing_purpose_registry(id) ON DELETE RESTRICT,
    lawful_basis_code TEXT NOT NULL,
    required_for_core_service BOOLEAN NOT NULL,
    PRIMARY KEY (policy_id, purpose_id)
);

CREATE TABLE IF NOT EXISTS public.processing_authorization_receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    policy_id UUID NOT NULL REFERENCES
        public.processing_policy_versions(id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL,
    explicit_action TEXT NOT NULL CHECK (explicit_action = 'agree_and_continue'),
    age_18_attested BOOLEAN NOT NULL CHECK (age_18_attested),
    country_of_residence TEXT NOT NULL CHECK (
        length(btrim(country_of_residence)) BETWEEN 2 AND 80
    ),
    locale TEXT NOT NULL CHECK (length(btrim(locale)) BETWEEN 2 AND 35),
    client_version TEXT NOT NULL CHECK (length(btrim(client_version)) BETWEEN 1 AND 120),
    accepted_at TIMESTAMPTZ NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    pooled_learning_eligible BOOLEAN NOT NULL DEFAULT false
        CHECK (NOT pooled_learning_eligible),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (acquisition_principal_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS public.processing_authorization_receipt_purposes (
    receipt_id UUID NOT NULL REFERENCES
        public.processing_authorization_receipts(id) ON DELETE RESTRICT,
    purpose_id TEXT NOT NULL REFERENCES
        public.processing_purpose_registry(id) ON DELETE RESTRICT,
    lawful_basis_code TEXT NOT NULL,
    PRIMARY KEY (receipt_id, purpose_id)
);

CREATE TABLE IF NOT EXISTS public.processing_service_blocks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    block_kind TEXT NOT NULL CHECK (block_kind IN (
        'service_termination', 'account_deletion', 'restriction',
        'retention_expiry', 'third_party_audio', 'lawful_deletion'
    )),
    effective_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_request_id UUID,
    reason_code TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.processing_authorization_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    receipt_id UUID NOT NULL REFERENCES
        public.processing_authorization_receipts(id) ON DELETE RESTRICT,
    policy_id UUID NOT NULL REFERENCES
        public.processing_policy_versions(id) ON DELETE RESTRICT,
    purpose_id TEXT NOT NULL REFERENCES
        public.processing_purpose_registry(id) ON DELETE RESTRICT,
    operation_kind TEXT NOT NULL,
    source_take_id UUID,
    source_recording_id UUID,
    authority_checked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    authority_evidence_sha256 TEXT NOT NULL CHECK (
        authority_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    pooled_learning_eligible BOOLEAN NOT NULL DEFAULT false
        CHECK (NOT pooled_learning_eligible),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.processing_job_carryovers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    old_policy_id UUID NOT NULL REFERENCES
        public.processing_policy_versions(id) ON DELETE RESTRICT,
    new_policy_id UUID NOT NULL REFERENCES
        public.processing_policy_versions(id) ON DELETE RESTRICT,
    processing_job_id UUID NOT NULL,
    exact_operation TEXT NOT NULL CHECK (
        exact_operation = 'recording_transcription_ranking_feedback'
    ),
    cutoff_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    cancelled_at TIMESTAMPTZ,
    cancellation_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (processing_job_id, new_policy_id),
    CHECK (expires_at > cutoff_at)
);

CREATE TABLE IF NOT EXISTS public.processing_recording_attempts (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES
        public.projects(id) ON DELETE RESTRICT,
    recording_id UUID NOT NULL,
    upload_idempotency_key TEXT NOT NULL,
    authorization_snapshot_id UUID NOT NULL REFERENCES
        public.processing_authorization_snapshots(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'accepted' CHECK (status IN (
        'accepted', 'processing', 'completed', 'failed', 'cancelled', 'purged'
    )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (acquisition_principal_id, project_id, upload_idempotency_key),
    UNIQUE (recording_id)
);

CREATE TABLE IF NOT EXISTS public.processing_audio_objects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    recording_attempt_id UUID NOT NULL REFERENCES
        public.processing_recording_attempts(id) ON DELETE RESTRICT,
    storage_provider TEXT NOT NULL CHECK (storage_provider IN ('r2', 'supabase')),
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    byte_size BIGINT NOT NULL CHECK (byte_size > 0),
    content_type TEXT NOT NULL,
    exact_bytes_sha256 TEXT NOT NULL CHECK (exact_bytes_sha256 ~ '^[0-9a-f]{64}$'),
    verified_at TIMESTAMPTZ NOT NULL,
    verification_method TEXT NOT NULL CHECK (verification_method IN (
        'read_after_write_sha256', 'trusted_object_checksum_sha256'
    )),
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (storage_provider, bucket, object_key),
    UNIQUE (recording_attempt_id)
);

CREATE TABLE IF NOT EXISTS public.processing_orphan_objects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    storage_provider TEXT NOT NULL,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    exact_bytes_sha256 TEXT NOT NULL CHECK (exact_bytes_sha256 ~ '^[0-9a-f]{64}$'),
    reason_code TEXT NOT NULL,
    not_before TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'processing', 'deleted', 'referenced', 'failed')
    ),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error_code TEXT,
    checked_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (storage_provider, bucket, object_key)
);

ALTER TABLE public.processing_orphan_objects
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE public.processing_orphan_objects
    ADD COLUMN IF NOT EXISTS attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE public.processing_orphan_objects
    ADD COLUMN IF NOT EXISTS last_error_code TEXT;
ALTER TABLE public.processing_orphan_objects
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS processing_orphans_cleanup_idx
    ON public.processing_orphan_objects (status, not_before, created_at);

CREATE TABLE IF NOT EXISTS public.phase1_processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    recording_attempt_id UUID NOT NULL REFERENCES
        public.processing_recording_attempts(id) ON DELETE RESTRICT,
    authorization_snapshot_id UUID NOT NULL REFERENCES
        public.processing_authorization_snapshots(id) ON DELETE RESTRICT,
    runtime_job_id UUID UNIQUE,
    job_kind TEXT NOT NULL CHECK (job_kind IN (
        'recording_transcription_ranking_feedback', 'ideal_text_retry'
    )),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending', 'processing', 'completed', 'failed', 'cancelled'
    )),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (recording_attempt_id, job_kind)
);

ALTER TABLE public.phase1_processing_jobs
    ADD COLUMN IF NOT EXISTS runtime_job_id UUID UNIQUE;

CREATE TABLE IF NOT EXISTS public.phase1_processing_job_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    processing_job_id UUID NOT NULL REFERENCES
        public.phase1_processing_jobs(id) ON DELETE RESTRICT,
    runtime_job_id UUID,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'processing', 'completed', 'failed', 'cancelled'
    )),
    attempts INTEGER NOT NULL CHECK (attempts >= 0),
    error_code TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (processing_job_id, runtime_job_id, status, attempts)
);

CREATE TABLE IF NOT EXISTS public.phase1_processing_outbox (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    processing_job_id UUID NOT NULL REFERENCES
        public.phase1_processing_jobs(id) ON DELETE RESTRICT,
    event_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.processing_provider_permits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    authorization_snapshot_id UUID NOT NULL REFERENCES
        public.processing_authorization_snapshots(id) ON DELETE RESTRICT,
    provider TEXT NOT NULL,
    operation_kind TEXT NOT NULL CHECK (operation_kind IN (
        'audio_download', 'transcription', 'feedback_generation',
        'ideal_text_generation', 'coach_delivery'
    )),
    pseudonymous_subject_ref TEXT NOT NULL,
    minimum_data_manifest JSONB NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'issued' CHECK (status IN (
        'issued', 'used', 'revoked', 'expired', 'cancelled'
    )),
    idempotency_key TEXT NOT NULL UNIQUE,
    CHECK (expires_at > issued_at)
);

CREATE TABLE IF NOT EXISTS public.processing_provider_operations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    permit_id UUID NOT NULL REFERENCES
        public.processing_provider_permits(id) ON DELETE RESTRICT,
    provider_operation_ref TEXT,
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'started', 'completed', 'failed', 'cancelled', 'deleted', 'delete_failed'
    )),
    error_code TEXT,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS public.data_purge_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN (
        'service_termination', 'account_deletion', 'retention_expiry',
        'third_party_audio_report', 'lawful_deletion'
    )),
    state TEXT NOT NULL DEFAULT 'requested' CHECK (state IN (
        'requested', 'in_progress', 'review_required', 'done'
    )),
    idempotency_key TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (acquisition_principal_id, idempotency_key)
);

-- Requests other than erasure remain a separate immutable workflow.  A
-- restriction request blocks new processing immediately; fulfilment and any
-- correction are completed by the reviewed rights procedure, never by a
-- browser role editing product rows directly.
CREATE TABLE IF NOT EXISTS public.data_rights_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    request_kind TEXT NOT NULL CHECK (request_kind IN (
        'access', 'export', 'correction', 'restriction', 'objection'
    )),
    state TEXT NOT NULL DEFAULT 'requested' CHECK (state IN (
        'requested', 'in_progress', 'review_required', 'done'
    )),
    idempotency_key TEXT NOT NULL,
    subject_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ,
    UNIQUE (acquisition_principal_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS public.data_purge_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purge_request_id UUID NOT NULL REFERENCES
        public.data_purge_requests(id) ON DELETE RESTRICT,
    target_kind TEXT NOT NULL CHECK (target_kind IN (
        'database_row', 'r2_object', 'supabase_object', 'transcript',
        'derived_feedback', 'processing_queue', 'provider_operation',
        'coach_packet', 'cache', 'dataset_lineage', 'model_lineage', 'unknown'
    )),
    target_ref TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending' CHECK (state IN (
        'pending', 'deleted', 'retained', 'failed', 'unknown', 'not_found'
    )),
    retention_rule_id UUID,
    evidence_sha256 TEXT CHECK (
        evidence_sha256 IS NULL OR evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    UNIQUE (purge_request_id, target_kind, target_ref)
);

CREATE TABLE IF NOT EXISTS public.data_retention_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    rule_code TEXT NOT NULL UNIQUE,
    evidence_category TEXT NOT NULL,
    retention_until_rule TEXT NOT NULL,
    legal_artifact_id UUID NOT NULL REFERENCES
        public.processing_legal_artifacts(id) ON DELETE RESTRICT,
    active BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'data_purge_targets_retention_rule_fkey'
    ) THEN
        ALTER TABLE public.data_purge_targets
        ADD CONSTRAINT data_purge_targets_retention_rule_fkey
        FOREIGN KEY (retention_rule_id) REFERENCES
            public.data_retention_rules(id) ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS public.data_purge_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purge_request_id UUID NOT NULL REFERENCES
        public.data_purge_requests(id) ON DELETE RESTRICT,
    target_id UUID REFERENCES public.data_purge_targets(id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL,
    actor_kind TEXT NOT NULL,
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS public.ai_transparency_exposures (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    ai_notice_version TEXT NOT NULL,
    surface TEXT NOT NULL,
    client_render_id TEXT NOT NULL,
    rendered_at TIMESTAMPTZ NOT NULL,
    client_version TEXT NOT NULL,
    authenticated_actor_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (acquisition_principal_id, ai_notice_version, surface, client_render_id)
);

CREATE TABLE IF NOT EXISTS public.retired_processing_artifact_reconciliation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_kind TEXT NOT NULL CHECK (artifact_kind IN (
        'sex_routed_confidence', 'challenge_threat_direction',
        'machine_breakthrough'
    )),
    artifact_ref TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('recomputed', 'excluded')),
    replacement_version TEXT,
    exclusion_reason TEXT,
    old_value_sha256 TEXT NOT NULL CHECK (old_value_sha256 ~ '^[0-9a-f]{64}$'),
    reconciled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    reconciled_by TEXT NOT NULL,
    UNIQUE (artifact_kind, artifact_ref),
    CONSTRAINT retired_artifact_outcome_check CHECK (
        (outcome = 'recomputed' AND replacement_version IS NOT NULL
            AND exclusion_reason IS NULL)
        OR (outcome = 'excluded' AND replacement_version IS NULL
            AND exclusion_reason IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.phase1_authorization_admin_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_kind TEXT NOT NULL,
    actor TEXT NOT NULL,
    target_ref TEXT NOT NULL,
    payload_sha256 TEXT NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.get_phase1_processing_authorization_v1(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    policy processing_policy_versions;
    receipt processing_authorization_receipts;
    blocked BOOLEAN;
BEGIN
    SELECT * INTO policy FROM processing_policy_versions
     WHERE status = 'active' AND activated_at <= now()
       AND (retired_at IS NULL OR retired_at > now())
     ORDER BY activated_at DESC LIMIT 1;
    IF policy.id IS NULL THEN
        RETURN jsonb_build_object(
            'authorized', false, 'code', 'PROCESSING_POLICY_INACTIVE',
            'policy_available', false, 'pooled_learning_eligible', false
        );
    END IF;
    SELECT EXISTS (
        SELECT 1 FROM processing_service_blocks b
         WHERE b.acquisition_principal_id = p_acquisition_principal_id
           AND b.effective_at <= now()
    ) INTO blocked;
    SELECT r.* INTO receipt FROM processing_authorization_receipts r
     WHERE r.acquisition_principal_id = p_acquisition_principal_id
       AND r.policy_id = policy.id
     ORDER BY r.accepted_at DESC LIMIT 1;
    RETURN jsonb_build_object(
        'authorized', receipt.id IS NOT NULL AND NOT blocked,
        'code', CASE
            WHEN blocked THEN 'PROCESSING_SERVICE_BLOCKED'
            WHEN receipt.id IS NULL THEN 'PROCESSING_AUTHORIZATION_REQUIRED'
            ELSE 'PROCESSING_AUTHORIZED' END,
        'policy_available', true, 'policy_id', policy.id,
        'policy_version', policy.version,
        'terms_version', policy.terms_version,
        'terms_copy', policy.terms_copy,
        'terms_copy_sha256', policy.terms_copy_sha256,
        'privacy_version', policy.privacy_version,
        'privacy_copy', policy.privacy_copy,
        'privacy_copy_sha256', policy.privacy_copy_sha256,
        'ai_notice_version', policy.ai_notice_version,
        'ai_notice_copy', policy.ai_notice_copy,
        'ai_notice_copy_sha256', policy.ai_notice_copy_sha256,
        'agreement_copy', policy.agreement_copy,
        'agreement_copy_sha256', policy.agreement_copy_sha256,
        'minimum_age', policy.minimum_age,
        'allowed_countries', policy.allowed_countries,
        'ai_notice_rendered', EXISTS (
            SELECT 1 FROM ai_transparency_exposures e
             WHERE e.acquisition_principal_id = p_acquisition_principal_id
               AND e.ai_notice_version = policy.ai_notice_version
        ),
        'receipt_id', receipt.id, 'pooled_learning_eligible', false
    );
END;
$$;
REVOKE ALL ON FUNCTION public.get_phase1_processing_authorization_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_phase1_processing_authorization_v1(UUID)
    TO service_role;

-- Product ownership may move from a signed guest principal to an existing
-- account principal. Acquisition evidence must not move with it. Resolve the
-- immutable acquisition principal through the audited claim event, preferring
-- the newest source that already owns Phase-1 authorization evidence.
CREATE OR REPLACE FUNCTION public.resolve_phase1_acquisition_principal_v1(
    p_product_owner_principal_id UUID,
    p_user_id UUID DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE resolved UUID;
BEGIN
    IF p_product_owner_principal_id IS NULL THEN
        RAISE EXCEPTION 'PROCESSING_PRINCIPAL_UNRESOLVED';
    END IF;
    SELECT event.source_owner_principal_id INTO resolved
      FROM public.owner_claim_events event
     WHERE event.target_owner_principal_id = p_product_owner_principal_id
       AND (p_user_id IS NULL OR event.claimed_user_id = p_user_id)
       AND EXISTS (
           SELECT 1 FROM public.processing_authorization_receipts receipt
            WHERE receipt.acquisition_principal_id =
                  event.source_owner_principal_id
       )
     ORDER BY event.claimed_at DESC, event.id DESC
     LIMIT 1;
    RETURN COALESCE(resolved, p_product_owner_principal_id);
END;
$$;
REVOKE ALL ON FUNCTION public.resolve_phase1_acquisition_principal_v1(UUID,UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_acquisition_principal_v1(UUID,UUID)
    TO service_role;

CREATE OR REPLACE FUNCTION public.accept_phase1_processing_authorization_v1(
    p_acquisition_principal_id UUID, p_policy_version TEXT,
    p_terms_copy_sha256 TEXT, p_privacy_copy_sha256 TEXT,
    p_ai_notice_copy_sha256 TEXT, p_agreement_copy_sha256 TEXT,
    p_explicit_action TEXT, p_age_18_attested BOOLEAN,
    p_country_of_residence TEXT, p_locale TEXT, p_client_version TEXT,
    p_accepted_at TIMESTAMPTZ, p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    policy processing_policy_versions;
    receipt processing_authorization_receipts;
    evidence_hash TEXT;
    existing_hash TEXT;
BEGIN
    SELECT * INTO policy FROM processing_policy_versions
     WHERE version = p_policy_version AND status = 'active'
       AND activated_at <= now()
       AND (retired_at IS NULL OR retired_at > now()) LIMIT 1;
    IF policy.id IS NULL OR policy.product_legal_artifact_id IS NULL THEN
        RAISE EXCEPTION 'PROCESSING_POLICY_UNAPPROVED';
    END IF;
    IF p_explicit_action <> 'agree_and_continue' OR NOT p_age_18_attested THEN
        RAISE EXCEPTION 'EXPLICIT_ACCEPTANCE_REQUIRED';
    END IF;
    IF NOT (lower(btrim(p_country_of_residence)) = ANY(policy.allowed_countries)) THEN
        RAISE EXCEPTION 'COUNTRY_NOT_ALLOWED';
    END IF;
    IF p_terms_copy_sha256 <> policy.terms_copy_sha256
       OR p_privacy_copy_sha256 <> policy.privacy_copy_sha256
       OR p_ai_notice_copy_sha256 <> policy.ai_notice_copy_sha256
       OR p_agreement_copy_sha256 <> policy.agreement_copy_sha256 THEN
        RAISE EXCEPTION 'PROCESSING_POLICY_STALE';
    END IF;
    IF EXISTS (
        SELECT 1 FROM processing_policy_purposes pp
        JOIN processing_purpose_registry pr ON pr.id = pp.purpose_id
          WHERE pp.policy_id = policy.id AND pp.required_for_core_service
            AND (NOT pr.operational OR NOT pr.authorizes_processing)
    ) THEN RAISE EXCEPTION 'PROCESSING_PURPOSE_NOT_OPERATIONAL'; END IF;
    IF EXISTS (
        SELECT 1 FROM processing_policy_purposes
         WHERE policy_id = policy.id AND purpose_id IN (
             'pooled_model_improvement', 'personalized_exercise_recommendation'
         )
    ) THEN RAISE EXCEPTION 'PHASE2_PURPOSE_FORBIDDEN'; END IF;

    evidence_hash := encode(extensions.digest(concat_ws(':',
        p_acquisition_principal_id::text, policy.id::text,
        p_terms_copy_sha256, p_privacy_copy_sha256, p_ai_notice_copy_sha256,
        p_agreement_copy_sha256, p_explicit_action,
        p_age_18_attested::text, lower(btrim(p_country_of_residence)),
        p_locale, p_client_version, p_accepted_at::text, p_idempotency_key
    ), 'sha256'), 'hex');
    SELECT evidence_sha256 INTO existing_hash
      FROM processing_authorization_receipts
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = p_idempotency_key;
    IF existing_hash IS NOT NULL AND existing_hash <> evidence_hash THEN
        RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
    END IF;
    INSERT INTO processing_authorization_receipts (
        acquisition_principal_id, policy_id, idempotency_key, explicit_action,
        age_18_attested, country_of_residence, locale, client_version,
        accepted_at, evidence_sha256, pooled_learning_eligible
    ) VALUES (
        p_acquisition_principal_id, policy.id, p_idempotency_key,
        p_explicit_action, p_age_18_attested,
        lower(btrim(p_country_of_residence)), p_locale, p_client_version,
        p_accepted_at, evidence_hash, false
    ) ON CONFLICT (acquisition_principal_id, idempotency_key) DO NOTHING;
    SELECT * INTO receipt FROM processing_authorization_receipts
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = p_idempotency_key;
    INSERT INTO processing_authorization_receipt_purposes (
        receipt_id, purpose_id, lawful_basis_code
    ) SELECT receipt.id, pp.purpose_id, pp.lawful_basis_code
        FROM processing_policy_purposes pp
       WHERE pp.policy_id = policy.id AND pp.required_for_core_service
    ON CONFLICT DO NOTHING;
    RETURN jsonb_build_object(
        'authorized', true, 'receipt_id', receipt.id,
        'policy_version', policy.version, 'pooled_learning_eligible', false
    );
END;
$$;
REVOKE ALL ON FUNCTION public.accept_phase1_processing_authorization_v1(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_phase1_processing_authorization_v1(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT
) TO service_role;

CREATE OR REPLACE FUNCTION public.finalize_phase1_recording_intake_v1(
    p_attempt_id UUID, p_acquisition_principal_id UUID, p_project_id UUID,
    p_recording_id UUID, p_upload_idempotency_key TEXT,
    p_storage_provider TEXT, p_bucket TEXT, p_object_key TEXT,
    p_byte_size BIGINT, p_content_type TEXT, p_exact_bytes_sha256 TEXT,
    p_verification_method TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    auth JSONB;
    auth_receipt_id UUID;
    auth_policy_id UUID;
    snapshot_id UUID;
    attempt processing_recording_attempts;
    audio processing_audio_objects;
    job_id UUID;
    outbox_id UUID;
    authority_hash TEXT;
    orphan processing_orphan_objects;
BEGIN
    auth := get_phase1_processing_authorization_v1(p_acquisition_principal_id);
    IF NOT COALESCE((auth->>'authorized')::boolean, false) THEN
        RAISE EXCEPTION '%', COALESCE(
            auth->>'code', 'PROCESSING_AUTHORIZATION_REQUIRED'
        );
    END IF;
    auth_receipt_id := (auth->>'receipt_id')::uuid;
    SELECT policy_id INTO auth_policy_id
      FROM processing_authorization_receipts WHERE id = auth_receipt_id;

    -- Serialize one acquisition/project/idempotency coordinate.  An exact
    -- replay returns the original immutable boundary; a changed recording or
    -- object cannot hide behind ON CONFLICT DO NOTHING.
    PERFORM pg_advisory_xact_lock(hashtext(concat_ws(':',
        'phase1-intake', p_acquisition_principal_id::text,
        p_project_id::text, p_upload_idempotency_key)));
    SELECT * INTO attempt FROM processing_recording_attempts
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND project_id = p_project_id
       AND upload_idempotency_key = p_upload_idempotency_key
     FOR UPDATE;
    IF attempt.id IS NOT NULL THEN
        SELECT * INTO audio FROM processing_audio_objects
         WHERE recording_attempt_id = attempt.id;
        IF attempt.recording_id <> p_recording_id
           OR audio.id IS NULL
           OR audio.storage_provider <> p_storage_provider
           OR audio.bucket <> p_bucket
           OR audio.object_key <> p_object_key
           OR audio.byte_size <> p_byte_size
           OR audio.content_type <> p_content_type
           OR audio.exact_bytes_sha256 <> p_exact_bytes_sha256
        THEN
            RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
        END IF;
        SELECT id INTO job_id FROM phase1_processing_jobs
         WHERE recording_attempt_id = attempt.id
           AND job_kind = 'recording_transcription_ranking_feedback';
        SELECT id INTO outbox_id FROM phase1_processing_outbox
         WHERE idempotency_key = 'phase1-recording:' || attempt.id::text;
        IF job_id IS NULL OR outbox_id IS NULL THEN
            RAISE EXCEPTION 'PROCESSING_BOUNDARY_INCOMPLETE';
        END IF;
        RETURN jsonb_build_object(
            'attempt_id', attempt.id, 'recording_id', attempt.recording_id,
            'authorization_snapshot_id', attempt.authorization_snapshot_id,
            'processing_job_id', job_id, 'outbox_event_id', outbox_id,
            'pooled_learning_eligible', false, 'idempotent_replay', true
        );
    END IF;

    -- Serialize canonical intake against delayed orphan cleanup for the exact
    -- provider/bucket/key. Cleanup never wins while intake owns the object,
    -- and intake never registers bytes already deleted by cleanup.
    SELECT * INTO orphan FROM processing_orphan_objects
     WHERE storage_provider = p_storage_provider
       AND bucket = p_bucket AND object_key = p_object_key
     FOR UPDATE;
    IF orphan.id IS NOT NULL THEN
        IF orphan.exact_bytes_sha256 <> p_exact_bytes_sha256 THEN
            RAISE EXCEPTION 'ORPHAN_OBJECT_HASH_CONFLICT';
        ELSIF orphan.status = 'processing' THEN
            RAISE EXCEPTION 'ORPHAN_CLEANUP_IN_PROGRESS';
        ELSIF orphan.status = 'deleted' THEN
            RAISE EXCEPTION 'ORPHAN_OBJECT_ALREADY_DELETED';
        ELSE
            UPDATE processing_orphan_objects SET
                status = 'referenced', checked_at = now(), updated_at = now(),
                last_error_code = NULL
             WHERE id = orphan.id;
        END IF;
    END IF;

    authority_hash := encode(extensions.digest(concat_ws(':', auth_receipt_id::text,
        p_attempt_id::text, p_recording_id::text, p_exact_bytes_sha256,
        'recording_voice_processing'), 'sha256'), 'hex');

    INSERT INTO processing_authorization_snapshots (
        acquisition_principal_id, receipt_id, policy_id, purpose_id,
        operation_kind, source_take_id, source_recording_id,
        authority_evidence_sha256, pooled_learning_eligible
    ) VALUES (
        p_acquisition_principal_id, auth_receipt_id, auth_policy_id,
        'recording_voice_processing',
        'recording_transcription_ranking_feedback', p_attempt_id,
        p_recording_id, authority_hash, false
    ) RETURNING id INTO snapshot_id;

    INSERT INTO processing_recording_attempts (
        id, acquisition_principal_id, project_id, recording_id,
        upload_idempotency_key, authorization_snapshot_id
    ) VALUES (
        p_attempt_id, p_acquisition_principal_id, p_project_id, p_recording_id,
        p_upload_idempotency_key, snapshot_id
    ) RETURNING * INTO attempt;

    INSERT INTO processing_audio_objects (
        acquisition_principal_id, recording_attempt_id, storage_provider,
        bucket, object_key, byte_size, content_type, exact_bytes_sha256,
        verified_at, verification_method
    ) VALUES (
        p_acquisition_principal_id, attempt.id, p_storage_provider,
        p_bucket, p_object_key, p_byte_size, p_content_type,
        p_exact_bytes_sha256, now(), p_verification_method
    );

    INSERT INTO phase1_processing_jobs (
        acquisition_principal_id, recording_attempt_id,
        authorization_snapshot_id, job_kind
    ) VALUES (
        p_acquisition_principal_id, attempt.id,
        attempt.authorization_snapshot_id,
        'recording_transcription_ranking_feedback'
    ) RETURNING id INTO job_id;
    INSERT INTO phase1_processing_outbox (
        processing_job_id, event_type, idempotency_key, payload
    ) VALUES (
        job_id, 'phase1_recording_ready',
        'phase1-recording:' || attempt.id::text,
        jsonb_build_object(
            'attempt_id', attempt.id, 'recording_id', attempt.recording_id,
            'acquisition_principal_id', p_acquisition_principal_id,
            'authorization_snapshot_id', attempt.authorization_snapshot_id,
            'pooled_learning_eligible', false
        )
    ) RETURNING id INTO outbox_id;
    RETURN jsonb_build_object(
        'attempt_id', attempt.id, 'recording_id', attempt.recording_id,
        'authorization_snapshot_id', attempt.authorization_snapshot_id,
        'processing_job_id', job_id, 'outbox_event_id', outbox_id,
        'pooled_learning_eligible', false
    );
END;
$$;
REVOKE ALL ON FUNCTION public.finalize_phase1_recording_intake_v1(
    UUID,UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_phase1_recording_intake_v1(
    UUID,UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TEXT,TEXT
) TO service_role;

CREATE OR REPLACE FUNCTION public.sync_phase1_processing_job_v1(
    p_attempt_id UUID, p_runtime_job_id UUID, p_status TEXT,
    p_attempts INTEGER, p_error_code TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    canonical_job phase1_processing_jobs;
    runtime_job processing_jobs;
    current_authority JSONB;
BEGIN
    IF p_status NOT IN (
        'pending', 'processing', 'completed', 'failed', 'cancelled'
    ) OR p_attempts < 0 THEN
        RAISE EXCEPTION 'PROCESSING_JOB_TRANSITION_INVALID';
    END IF;
    SELECT * INTO canonical_job FROM phase1_processing_jobs
     WHERE recording_attempt_id = p_attempt_id
       AND job_kind = 'recording_transcription_ranking_feedback'
     FOR UPDATE;
    IF canonical_job.id IS NULL THEN
        RAISE EXCEPTION 'PROCESSING_JOB_NOT_FOUND';
    END IF;
    IF p_runtime_job_id IS NOT NULL THEN
        SELECT * INTO runtime_job FROM processing_jobs
         WHERE id = p_runtime_job_id
           AND session_id = p_attempt_id
           AND kind = 'session_recording';
        IF runtime_job.id IS NULL THEN
            RAISE EXCEPTION 'PROCESSING_RUNTIME_JOB_MISMATCH';
        END IF;
        IF canonical_job.runtime_job_id IS NOT NULL
           AND canonical_job.runtime_job_id <> p_runtime_job_id
        THEN
            RAISE EXCEPTION 'PROCESSING_RUNTIME_JOB_CONFLICT';
        END IF;
    END IF;
    IF canonical_job.status IN ('completed', 'failed', 'cancelled')
       AND canonical_job.status <> p_status THEN
        IF canonical_job.status = 'failed' AND p_status = 'pending'
           AND p_runtime_job_id = canonical_job.runtime_job_id THEN
            current_authority := get_phase1_processing_authorization_v1(
                canonical_job.acquisition_principal_id
            );
            IF NOT COALESCE(
                (current_authority->>'authorized')::boolean, false
            ) THEN
                RAISE EXCEPTION 'PROCESSING_AUTHORIZATION_REQUIRED';
            END IF;
        ELSE
            RAISE EXCEPTION 'PROCESSING_JOB_TERMINAL';
        END IF;
    END IF;
    UPDATE phase1_processing_jobs SET
        runtime_job_id = COALESCE(runtime_job_id, p_runtime_job_id),
        status = p_status,
        attempts = GREATEST(attempts, p_attempts),
        last_error_code = CASE
            WHEN p_status = 'completed' THEN NULL ELSE p_error_code END,
        updated_at = now()
     WHERE id = canonical_job.id;
    INSERT INTO phase1_processing_job_events (
        processing_job_id, runtime_job_id, status, attempts, error_code
    ) VALUES (
        canonical_job.id, p_runtime_job_id, p_status, p_attempts, p_error_code
    ) ON CONFLICT DO NOTHING;
    IF p_runtime_job_id IS NOT NULL THEN
        UPDATE phase1_processing_outbox SET
            processed_at = COALESCE(processed_at, now()),
            attempts = GREATEST(attempts, 1),
            last_error_code = NULL
         WHERE processing_job_id = canonical_job.id
           AND event_type = 'phase1_recording_ready';
    END IF;
    RETURN jsonb_build_object(
        'processing_job_id', canonical_job.id,
        'runtime_job_id', COALESCE(
            canonical_job.runtime_job_id, p_runtime_job_id
        ),
        'status', p_status, 'attempts', p_attempts
    );
END;
$$;
REVOKE ALL ON FUNCTION public.sync_phase1_processing_job_v1(
    UUID,UUID,TEXT,INTEGER,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.sync_phase1_processing_job_v1(
    UUID,UUID,TEXT,INTEGER,TEXT
) TO service_role;

CREATE OR REPLACE FUNCTION public.queue_phase1_orphan_audio_v1(
    p_acquisition_principal_id UUID, p_storage_provider TEXT, p_bucket TEXT,
    p_object_key TEXT, p_exact_bytes_sha256 TEXT, p_reason_code TEXT
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE orphan_id UUID;
BEGIN
    INSERT INTO processing_orphan_objects (
        acquisition_principal_id, storage_provider, bucket, object_key,
        exact_bytes_sha256, reason_code, not_before
    ) VALUES (
        p_acquisition_principal_id, p_storage_provider, p_bucket, p_object_key,
        p_exact_bytes_sha256, p_reason_code, now() + interval '24 hours'
    ) ON CONFLICT (storage_provider, bucket, object_key) DO NOTHING;
    SELECT id INTO orphan_id FROM processing_orphan_objects
     WHERE storage_provider = p_storage_provider AND bucket = p_bucket
       AND object_key = p_object_key;
    RETURN orphan_id;
END;
$$;
REVOKE ALL ON FUNCTION public.queue_phase1_orphan_audio_v1(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.queue_phase1_orphan_audio_v1(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT
) TO service_role;

CREATE OR REPLACE FUNCTION public.claim_phase1_orphan_audio_v1(
    p_limit INTEGER DEFAULT 25
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE claimed JSONB;
BEGIN
    IF p_limit < 1 OR p_limit > 100 THEN
        RAISE EXCEPTION 'INVALID_ORPHAN_CLAIM_LIMIT';
    END IF;

    -- A recording finalizer may have won the race after the orphan was
    -- queued. Such an object is canonical evidence, never cleanup material.
    UPDATE processing_orphan_objects orphan SET
        status = 'referenced', checked_at = now(), updated_at = now(),
        last_error_code = NULL
     WHERE orphan.status IN ('pending', 'failed')
       AND EXISTS (
           SELECT 1 FROM processing_audio_objects audio
            WHERE audio.storage_provider = orphan.storage_provider
              AND audio.bucket = orphan.bucket
              AND audio.object_key = orphan.object_key
       );

    WITH eligible AS (
        SELECT orphan.id
          FROM processing_orphan_objects orphan
         WHERE orphan.status IN ('pending', 'failed')
           AND orphan.not_before <= now()
           AND orphan.attempts < 3
           AND NOT EXISTS (
               SELECT 1 FROM processing_audio_objects audio
                WHERE audio.storage_provider = orphan.storage_provider
                  AND audio.bucket = orphan.bucket
                  AND audio.object_key = orphan.object_key
           )
         ORDER BY orphan.created_at, orphan.id
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    ), rows AS (
        UPDATE processing_orphan_objects orphan SET
            status = 'processing', attempts = orphan.attempts + 1,
            checked_at = now(), updated_at = now(), last_error_code = NULL
          FROM eligible
         WHERE orphan.id = eligible.id
        RETURNING orphan.id, orphan.storage_provider, orphan.bucket,
                  orphan.object_key, orphan.exact_bytes_sha256,
                  orphan.attempts
    )
    SELECT COALESCE(jsonb_agg(to_jsonb(rows)), '[]'::jsonb)
      INTO claimed FROM rows;
    RETURN claimed;
END;
$$;
REVOKE ALL ON FUNCTION public.claim_phase1_orphan_audio_v1(INTEGER)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_phase1_orphan_audio_v1(INTEGER)
    TO service_role;

CREATE OR REPLACE FUNCTION public.resolve_phase1_orphan_audio_v1(
    p_orphan_id UUID, p_outcome TEXT, p_error_code TEXT DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE orphan processing_orphan_objects;
BEGIN
    IF p_outcome NOT IN ('deleted', 'failed') THEN
        RAISE EXCEPTION 'INVALID_ORPHAN_OUTCOME';
    END IF;
    SELECT * INTO orphan FROM processing_orphan_objects
     WHERE id = p_orphan_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'ORPHAN_NOT_FOUND'; END IF;
    IF orphan.status IN ('deleted', 'referenced') THEN
        RETURN to_jsonb(orphan);
    END IF;
    IF orphan.status <> 'processing' THEN
        RAISE EXCEPTION 'ORPHAN_NOT_CLAIMED';
    END IF;

    -- Recheck after the network deletion call. If canonical intake appeared
    -- in the meantime, never record this as a successful orphan deletion.
    IF EXISTS (
        SELECT 1 FROM processing_audio_objects audio
         WHERE audio.storage_provider = orphan.storage_provider
           AND audio.bucket = orphan.bucket
           AND audio.object_key = orphan.object_key
    ) THEN
        UPDATE processing_orphan_objects SET
            status = 'referenced', checked_at = now(), updated_at = now(),
            last_error_code = NULL
         WHERE id = p_orphan_id RETURNING * INTO orphan;
        RETURN to_jsonb(orphan);
    END IF;

    UPDATE processing_orphan_objects SET
        status = p_outcome,
        deleted_at = CASE WHEN p_outcome = 'deleted' THEN now() ELSE NULL END,
        not_before = CASE WHEN p_outcome = 'failed'
            THEN now() + make_interval(mins => LEAST(60, attempts * 10))
            ELSE not_before END,
        checked_at = now(), updated_at = now(),
        last_error_code = CASE WHEN p_outcome = 'failed'
            THEN COALESCE(NULLIF(left(p_error_code, 160), ''), 'DELETE_FAILED')
            ELSE NULL END
     WHERE id = p_orphan_id RETURNING * INTO orphan;
    RETURN to_jsonb(orphan);
END;
$$;
REVOKE ALL ON FUNCTION public.resolve_phase1_orphan_audio_v1(UUID,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_orphan_audio_v1(UUID,TEXT,TEXT)
    TO service_role;

CREATE OR REPLACE FUNCTION public.issue_phase1_provider_permit_v1(
    p_acquisition_principal_id UUID, p_source_take_id UUID,
    p_source_recording_id UUID, p_provider TEXT, p_operation_kind TEXT,
    p_pseudonymous_subject_ref TEXT, p_minimum_data_manifest JSONB,
    p_idempotency_key TEXT, p_ttl_seconds INTEGER DEFAULT 900
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    auth JSONB;
    receipt processing_authorization_receipts;
    purpose TEXT;
    snapshot_id UUID;
    permit processing_provider_permits;
    authority_hash TEXT;
    carryover processing_job_carryovers;
    source_job phase1_processing_jobs;
BEGIN
    auth := get_phase1_processing_authorization_v1(p_acquisition_principal_id);
    IF NOT COALESCE((auth->>'authorized')::boolean, false) THEN
        IF p_operation_kind NOT IN (
            'audio_download', 'transcription', 'feedback_generation',
            'ideal_text_generation'
        ) THEN
            RAISE EXCEPTION '%', COALESCE(
                auth->>'code', 'PROCESSING_AUTHORIZATION_REQUIRED'
            );
        END IF;
        SELECT j.* INTO source_job
          FROM phase1_processing_jobs j
          JOIN processing_recording_attempts a
            ON a.id = j.recording_attempt_id
         WHERE j.acquisition_principal_id = p_acquisition_principal_id
           AND a.recording_id = p_source_recording_id
           AND j.job_kind = 'recording_transcription_ranking_feedback'
           AND j.status IN ('pending', 'processing')
         ORDER BY j.created_at DESC LIMIT 1;
        IF source_job.id IS NOT NULL THEN
            SELECT c.* INTO carryover
              FROM processing_job_carryovers c
             WHERE c.processing_job_id = source_job.id
               AND c.acquisition_principal_id = p_acquisition_principal_id
               AND c.exact_operation =
                   'recording_transcription_ranking_feedback'
               AND c.cancelled_at IS NULL
               AND c.cutoff_at <= now() AND c.expires_at > now()
             ORDER BY c.created_at DESC LIMIT 1;
        END IF;
        IF carryover.id IS NULL THEN
            RAISE EXCEPTION '%', COALESCE(
                auth->>'code', 'PROCESSING_AUTHORIZATION_REQUIRED'
            );
        END IF;
    END IF;
    IF p_ttl_seconds < 30 OR p_ttl_seconds > 3600 THEN
        RAISE EXCEPTION 'INVALID_PERMIT_TTL';
    END IF;
    purpose := CASE p_operation_kind
        WHEN 'audio_download' THEN 'recording_voice_processing'
        WHEN 'transcription' THEN 'transcription_feedback'
        WHEN 'feedback_generation' THEN 'transcription_feedback'
        WHEN 'ideal_text_generation' THEN 'transcription_feedback'
        WHEN 'coach_delivery' THEN 'coach_review'
        ELSE NULL END;
    IF purpose IS NULL THEN RAISE EXCEPTION 'INVALID_PROVIDER_OPERATION'; END IF;
    IF COALESCE((auth->>'authorized')::boolean, false) THEN
        SELECT * INTO receipt FROM processing_authorization_receipts
         WHERE id = (auth->>'receipt_id')::uuid;
    ELSE
        SELECT r.* INTO receipt
          FROM processing_authorization_snapshots s
          JOIN processing_authorization_receipts r ON r.id = s.receipt_id
         WHERE s.id = source_job.authorization_snapshot_id;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM processing_authorization_receipt_purposes
         WHERE receipt_id = receipt.id AND purpose_id = purpose
    ) THEN RAISE EXCEPTION 'PROCESSING_PURPOSE_NOT_AUTHORIZED'; END IF;

    authority_hash := encode(extensions.digest(concat_ws(':', receipt.id::text,
        p_source_take_id::text, p_source_recording_id::text,
        p_provider, p_operation_kind, p_idempotency_key), 'sha256'), 'hex');
    INSERT INTO processing_authorization_snapshots (
        acquisition_principal_id, receipt_id, policy_id, purpose_id,
        operation_kind, source_take_id, source_recording_id,
        authority_evidence_sha256, pooled_learning_eligible
    ) VALUES (
        p_acquisition_principal_id, receipt.id, receipt.policy_id, purpose,
        p_operation_kind, p_source_take_id, p_source_recording_id,
        authority_hash, false
    ) RETURNING id INTO snapshot_id;
    INSERT INTO processing_provider_permits (
        acquisition_principal_id, authorization_snapshot_id, provider,
        operation_kind, pseudonymous_subject_ref, minimum_data_manifest,
        expires_at, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, snapshot_id, p_provider,
        p_operation_kind, p_pseudonymous_subject_ref,
        p_minimum_data_manifest, now() + make_interval(secs => p_ttl_seconds),
        p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO permit FROM processing_provider_permits
     WHERE idempotency_key = p_idempotency_key;
    IF permit.acquisition_principal_id <> p_acquisition_principal_id
       OR permit.operation_kind <> p_operation_kind THEN
        RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
    END IF;
    RETURN jsonb_build_object(
        'permit_id', permit.id, 'provider', permit.provider,
        'operation_kind', permit.operation_kind,
        'expires_at', permit.expires_at,
        'authorization_snapshot_id', permit.authorization_snapshot_id
    );
END;
$$;
REVOKE ALL ON FUNCTION public.issue_phase1_provider_permit_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT,JSONB,TEXT,INTEGER
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.issue_phase1_provider_permit_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT,JSONB,TEXT,INTEGER
) TO service_role;

CREATE OR REPLACE FUNCTION public.record_phase1_provider_operation_v1(
    p_permit_id UUID, p_event_kind TEXT, p_provider_operation_ref TEXT,
    p_error_code TEXT, p_metadata JSONB
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE event_id UUID;
BEGIN
    IF p_event_kind NOT IN (
        'started', 'completed', 'failed', 'cancelled', 'deleted', 'delete_failed'
    ) THEN RAISE EXCEPTION 'INVALID_PROVIDER_EVENT'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM processing_provider_permits
         WHERE id = p_permit_id AND revoked_at IS NULL AND expires_at > now()
    ) THEN RAISE EXCEPTION 'PROVIDER_PERMIT_INVALID'; END IF;
    INSERT INTO processing_provider_operations (
        permit_id, provider_operation_ref, event_kind, error_code, metadata
    ) VALUES (
        p_permit_id, p_provider_operation_ref, p_event_kind,
        p_error_code, COALESCE(p_metadata, '{}'::jsonb)
    ) RETURNING id INTO event_id;
    IF p_event_kind = 'completed' THEN
        UPDATE processing_provider_permits SET status = 'used'
         WHERE id = p_permit_id AND status = 'issued';
    ELSIF p_event_kind = 'cancelled' THEN
        UPDATE processing_provider_permits SET status = 'cancelled',
            revoked_at = now() WHERE id = p_permit_id;
    END IF;
    RETURN event_id;
END;
$$;
REVOKE ALL ON FUNCTION public.record_phase1_provider_operation_v1(
    UUID,TEXT,TEXT,TEXT,JSONB
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_phase1_provider_operation_v1(
    UUID,TEXT,TEXT,TEXT,JSONB
) TO service_role;

CREATE OR REPLACE FUNCTION public.request_phase1_purge_v1(
    p_acquisition_principal_id UUID, p_trigger_kind TEXT,
    p_idempotency_key TEXT, p_reason_code TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE req data_purge_requests;
BEGIN
    IF p_trigger_kind NOT IN (
        'service_termination', 'account_deletion', 'retention_expiry',
        'third_party_audio_report', 'lawful_deletion'
    ) THEN RAISE EXCEPTION 'INVALID_PURGE_TRIGGER'; END IF;
    INSERT INTO data_purge_requests (
        acquisition_principal_id, trigger_kind, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_trigger_kind, p_idempotency_key
    ) ON CONFLICT (acquisition_principal_id, idempotency_key) DO NOTHING;
    SELECT * INTO req FROM data_purge_requests
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = p_idempotency_key;

    IF p_trigger_kind IN ('service_termination', 'account_deletion',
                          'retention_expiry', 'lawful_deletion')
       AND NOT EXISTS (
           SELECT 1 FROM processing_service_blocks
            WHERE source_request_id = req.id
       ) THEN
        INSERT INTO processing_service_blocks (
            acquisition_principal_id, block_kind, source_request_id, reason_code
        ) VALUES (
            p_acquisition_principal_id,
            CASE WHEN p_trigger_kind = 'lawful_deletion'
                 THEN 'lawful_deletion' ELSE p_trigger_kind END,
            req.id, p_reason_code
        );
        UPDATE phase1_processing_jobs SET status = 'cancelled',
            updated_at = now(), last_error_code = 'PROCESSING_AUTHORITY_ENDED'
         WHERE acquisition_principal_id = p_acquisition_principal_id
           AND status IN ('pending', 'processing');
        UPDATE processing_provider_permits SET status = 'cancelled',
            revoked_at = now()
         WHERE acquisition_principal_id = p_acquisition_principal_id
           AND status = 'issued';
        UPDATE processing_job_carryovers SET cancelled_at = now(),
            cancellation_reason = 'PROCESSING_AUTHORITY_ENDED'
         WHERE acquisition_principal_id = p_acquisition_principal_id
           AND cancelled_at IS NULL;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM data_purge_events
         WHERE purge_request_id = req.id AND event_kind = 'requested'
    ) THEN
        INSERT INTO data_purge_events (
            purge_request_id, event_kind, actor_kind,
            evidence_sha256, metadata
        ) VALUES (
            req.id, 'requested', 'system', encode(extensions.digest(concat_ws(':',
                req.id::text, p_trigger_kind, p_reason_code
            ), 'sha256'), 'hex'),
            jsonb_build_object('trigger_kind', p_trigger_kind,
                               'reason_code', p_reason_code)
        );
    END IF;
    RETURN jsonb_build_object('purge_request_id', req.id, 'state', req.state);
END;
$$;
REVOKE ALL ON FUNCTION public.request_phase1_purge_v1(UUID,TEXT,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.request_phase1_purge_v1(UUID,TEXT,TEXT,TEXT)
    TO service_role;

CREATE OR REPLACE FUNCTION public.request_phase1_data_right_v1(
    p_acquisition_principal_id UUID, p_request_kind TEXT,
    p_idempotency_key TEXT, p_subject_payload JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE req data_rights_requests;
BEGIN
    IF p_request_kind NOT IN (
        'access', 'export', 'correction', 'restriction', 'objection'
    ) THEN RAISE EXCEPTION 'INVALID_DATA_RIGHT_KIND'; END IF;
    IF length(COALESCE(p_idempotency_key, '')) < 8 THEN
        RAISE EXCEPTION 'IDEMPOTENCY_KEY_REQUIRED';
    END IF;
    INSERT INTO data_rights_requests (
        acquisition_principal_id, request_kind, idempotency_key,
        subject_payload
    ) VALUES (
        p_acquisition_principal_id, p_request_kind, p_idempotency_key,
        COALESCE(p_subject_payload, '{}'::jsonb)
    ) ON CONFLICT (acquisition_principal_id, idempotency_key) DO NOTHING;
    SELECT * INTO req FROM data_rights_requests
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND idempotency_key = p_idempotency_key;
    IF req.request_kind <> p_request_kind
       OR req.subject_payload <> COALESCE(p_subject_payload, '{}'::jsonb)
    THEN RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT'; END IF;

    IF p_request_kind = 'restriction' AND NOT EXISTS (
        SELECT 1 FROM processing_service_blocks
         WHERE source_request_id = req.id
    ) THEN
        INSERT INTO processing_service_blocks (
            acquisition_principal_id, block_kind, source_request_id,
            reason_code
        ) VALUES (
            p_acquisition_principal_id, 'restriction', req.id,
            'DATA_RIGHT_RESTRICTION'
        );
        UPDATE phase1_processing_jobs SET status = 'cancelled',
            updated_at = now(), last_error_code = 'PROCESSING_RESTRICTED'
         WHERE acquisition_principal_id = p_acquisition_principal_id
           AND status IN ('pending', 'processing');
        UPDATE processing_provider_permits SET status = 'cancelled',
            revoked_at = now()
         WHERE acquisition_principal_id = p_acquisition_principal_id
           AND status = 'issued';
        UPDATE processing_job_carryovers SET cancelled_at = now(),
            cancellation_reason = 'PROCESSING_RESTRICTED'
         WHERE acquisition_principal_id = p_acquisition_principal_id
           AND cancelled_at IS NULL;
    END IF;
    RETURN jsonb_build_object(
        'request_id', req.id, 'request_kind', req.request_kind,
        'state', req.state, 'requested_at', req.requested_at
    );
END;
$$;
REVOKE ALL ON FUNCTION public.request_phase1_data_right_v1(
    UUID,TEXT,TEXT,JSONB
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.request_phase1_data_right_v1(
    UUID,TEXT,TEXT,JSONB
) TO service_role;

CREATE OR REPLACE FUNCTION public.freeze_phase1_purge_inventory_v1(
    p_purge_request_id UUID, p_resolver_version TEXT, p_targets JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE item JSONB; req data_purge_requests; kind TEXT; ref TEXT; unknowns INT;
BEGIN
    SELECT * INTO req FROM data_purge_requests
     WHERE id = p_purge_request_id FOR UPDATE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    IF req.state NOT IN ('requested', 'in_progress', 'review_required') THEN
        RAISE EXCEPTION 'PURGE_INVENTORY_FROZEN';
    END IF;
    IF jsonb_typeof(p_targets) <> 'array' THEN
        RAISE EXCEPTION 'PURGE_TARGETS_REQUIRED';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(p_targets) LOOP
        kind := COALESCE(item->>'target_kind', 'unknown');
        ref := COALESCE(NULLIF(item->>'target_ref', ''), 'unresolved');
        IF kind NOT IN (
            'database_row', 'r2_object', 'supabase_object', 'transcript',
            'derived_feedback', 'processing_queue', 'provider_operation',
            'coach_packet', 'cache', 'dataset_lineage', 'model_lineage'
        ) THEN kind := 'unknown'; END IF;
        INSERT INTO data_purge_targets (
            purge_request_id, target_kind, target_ref, resolver_version, state
        ) VALUES (
            req.id, kind, ref, p_resolver_version,
            CASE WHEN kind = 'unknown' THEN 'unknown' ELSE 'pending' END
        ) ON CONFLICT (purge_request_id, target_kind, target_ref) DO NOTHING;
    END LOOP;
    SELECT count(*) INTO unknowns FROM data_purge_targets
     WHERE purge_request_id = req.id AND state = 'unknown';
    UPDATE data_purge_requests SET state = CASE
        WHEN unknowns > 0 THEN 'review_required' ELSE 'in_progress' END
     WHERE id = req.id;
    RETURN jsonb_build_object('purge_request_id', req.id,
        'state', CASE WHEN unknowns > 0 THEN 'review_required'
                      ELSE 'in_progress' END,
        'unknown_target_count', unknowns);
END;
$$;
REVOKE ALL ON FUNCTION public.freeze_phase1_purge_inventory_v1(UUID,TEXT,JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_phase1_purge_inventory_v1(UUID,TEXT,JSONB)
    TO service_role;

CREATE OR REPLACE FUNCTION public.resolve_phase1_purge_target_v1(
    p_target_id UUID, p_state TEXT, p_evidence_sha256 TEXT,
    p_last_error_code TEXT DEFAULT NULL, p_retention_rule_id UUID DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE target data_purge_targets;
BEGIN
    IF p_state NOT IN ('deleted', 'retained', 'failed', 'unknown', 'not_found')
    THEN RAISE EXCEPTION 'INVALID_PURGE_TARGET_STATE'; END IF;
    IF p_state = 'retained' AND p_retention_rule_id IS NULL THEN
        RAISE EXCEPTION 'RETENTION_RULE_REQUIRED';
    END IF;
    UPDATE data_purge_targets SET state = p_state,
        evidence_sha256 = p_evidence_sha256,
        last_error_code = p_last_error_code,
        retention_rule_id = p_retention_rule_id,
        resolved_at = now()
     WHERE id = p_target_id AND state IN ('pending', 'failed', 'unknown')
     RETURNING * INTO target;
    IF target.id IS NULL THEN RAISE EXCEPTION 'PURGE_TARGET_NOT_RESOLVABLE'; END IF;
    INSERT INTO data_purge_events (
        purge_request_id, target_id, event_kind, actor_kind,
        evidence_sha256, metadata
    ) VALUES (
        target.purge_request_id, target.id, 'target_' || p_state,
        'orchestrator', p_evidence_sha256,
        jsonb_build_object('error_code', p_last_error_code,
                           'retention_rule_id', p_retention_rule_id)
    );
    RETURN jsonb_build_object('target_id', target.id, 'state', target.state);
END;
$$;
REVOKE ALL ON FUNCTION public.resolve_phase1_purge_target_v1(
    UUID,TEXT,TEXT,TEXT,UUID
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_purge_target_v1(
    UUID,TEXT,TEXT,TEXT,UUID
) TO service_role;

CREATE OR REPLACE FUNCTION public.finalize_phase1_purge_v1(
    p_purge_request_id UUID, p_evidence_sha256 TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE unresolved INT; req data_purge_requests;
BEGIN
    SELECT * INTO req FROM data_purge_requests
     WHERE id = p_purge_request_id FOR UPDATE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    SELECT count(*) INTO unresolved FROM data_purge_targets
     WHERE purge_request_id = req.id
       AND state IN ('pending', 'failed', 'unknown');
    IF unresolved > 0 THEN
        UPDATE data_purge_requests SET state = 'review_required'
         WHERE id = req.id;
        RETURN jsonb_build_object('purge_request_id', req.id,
            'state', 'review_required', 'unresolved_target_count', unresolved);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM data_purge_targets WHERE purge_request_id = req.id
    ) THEN RAISE EXCEPTION 'PURGE_INVENTORY_EMPTY'; END IF;
    UPDATE data_purge_requests SET state = 'done', completed_at = now()
     WHERE id = req.id;
    INSERT INTO data_purge_events (
        purge_request_id, event_kind, actor_kind, evidence_sha256
    ) VALUES (req.id, 'completed', 'orchestrator', p_evidence_sha256);
    RETURN jsonb_build_object('purge_request_id', req.id, 'state', 'done');
END;
$$;
REVOKE ALL ON FUNCTION public.finalize_phase1_purge_v1(UUID,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_phase1_purge_v1(UUID,TEXT)
    TO service_role;

CREATE OR REPLACE FUNCTION public.register_phase1_policy_v1(
    p_policy JSONB, p_product_legal JSONB,
    p_power_score_classification JSONB, p_article50 JSONB,
    p_purposes JSONB, p_actor TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    legal_id UUID; power_id UUID; article50_id UUID; v_policy_id UUID;
    item JSONB; v_purpose_id TEXT; existing_purpose processing_policy_purposes;
    registry_purpose processing_purpose_registry; policy_preexisting BOOLEAN := false;
    registration_hash TEXT;
BEGIN
    -- Serializes the reviewed admin-only registration path, so the explicit
    -- select-then-insert append-only pattern cannot race on unique versions.
    PERFORM pg_advisory_xact_lock(hashtext('phase1-policy-registry'));
    IF jsonb_typeof(p_purposes) <> 'array' OR jsonb_array_length(p_purposes) = 0
    THEN RAISE EXCEPTION 'POLICY_PURPOSES_REQUIRED'; END IF;
    IF encode(extensions.digest(COALESCE(p_policy->>'terms_copy', ''),
                                'sha256'), 'hex') <>
           COALESCE(p_policy->>'terms_copy_sha256', '')
       OR encode(extensions.digest(COALESCE(p_policy->>'privacy_copy', ''),
                                   'sha256'), 'hex') <>
           COALESCE(p_policy->>'privacy_copy_sha256', '')
       OR encode(extensions.digest(COALESCE(p_policy->>'ai_notice_copy', ''),
                                   'sha256'), 'hex') <>
           COALESCE(p_policy->>'ai_notice_copy_sha256', '')
       OR encode(extensions.digest(COALESCE(p_policy->>'agreement_copy', ''),
                                   'sha256'), 'hex') <>
           COALESCE(p_policy->>'agreement_copy_sha256', '')
    THEN RAISE EXCEPTION 'POLICY_COPY_HASH_MISMATCH'; END IF;
    IF COALESCE(p_product_legal->>'artifact_kind', '') <> 'product_legal_approval'
       OR COALESCE(p_power_score_classification->>'artifact_kind', '') <>
          'power_score_classification'
       OR COALESCE(p_article50->>'artifact_kind', '') <> 'article_50_assessment'
    THEN RAISE EXCEPTION 'LEGAL_ARTIFACT_KIND_INVALID'; END IF;
    IF COALESCE((p_power_score_classification->'metadata'->>
                 'biometric_identification')::boolean, true)
       OR COALESCE((p_power_score_classification->'metadata'->>
                    'sex_gender_inference')::boolean, true)
       OR COALESCE((p_power_score_classification->'metadata'->>
                    'emotion_intention_inference')::boolean, true)
    THEN RAISE EXCEPTION 'POWER_SCORE_CLASSIFICATION_CONFLICT'; END IF;
    IF COALESCE(p_power_score_classification->'metadata'->>'pipeline_version', '')
       <> 'voice-confidence-universal-v3'
    THEN RAISE EXCEPTION 'POWER_SCORE_PIPELINE_VERSION_UNAPPROVED'; END IF;

    SELECT id INTO legal_id FROM processing_legal_artifacts
     WHERE artifact_kind = 'product_legal_approval'
       AND version = p_product_legal->>'version';
    IF legal_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM processing_legal_artifacts WHERE id = legal_id
          AND approving_authority = p_product_legal->>'approving_authority'
          AND approved_at = (p_product_legal->>'approved_at')::timestamptz
          AND object_key = p_product_legal->>'object_key'
          AND sha256 = p_product_legal->>'sha256'
          AND metadata = COALESCE(p_product_legal->'metadata', '{}'::jsonb)
    ) THEN RAISE EXCEPTION 'LEGAL_ARTIFACT_VERSION_CONFLICT'; END IF;
    IF legal_id IS NULL THEN
        INSERT INTO processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            p_product_legal->>'artifact_kind', p_product_legal->>'version',
            p_product_legal->>'approving_authority',
            (p_product_legal->>'approved_at')::timestamptz,
            p_product_legal->>'object_key', p_product_legal->>'sha256',
            COALESCE(p_product_legal->'metadata', '{}'::jsonb)
        ) RETURNING id INTO legal_id;
    END IF;

    SELECT id INTO power_id FROM processing_legal_artifacts
     WHERE artifact_kind = 'power_score_classification'
       AND version = p_power_score_classification->>'version';
    IF power_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM processing_legal_artifacts WHERE id = power_id
          AND approving_authority = p_power_score_classification->>'approving_authority'
          AND approved_at = (p_power_score_classification->>'approved_at')::timestamptz
          AND object_key = p_power_score_classification->>'object_key'
          AND sha256 = p_power_score_classification->>'sha256'
          AND metadata = COALESCE(
              p_power_score_classification->'metadata', '{}'::jsonb)
    ) THEN RAISE EXCEPTION 'POWER_SCORE_ARTIFACT_VERSION_CONFLICT'; END IF;
    IF power_id IS NULL THEN
        INSERT INTO processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            p_power_score_classification->>'artifact_kind',
            p_power_score_classification->>'version',
            p_power_score_classification->>'approving_authority',
            (p_power_score_classification->>'approved_at')::timestamptz,
            p_power_score_classification->>'object_key',
            p_power_score_classification->>'sha256',
            COALESCE(p_power_score_classification->'metadata', '{}'::jsonb)
        ) RETURNING id INTO power_id;
    END IF;

    SELECT id INTO article50_id FROM processing_legal_artifacts
     WHERE artifact_kind = 'article_50_assessment'
       AND version = p_article50->>'version';
    IF article50_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM processing_legal_artifacts WHERE id = article50_id
          AND approving_authority = p_article50->>'approving_authority'
          AND approved_at = (p_article50->>'approved_at')::timestamptz
          AND object_key = p_article50->>'object_key'
          AND sha256 = p_article50->>'sha256'
          AND metadata = COALESCE(p_article50->'metadata', '{}'::jsonb)
    ) THEN RAISE EXCEPTION 'ARTICLE50_ARTIFACT_VERSION_CONFLICT'; END IF;
    IF article50_id IS NULL THEN
        INSERT INTO processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata
        ) VALUES (
            p_article50->>'artifact_kind', p_article50->>'version',
            p_article50->>'approving_authority',
            (p_article50->>'approved_at')::timestamptz,
            p_article50->>'object_key', p_article50->>'sha256',
            COALESCE(p_article50->'metadata', '{}'::jsonb)
        ) RETURNING id INTO article50_id;
    END IF;

    SELECT id INTO v_policy_id FROM processing_policy_versions
     WHERE version = p_policy->>'version';
    policy_preexisting := v_policy_id IS NOT NULL;
    IF policy_preexisting AND NOT EXISTS (
        SELECT 1 FROM processing_policy_versions policy
         WHERE policy.id = v_policy_id
           AND policy.status IN ('approved', 'active')
           AND policy.product_legal_artifact_id = legal_id
           AND policy.power_score_classification_artifact_id = power_id
           AND policy.article50_artifact_id = article50_id
           AND policy.terms_version = p_policy->>'terms_version'
           AND policy.terms_copy = p_policy->>'terms_copy'
           AND policy.terms_copy_sha256 = p_policy->>'terms_copy_sha256'
           AND policy.privacy_version = p_policy->>'privacy_version'
           AND policy.privacy_copy = p_policy->>'privacy_copy'
           AND policy.privacy_copy_sha256 = p_policy->>'privacy_copy_sha256'
           AND policy.ai_notice_version = p_policy->>'ai_notice_version'
           AND policy.ai_notice_copy = p_policy->>'ai_notice_copy'
           AND policy.ai_notice_copy_sha256 = p_policy->>'ai_notice_copy_sha256'
           AND policy.agreement_copy = p_policy->>'agreement_copy'
           AND policy.agreement_copy_sha256 = p_policy->>'agreement_copy_sha256'
           AND policy.allowed_countries = ARRAY(
               SELECT lower(value) FROM jsonb_array_elements_text(
                   p_policy->'allowed_countries'
               ) AS value ORDER BY lower(value)
           )
    ) THEN RAISE EXCEPTION 'POLICY_VERSION_CONFLICT'; END IF;
    IF v_policy_id IS NULL THEN
        INSERT INTO processing_policy_versions (
            version, status, product_legal_artifact_id,
            power_score_classification_artifact_id, article50_artifact_id,
            terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256, allowed_countries,
            created_by
        ) VALUES (
            p_policy->>'version', 'approved', legal_id, power_id, article50_id,
            p_policy->>'terms_version', p_policy->>'terms_copy',
            p_policy->>'terms_copy_sha256', p_policy->>'privacy_version',
            p_policy->>'privacy_copy', p_policy->>'privacy_copy_sha256',
            p_policy->>'ai_notice_version', p_policy->>'ai_notice_copy',
            p_policy->>'ai_notice_copy_sha256', p_policy->>'agreement_copy',
            p_policy->>'agreement_copy_sha256', ARRAY(
                SELECT lower(value) FROM jsonb_array_elements_text(
                    p_policy->'allowed_countries'
                ) AS value ORDER BY lower(value)
            ), p_actor
        ) RETURNING id INTO v_policy_id;
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(p_purposes) LOOP
        v_purpose_id := item->>'purpose_id';
        IF v_purpose_id IN (
            'pooled_model_improvement', 'personalized_exercise_recommendation'
        ) THEN RAISE EXCEPTION 'PHASE2_PURPOSE_FORBIDDEN'; END IF;
        SELECT * INTO registry_purpose FROM processing_purpose_registry
         WHERE id = v_purpose_id AND phase = 'phase1' FOR UPDATE;
        IF registry_purpose.id IS NULL THEN
            RAISE EXCEPTION 'UNKNOWN_PHASE1_PURPOSE';
        END IF;
        IF registry_purpose.operational AND (
            registry_purpose.capability_version IS DISTINCT FROM
                item->>'capability_version'
            OR registry_purpose.reviewed_at IS DISTINCT FROM
                (item->>'reviewed_at')::timestamptz
            OR registry_purpose.retention_control_version IS DISTINCT FROM
                item->>'retention_control_version'
            OR registry_purpose.deletion_control_version IS DISTINCT FROM
                item->>'deletion_control_version'
            OR registry_purpose.rights_control_version IS DISTINCT FROM
                item->>'rights_control_version'
        ) THEN RAISE EXCEPTION 'PURPOSE_CONTROL_VERSION_CONFLICT'; END IF;
        UPDATE processing_purpose_registry SET operational = true,
            authorizes_processing = true,
            capability_version = item->>'capability_version',
            reviewed_at = (item->>'reviewed_at')::timestamptz,
            retention_control_version = item->>'retention_control_version',
            deletion_control_version = item->>'deletion_control_version',
            rights_control_version = item->>'rights_control_version'
         WHERE id = v_purpose_id AND phase = 'phase1';
        SELECT * INTO existing_purpose FROM processing_policy_purposes
         WHERE policy_id = v_policy_id
           AND purpose_id = v_purpose_id;
        IF existing_purpose.policy_id IS NOT NULL AND (
            existing_purpose.lawful_basis_code IS DISTINCT FROM
                item->>'lawful_basis_code'
            OR existing_purpose.required_for_core_service IS DISTINCT FROM
                COALESCE((item->>'required_for_core_service')::boolean, false)
        ) THEN RAISE EXCEPTION 'POLICY_PURPOSE_CONFLICT'; END IF;
        INSERT INTO processing_policy_purposes (
            policy_id, purpose_id, lawful_basis_code,
            required_for_core_service
        ) VALUES (
            v_policy_id, v_purpose_id, item->>'lawful_basis_code',
            COALESCE((item->>'required_for_core_service')::boolean, false)
        ) ON CONFLICT (policy_id, purpose_id) DO NOTHING;
    END LOOP;
    IF policy_preexisting AND EXISTS (
        SELECT 1 FROM processing_policy_purposes existing
         WHERE existing.policy_id = v_policy_id
           AND NOT EXISTS (
               SELECT 1 FROM jsonb_array_elements(p_purposes) supplied
                WHERE supplied->>'purpose_id' = existing.purpose_id
           )
    ) THEN RAISE EXCEPTION 'POLICY_PURPOSE_SET_CONFLICT'; END IF;
    registration_hash := encode(extensions.digest(
        p_policy::text || p_product_legal::text ||
        p_power_score_classification::text || p_article50::text ||
        p_purposes::text, 'sha256'), 'hex');
    IF NOT EXISTS (
        SELECT 1 FROM phase1_authorization_admin_events
         WHERE event_kind = 'policy_registered'
           AND target_ref = v_policy_id::text
    ) THEN
        INSERT INTO phase1_authorization_admin_events (
            event_kind, actor, target_ref, payload_sha256
        ) VALUES (
            'policy_registered', p_actor, v_policy_id::text, registration_hash
        );
    END IF;
    RETURN jsonb_build_object('policy_id', v_policy_id, 'status', 'approved');
END;
$$;
REVOKE ALL ON FUNCTION public.register_phase1_policy_v1(
    JSONB,JSONB,JSONB,JSONB,JSONB,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_phase1_policy_v1(
    JSONB,JSONB,JSONB,JSONB,JSONB,TEXT
) TO service_role;

CREATE OR REPLACE FUNCTION public.activate_phase1_policy_v1(
    p_policy_version TEXT, p_actor TEXT, p_activation_evidence_sha256 TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE next_policy processing_policy_versions;
        old_policy processing_policy_versions; cutoff TIMESTAMPTZ := now();
        carryover_count INTEGER := 0;
BEGIN
    SELECT * INTO next_policy FROM processing_policy_versions
     WHERE version = p_policy_version AND status = 'approved' FOR UPDATE;
    IF next_policy.id IS NULL THEN RAISE EXCEPTION 'POLICY_NOT_APPROVED'; END IF;
    IF EXISTS (
        SELECT 1 FROM processing_policy_purposes pp
        JOIN processing_purpose_registry pr ON pr.id = pp.purpose_id
         WHERE pp.policy_id = next_policy.id
           AND (NOT pr.operational OR NOT pr.authorizes_processing)
    ) THEN RAISE EXCEPTION 'PROCESSING_PURPOSE_NOT_OPERATIONAL'; END IF;
    SELECT * INTO old_policy FROM processing_policy_versions
     WHERE status = 'active' FOR UPDATE;
    IF old_policy.id IS NOT NULL THEN
        INSERT INTO processing_job_carryovers (
            acquisition_principal_id, old_policy_id, new_policy_id,
            processing_job_id, exact_operation, cutoff_at, expires_at
        ) SELECT j.acquisition_principal_id, old_policy.id, next_policy.id,
            j.id, 'recording_transcription_ranking_feedback', cutoff,
            cutoff + interval '24 hours'
          FROM phase1_processing_jobs j
          JOIN processing_authorization_snapshots s
            ON s.id = j.authorization_snapshot_id
         WHERE s.policy_id = old_policy.id
           AND j.status IN ('pending', 'processing')
        ON CONFLICT DO NOTHING;
        GET DIAGNOSTICS carryover_count = ROW_COUNT;
        UPDATE processing_policy_versions SET status = 'retired',
            retired_at = cutoff WHERE id = old_policy.id;
    END IF;
    UPDATE processing_policy_versions SET status = 'active',
        activated_at = cutoff WHERE id = next_policy.id;
    INSERT INTO phase1_authorization_admin_events (
        event_kind, actor, target_ref, payload_sha256
    ) VALUES ('policy_activated', p_actor, next_policy.id::text,
              p_activation_evidence_sha256);
    RETURN jsonb_build_object('policy_id', next_policy.id, 'status', 'active',
                              'carryover_count', carryover_count,
                              'cutoff_at', cutoff);
END;
$$;
REVOKE ALL ON FUNCTION public.activate_phase1_policy_v1(TEXT,TEXT,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.activate_phase1_policy_v1(TEXT,TEXT,TEXT)
    TO service_role;

CREATE OR REPLACE FUNCTION public.record_ai_transparency_render_v1(
    p_acquisition_principal_id UUID, p_ai_notice_version TEXT,
    p_surface TEXT, p_client_render_id TEXT, p_rendered_at TIMESTAMPTZ,
    p_client_version TEXT, p_authenticated_actor_id UUID DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE exposure ai_transparency_exposures;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM processing_policy_versions
         WHERE status = 'active' AND ai_notice_version = p_ai_notice_version
    ) THEN RAISE EXCEPTION 'AI_NOTICE_VERSION_STALE'; END IF;
    INSERT INTO ai_transparency_exposures (
        acquisition_principal_id, ai_notice_version, surface,
        client_render_id, rendered_at, client_version,
        authenticated_actor_id
    ) VALUES (
        p_acquisition_principal_id, p_ai_notice_version, p_surface,
        p_client_render_id, p_rendered_at, p_client_version,
        p_authenticated_actor_id
    ) ON CONFLICT DO NOTHING;
    SELECT * INTO exposure FROM ai_transparency_exposures
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND ai_notice_version = p_ai_notice_version
       AND surface = p_surface AND client_render_id = p_client_render_id;
    RETURN jsonb_build_object('exposure_id', exposure.id,
                              'rendered_at', exposure.rendered_at);
END;
$$;
REVOKE ALL ON FUNCTION public.record_ai_transparency_render_v1(
    UUID,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,UUID
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_ai_transparency_render_v1(
    UUID,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,UUID
) TO service_role;

-- Historical challenge/threat learning rows remain audit evidence where an
-- older installation retained them, but no role may append or mutate them.
CREATE OR REPLACE FUNCTION public.reject_retired_direction_write_v1()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    RAISE EXCEPTION 'RETIRED_DIRECTION_PIPELINE_WRITE_FORBIDDEN';
END;
$$;
REVOKE ALL ON FUNCTION public.reject_retired_direction_write_v1()
    FROM PUBLIC, anon, authenticated;

DO $$
DECLARE table_name TEXT; relation_kind "char";
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'training_labels', 'shadow_predictions', 'model_versions',
        'reflection_clips', 'stress_snippets'
    ] LOOP
        SELECT c.relkind INTO relation_kind FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relname = table_name;
        IF relation_kind IN ('r', 'p') THEN
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',
                           table_name || '_retired_write_guard', table_name);
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE INSERT OR UPDATE OR DELETE '
                'ON public.%I FOR EACH ROW EXECUTE FUNCTION '
                'public.reject_retired_direction_write_v1()',
                table_name || '_retired_write_guard', table_name
            );
        END IF;
    END LOOP;
END;
$$;

-- Immutable evidence tables reject update/delete even from service-role code.
DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'processing_legal_artifacts', 'processing_authorization_receipts',
        'processing_authorization_receipt_purposes',
        'processing_authorization_snapshots', 'processing_recording_attempts',
        'processing_audio_objects', 'processing_provider_operations',
        'phase1_processing_job_events',
        'data_purge_events',
        'ai_transparency_exposures',
        'retired_processing_artifact_reconciliation',
        'phase1_authorization_admin_events'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',
                       table_name || '_immutable', table_name);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.reject_phase1_immutable_mutation()',
            table_name || '_immutable', table_name
        );
    END LOOP;
END;
$$;

-- Browser/admin/coach roles get no table access. Service-role code can inspect
-- rows but cannot mutate them directly; every write must pass an RPC above.
ALTER TABLE public.processing_purpose_registry ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_legal_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_policy_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_policy_purposes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_authorization_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_authorization_receipt_purposes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_service_blocks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_authorization_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_job_carryovers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_recording_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_audio_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_orphan_objects ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.phase1_processing_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.phase1_processing_job_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.phase1_processing_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_provider_permits ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_provider_operations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_purge_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_rights_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_purge_targets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_retention_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_purge_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_transparency_exposures ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.retired_processing_artifact_reconciliation ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.phase1_authorization_admin_events ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'processing_purpose_registry', 'processing_legal_artifacts',
        'processing_policy_versions', 'processing_policy_purposes',
        'processing_authorization_receipts',
        'processing_authorization_receipt_purposes',
        'processing_service_blocks', 'processing_authorization_snapshots',
        'processing_job_carryovers', 'processing_recording_attempts',
        'processing_audio_objects', 'processing_orphan_objects',
        'phase1_processing_jobs', 'phase1_processing_job_events',
        'phase1_processing_outbox',
        'processing_provider_permits', 'processing_provider_operations',
        'data_purge_requests', 'data_rights_requests',
        'data_purge_targets', 'data_retention_rules',
        'data_purge_events', 'ai_transparency_exposures',
        'retired_processing_artifact_reconciliation',
        'phase1_authorization_admin_events'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'REVOKE ALL ON public.%I FROM PUBLIC, anon, authenticated, service_role',
            table_name
        );
        EXECUTE format('GRANT SELECT ON public.%I TO service_role', table_name);
    END LOOP;
END;
$$;

COMMIT;
