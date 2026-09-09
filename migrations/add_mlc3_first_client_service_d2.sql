-- MLC-3 First-Client Service D2 — disabled implementation foundation.
--
-- Release migration 0323 creates the
-- database-authoritative service gate and exact Feedback V3 response binding
-- required before a real exercise offer can exist.  It creates no dataset,
-- training, evaluation or promotion path and seeds the contract disabled.

BEGIN;

-- Service checks are evaluated against wall-clock time.  Transaction-start
-- time would make a newly inserted check immediately stale inside a long
-- READ COMMITTED transaction.
ALTER TABLE public.exercise_authorization_checks
    ALTER COLUMN checked_at SET DEFAULT clock_timestamp();

CREATE TABLE IF NOT EXISTS public.mlc3_service_contracts (
    contract_version TEXT PRIMARY KEY CHECK (
        contract_version = 'mlc3-first-client-service-v1'
    ),
    state TEXT NOT NULL CHECK (state IN ('disabled', 'active', 'retired')),
    active_from TIMESTAMPTZ NULL,
    retired_at TIMESTAMPTZ NULL,
    practice_bucket TEXT NULL,
    coach_video_bucket TEXT NULL,
    contract_sha256 TEXT NOT NULL CHECK (contract_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (
        (state = 'disabled' AND active_from IS NULL AND retired_at IS NULL)
        OR (state = 'active' AND active_from IS NOT NULL AND retired_at IS NULL
            AND length(btrim(practice_bucket)) > 0
            AND length(btrim(coach_video_bucket)) > 0)
        OR (state = 'retired' AND active_from IS NOT NULL
            AND retired_at IS NOT NULL AND retired_at >= active_from)
    )
);

INSERT INTO public.mlc3_service_contracts (
    contract_version, state, contract_sha256
) VALUES (
    'mlc3-first-client-service-v1',
    'disabled',
    public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-first-client-service-v1',
        'design_version', 'MLC-3 First-Client Service D2',
        'state', 'disabled'
    ))
) ON CONFLICT (contract_version) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.mlc3_service_principal_allowlist (
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    contract_version TEXT NOT NULL
        REFERENCES public.mlc3_service_contracts(contract_version)
        ON DELETE RESTRICT,
    state TEXT NOT NULL CHECK (state IN ('active', 'revoked')),
    approved_by_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    approval_evidence_sha256 TEXT NOT NULL CHECK (
        approval_evidence_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    activated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    revoked_at TIMESTAMPTZ NULL,
    PRIMARY KEY (acquisition_principal_id, contract_version),
    CHECK ((state = 'active' AND revoked_at IS NULL)
        OR (state = 'revoked' AND revoked_at IS NOT NULL))
);

-- Extend the existing Feedback V3 records in place.  Synthetic rows keep the
-- historical defaults and hashes.  Service rows receive a second immutable
-- identity hash that includes the operation mode and accepted service
-- contract, so a dark set can never be replayed as a served set.
ALTER TABLE public.feedback_v3_memberships
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.feedback_v3_membership_items
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.feedback_v3_owner_responses
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;

ALTER TABLE public.feedback_v3_memberships
    DROP CONSTRAINT IF EXISTS feedback_v3_memberships_take_id_policy_version_document_snaps_key;
ALTER TABLE public.feedback_v3_memberships
    DROP CONSTRAINT IF EXISTS feedback_v3_memberships_service_mode_unique;
ALTER TABLE public.feedback_v3_memberships
    ADD CONSTRAINT feedback_v3_memberships_service_mode_unique UNIQUE (
        take_id, policy_version, document_snapshot_id, operation_mode
    );

ALTER TABLE public.feedback_v3_memberships
    DROP CONSTRAINT IF EXISTS feedback_v3_memberships_serves_user_check;
ALTER TABLE public.feedback_v3_membership_items
    DROP CONSTRAINT IF EXISTS feedback_v3_membership_items_serves_user_check;
ALTER TABLE public.feedback_v3_owner_responses
    DROP CONSTRAINT IF EXISTS feedback_v3_owner_responses_serves_user_check;

ALTER TABLE public.feedback_v3_memberships
    DROP CONSTRAINT IF EXISTS feedback_v3_memberships_operation_mode_check;
ALTER TABLE public.feedback_v3_memberships
    ADD CONSTRAINT feedback_v3_memberships_operation_mode_check CHECK (
        (operation_mode = 'synthetic_dark' AND NOT serves_user
         AND service_identity_sha256 IS NULL)
        OR (operation_mode = 'allowlisted_service' AND serves_user
            AND service_identity_sha256 ~ '^[0-9a-f]{64}$')
    );
ALTER TABLE public.feedback_v3_membership_items
    DROP CONSTRAINT IF EXISTS feedback_v3_membership_items_operation_mode_check;
ALTER TABLE public.feedback_v3_membership_items
    ADD CONSTRAINT feedback_v3_membership_items_operation_mode_check CHECK (
        (operation_mode = 'synthetic_dark' AND NOT serves_user
         AND service_identity_sha256 IS NULL)
        OR (operation_mode = 'allowlisted_service' AND serves_user
            AND service_identity_sha256 ~ '^[0-9a-f]{64}$')
    );
ALTER TABLE public.feedback_v3_owner_responses
    DROP CONSTRAINT IF EXISTS feedback_v3_owner_responses_operation_mode_check;
ALTER TABLE public.feedback_v3_owner_responses
    ADD CONSTRAINT feedback_v3_owner_responses_operation_mode_check CHECK (
        operation_mode IN ('synthetic_dark', 'allowlisted_service')
        AND NOT serves_user
        AND ((operation_mode = 'synthetic_dark'
              AND service_identity_sha256 IS NULL)
             OR (operation_mode = 'allowlisted_service'
                 AND service_identity_sha256 ~ '^[0-9a-f]{64}$'))
    );

CREATE OR REPLACE FUNCTION public.prepare_feedback_v3_service_row_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
DECLARE requested_mode TEXT := COALESCE(NULLIF(
    current_setting('willab.mlc3_operation_mode', true), ''
), 'synthetic_dark');
BEGIN
    IF requested_mode = 'allowlisted_service' THEN
        NEW.operation_mode := requested_mode;
        NEW.serves_user := TG_TABLE_NAME IN (
            'feedback_v3_memberships', 'feedback_v3_membership_items'
        );
        NEW.dataset_eligible := false;
        NEW.service_identity_sha256 := public.exercise_json_sha256_v1(
            (to_jsonb(NEW) - 'service_identity_sha256' - 'created_at'
             - 'frozen_at') || jsonb_build_object(
                'operation_mode', requested_mode,
                'service_contract_version', 'mlc3-first-client-service-v1'
             )
        );
    ELSE
        NEW.operation_mode := 'synthetic_dark';
        NEW.serves_user := false;
        NEW.dataset_eligible := false;
        NEW.service_identity_sha256 := NULL;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS feedback_v3_memberships_service_mode
    ON public.feedback_v3_memberships;
CREATE TRIGGER feedback_v3_memberships_service_mode
BEFORE INSERT ON public.feedback_v3_memberships FOR EACH ROW
EXECUTE FUNCTION public.prepare_feedback_v3_service_row_v1();
DROP TRIGGER IF EXISTS feedback_v3_membership_items_service_mode
    ON public.feedback_v3_membership_items;
CREATE TRIGGER feedback_v3_membership_items_service_mode
BEFORE INSERT ON public.feedback_v3_membership_items FOR EACH ROW
EXECUTE FUNCTION public.prepare_feedback_v3_service_row_v1();
DROP TRIGGER IF EXISTS feedback_v3_owner_responses_service_mode
    ON public.feedback_v3_owner_responses;
CREATE TRIGGER feedback_v3_owner_responses_service_mode
BEFORE INSERT ON public.feedback_v3_owner_responses FOR EACH ROW
EXECUTE FUNCTION public.prepare_feedback_v3_service_row_v1();

-- The canonical confidence response historically proves the evidence and
-- owner but not the exact rendered candidate/exposure tuple.  This immutable
-- receipt is created in the same transaction as the two existing canonical
-- response records.  Unbound historical answers remain valid product history
-- but can never authorize a service offer.
CREATE TABLE IF NOT EXISTS public.feedback_v3_service_response_bindings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    owner_user_id UUID NOT NULL,
    membership_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    feedback_exposure_id UUID NOT NULL,
    render_receipt_id UUID NOT NULL UNIQUE,
    v3_owner_response_id UUID NOT NULL UNIQUE
        REFERENCES public.feedback_v3_owner_responses(id) ON DELETE RESTRICT,
    confidence_self_report_id UUID NOT NULL UNIQUE
        REFERENCES public.confidence_self_reports(id) ON DELETE RESTRICT,
    response TEXT NOT NULL CHECK (response IN (
        'confident_yes', 'confident_in_between', 'confident_no',
        'confident_not_sure', 'confident_audio_unclear'
    )),
    response_taxonomy_version TEXT NOT NULL CHECK (
        response_taxonomy_version = 'confidence-owner-five-state-v1'
    ),
    binding_sha256 TEXT NOT NULL CHECK (binding_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (membership_id, candidate_id)
        REFERENCES public.feedback_v3_membership_items(
            membership_id, candidate_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (membership_id, acquisition_principal_id)
        REFERENCES public.feedback_v3_memberships(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (feedback_exposure_id, candidate_id)
        REFERENCES public.feedback_exposures(id, candidate_id)
        ON DELETE RESTRICT,
    UNIQUE (membership_id, candidate_id, owner_user_id)
);

CREATE TABLE IF NOT EXISTS public.feedback_v3_service_render_receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    owner_user_id UUID NOT NULL,
    membership_id UUID NOT NULL,
    candidate_id UUID NOT NULL,
    feedback_exposure_id UUID NOT NULL,
    render_instance_id UUID NOT NULL,
    content_identity_sha256 TEXT NOT NULL CHECK (
        content_identity_sha256 ~ '^[0-9a-f]{64}$'
    ),
    rendered_at TIMESTAMPTZ NOT NULL,
    client_version TEXT NOT NULL CHECK (length(btrim(client_version)) > 0),
    receipt_sha256 TEXT NOT NULL CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (membership_id, candidate_id)
        REFERENCES public.feedback_v3_membership_items(
            membership_id, candidate_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (membership_id, acquisition_principal_id)
        REFERENCES public.feedback_v3_memberships(
            id, acquisition_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (feedback_exposure_id, candidate_id)
        REFERENCES public.feedback_exposures(id, candidate_id)
        ON DELETE RESTRICT,
    UNIQUE (membership_id, candidate_id, render_instance_id),
    UNIQUE (id, acquisition_principal_id, membership_id, candidate_id,
            feedback_exposure_id)
);

-- The service offer FK depends on the replay-identity index below. Drop it
-- first so a reviewed migration can be reapplied without CASCADE.
ALTER TABLE public.exercise_service_offers
    DROP CONSTRAINT IF EXISTS exercise_service_offers_feedback_response_fk;
ALTER TABLE public.feedback_v3_service_response_bindings
    DROP CONSTRAINT IF EXISTS feedback_v3_service_response_offer_identity_unique;
ALTER TABLE public.feedback_v3_service_response_bindings
    ADD CONSTRAINT feedback_v3_service_response_offer_identity_unique UNIQUE (
        id, acquisition_principal_id, membership_id, candidate_id,
        render_receipt_id
    );

ALTER TABLE public.feedback_v3_service_response_bindings
    DROP CONSTRAINT IF EXISTS feedback_v3_service_response_render_fk;
ALTER TABLE public.feedback_v3_service_response_bindings
    ADD CONSTRAINT feedback_v3_service_response_render_fk FOREIGN KEY (
        render_receipt_id, acquisition_principal_id, membership_id,
        candidate_id, feedback_exposure_id
    ) REFERENCES public.feedback_v3_service_render_receipts(
        id, acquisition_principal_id, membership_id, candidate_id,
        feedback_exposure_id
    ) ON DELETE RESTRICT;

-- These receipts keep service authority and optional pooling independent at
-- each acquisition.  There is one receipt for the source recording and a
-- separate one for the practice recording; absence of pooled authority is an
-- explicit future-release exclusion and never blocks service.
CREATE TABLE IF NOT EXISTS public.exercise_service_acquisition_receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    acquisition_kind TEXT NOT NULL CHECK (
        acquisition_kind IN ('source_recording', 'practice_recording')
    ),
    processing_recording_attempt_id UUID NOT NULL
        REFERENCES public.processing_recording_attempts(id) ON DELETE RESTRICT,
    processing_audio_object_id UUID NOT NULL
        REFERENCES public.processing_audio_objects(id) ON DELETE RESTRICT,
    service_authorization_snapshot_id UUID NOT NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    pooled_authorization_snapshot_id UUID NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    pooled_state_at_acquisition TEXT NOT NULL CHECK (
        pooled_state_at_acquisition IN ('authorized', 'not_authorized')
    ),
    future_release_state TEXT NOT NULL CHECK (
        future_release_state IN (
            'requires_release_revalidation',
            'excluded_no_acquisition_pooling'
        )
    ),
    receipt_sha256 TEXT NOT NULL CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK (
        (pooled_state_at_acquisition = 'authorized'
         AND pooled_authorization_snapshot_id IS NOT NULL
         AND future_release_state = 'requires_release_revalidation')
        OR
        (pooled_state_at_acquisition = 'not_authorized'
         AND pooled_authorization_snapshot_id IS NULL
         AND future_release_state = 'excluded_no_acquisition_pooling')
    ),
    UNIQUE (processing_recording_attempt_id, acquisition_kind),
    UNIQUE (processing_audio_object_id, acquisition_kind)
);

-- Provider processing is authorized and frozen before any practice audio is
-- sent to transcription.  The terminal normalized output is immutable and is
-- the sole transcript source accepted by practice attempts and N1 extraction.
CREATE TABLE IF NOT EXISTS public.exercise_practice_transcription_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL
        REFERENCES public.exercise_practice_sessions(id) ON DELETE RESTRICT,
    upload_recovery_id UUID NOT NULL
        REFERENCES public.exercise_practice_upload_recoveries(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    processing_recording_attempt_id UUID NOT NULL
        REFERENCES public.processing_recording_attempts(id) ON DELETE RESTRICT,
    processing_audio_object_id UUID NOT NULL
        REFERENCES public.processing_audio_objects(id) ON DELETE RESTRICT,
    practice_acquisition_receipt_id UUID NOT NULL
        REFERENCES public.exercise_service_acquisition_receipts(id)
        ON DELETE RESTRICT,
    authorization_check_id UUID NOT NULL
        REFERENCES public.exercise_authorization_checks(id) ON DELETE RESTRICT,
    exact_audio_sha256 TEXT NOT NULL CHECK (
        exact_audio_sha256 ~ '^[0-9a-f]{64}$'
    ),
    provider TEXT NOT NULL CHECK (provider = 'openai'),
    model_version TEXT NOT NULL CHECK (model_version = 'whisper-1'),
    prompt_version TEXT NOT NULL CHECK (
        prompt_version = 'disfluent-preservation-v1'
    ),
    language_policy_version TEXT NOT NULL CHECK (
        language_policy_version = 'auto-detect-no-hint-v1'
    ),
    language_hint TEXT NULL CHECK (language_hint IS NULL),
    output_schema_version TEXT NOT NULL CHECK (
        output_schema_version = 'whisper-verbose-word-timestamps-v1'
    ),
    request_sha256 TEXT NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    permit_sha256 TEXT NOT NULL CHECK (permit_sha256 ~ '^[0-9a-f]{64}$'),
    status TEXT NOT NULL,
    normalized_output JSONB NULL CHECK (
        normalized_output IS NULL OR jsonb_typeof(normalized_output) = 'object'
    ),
    response_sha256 TEXT NULL CHECK (
        response_sha256 IS NULL OR response_sha256 ~ '^[0-9a-f]{64}$'
    ),
    transcript_state TEXT NULL CHECK (
        transcript_state IS NULL OR transcript_state IN ('available', 'missing')
    ),
    transcript_text TEXT NULL,
    transcript_sha256 TEXT NULL CHECK (
        transcript_sha256 IS NULL OR transcript_sha256 ~ '^[0-9a-f]{64}$'
    ),
    provider_error_code TEXT NULL,
    run_sha256 TEXT NULL CHECK (
        run_sha256 IS NULL OR run_sha256 ~ '^[0-9a-f]{64}$'
    ),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    finalization_idempotency_key TEXT NULL UNIQUE CHECK (
        finalization_idempotency_key IS NULL OR
        length(btrim(finalization_idempotency_key)) BETWEEN 1 AND 200
    ),
    authorized_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    permit_expires_at TIMESTAMPTZ NOT NULL,
    dispatch_idempotency_key TEXT NULL UNIQUE CHECK (
        dispatch_idempotency_key IS NULL OR
        length(btrim(dispatch_idempotency_key)) BETWEEN 1 AND 200
    ),
    dispatch_sha256 TEXT NULL CHECK (
        dispatch_sha256 IS NULL OR dispatch_sha256 ~ '^[0-9a-f]{64}$'
    ),
    dispatched_at TIMESTAMPTZ NULL,
    finalized_at TIMESTAMPTZ NULL,
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK (permit_expires_at > authorized_at),
    UNIQUE (upload_recovery_id),
    UNIQUE (processing_audio_object_id),
    UNIQUE (id, acquisition_principal_id, processing_audio_object_id)
);
ALTER TABLE public.exercise_practice_transcription_runs
    ADD COLUMN IF NOT EXISTS finalization_idempotency_key TEXT NULL UNIQUE;
ALTER TABLE public.exercise_practice_transcription_runs
    ADD COLUMN IF NOT EXISTS dispatch_idempotency_key TEXT NULL UNIQUE;
ALTER TABLE public.exercise_practice_transcription_runs
    ADD COLUMN IF NOT EXISTS dispatch_sha256 TEXT NULL;
ALTER TABLE public.exercise_practice_transcription_runs
    ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ NULL;

-- Earlier unassigned review snapshots allowed authorize -> terminal directly.
-- No production collection was possible, but populated apply/reapply rehearsal
-- databases retain those synthetic rows.  Give them an explicit, deterministic
-- legacy dispatch identity before the stricter state machine is installed.
DROP TRIGGER IF EXISTS exercise_practice_transcription_runs_immutable
    ON public.exercise_practice_transcription_runs;
UPDATE public.exercise_practice_transcription_runs row
   SET dispatch_idempotency_key =
           'legacy-reviewed-dispatch:' || row.id::TEXT,
       dispatch_sha256 = public.exercise_json_sha256_v1(jsonb_build_object(
           'contract_version', 'practice-transcription-dispatch-v1',
           'run_id', row.id,
           'request_sha256', row.request_sha256,
           'permit_sha256', row.permit_sha256,
           'idempotency_key', 'legacy-reviewed-dispatch:' || row.id::TEXT
       )),
       dispatched_at = row.authorized_at
 WHERE row.status IN ('finalized', 'uncertain', 'failed')
   AND row.dispatch_idempotency_key IS NULL;

-- This migration is safely re-applicable. Remove the previous inline
-- status/state checks before installing the named state-machine constraints
-- below.
DO $$
DECLARE
    check_name TEXT;
BEGIN
    FOR check_name IN
        SELECT constraint_row.conname
          FROM pg_constraint constraint_row
         WHERE constraint_row.conrelid =
               'public.exercise_practice_transcription_runs'::regclass
           AND constraint_row.contype = 'c'
           AND (
               pg_get_constraintdef(constraint_row.oid) LIKE
                   '%status = ANY%authorized%finalized%uncertain%failed%'
               OR pg_get_constraintdef(constraint_row.oid) LIKE
                   '%status = ''authorized''%normalized_output%'
           )
    LOOP
        EXECUTE format(
            'ALTER TABLE public.exercise_practice_transcription_runs '
            'DROP CONSTRAINT %I', check_name
        );
    END LOOP;
END;
$$;

ALTER TABLE public.exercise_practice_transcription_runs
    DROP CONSTRAINT IF EXISTS exercise_practice_transcription_status_check;
ALTER TABLE public.exercise_practice_transcription_runs
    ADD CONSTRAINT exercise_practice_transcription_status_check CHECK (
        status IN (
            'authorized', 'dispatched', 'finalized', 'uncertain', 'failed',
            'expired_after_dispatch', 'revoked_after_dispatch',
            'outcome_uncommitted'
        )
    );
ALTER TABLE public.exercise_practice_transcription_runs
    DROP CONSTRAINT IF EXISTS exercise_practice_transcription_state_check;
ALTER TABLE public.exercise_practice_transcription_runs
    ADD CONSTRAINT exercise_practice_transcription_state_check CHECK (
        (status = 'authorized'
         AND dispatch_idempotency_key IS NULL AND dispatch_sha256 IS NULL
         AND dispatched_at IS NULL AND normalized_output IS NULL
         AND response_sha256 IS NULL AND transcript_state IS NULL
         AND transcript_text IS NULL AND transcript_sha256 IS NULL
         AND provider_error_code IS NULL AND run_sha256 IS NULL
         AND finalized_at IS NULL AND finalization_idempotency_key IS NULL)
        OR (status = 'dispatched'
            AND dispatch_idempotency_key IS NOT NULL
            AND dispatch_sha256 IS NOT NULL AND dispatched_at IS NOT NULL
            AND normalized_output IS NULL AND response_sha256 IS NULL
            AND transcript_state IS NULL AND transcript_text IS NULL
            AND transcript_sha256 IS NULL AND provider_error_code IS NULL
            AND run_sha256 IS NULL AND finalized_at IS NULL
            AND finalization_idempotency_key IS NULL)
        OR (status = 'finalized'
            AND dispatch_idempotency_key IS NOT NULL
            AND dispatch_sha256 IS NOT NULL AND dispatched_at IS NOT NULL
            AND normalized_output IS NOT NULL
            AND response_sha256 IS NOT NULL AND transcript_state IS NOT NULL
            AND run_sha256 IS NOT NULL AND finalized_at IS NOT NULL
            AND finalization_idempotency_key IS NOT NULL
            AND provider_error_code IS NULL
            AND ((transcript_state = 'available'
                  AND length(btrim(transcript_text)) > 0
                  AND transcript_sha256 IS NOT NULL)
                 OR (transcript_state = 'missing'
                     AND transcript_text IS NULL
                     AND transcript_sha256 IS NULL)))
        OR (status IN ('uncertain', 'failed')
            AND dispatch_idempotency_key IS NOT NULL
            AND dispatch_sha256 IS NOT NULL AND dispatched_at IS NOT NULL
            AND normalized_output IS NULL AND response_sha256 IS NULL
            AND transcript_state IS NULL AND transcript_text IS NULL
            AND transcript_sha256 IS NULL
            AND length(btrim(provider_error_code)) > 0
            AND run_sha256 IS NOT NULL AND finalized_at IS NOT NULL
            AND finalization_idempotency_key IS NOT NULL)
        OR (status IN (
                'expired_after_dispatch', 'revoked_after_dispatch',
                'outcome_uncommitted'
            )
            AND dispatch_idempotency_key IS NOT NULL
            AND dispatch_sha256 IS NOT NULL AND dispatched_at IS NOT NULL
            AND normalized_output IS NULL AND response_sha256 IS NULL
            AND transcript_state IS NULL AND transcript_text IS NULL
            AND transcript_sha256 IS NULL
            AND length(btrim(provider_error_code)) > 0
            AND run_sha256 IS NOT NULL AND finalized_at IS NOT NULL
            AND finalization_idempotency_key IS NOT NULL)
    );

-- The original and practice confidence tasks are separate, canonical service
-- review assignments.  They do not reuse the MLC-2 training producer: these
-- five-state answers name the confidence surface but are structurally barred
-- from datasets until a future, independently approved release contract.
CREATE TABLE IF NOT EXISTS public.exercise_service_confidence_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    practice_session_id UUID NOT NULL
        REFERENCES public.exercise_practice_sessions(id) ON DELETE RESTRICT,
    evidence_kind TEXT NOT NULL CHECK (
        evidence_kind IN ('original_source', 'first_valid_practice')
    ),
    source_audio_lineage_id UUID NULL
        REFERENCES public.exercise_audio_lineages(id) ON DELETE RESTRICT,
    practice_attempt_id UUID NULL
        REFERENCES public.exercise_practice_attempts(id) ON DELETE RESTRICT,
    processing_audio_object_id UUID NOT NULL
        REFERENCES public.processing_audio_objects(id) ON DELETE RESTRICT,
    exact_audio_sha256 TEXT NOT NULL CHECK (
        exact_audio_sha256 ~ '^[0-9a-f]{64}$'
    ),
    start_offset_ms INTEGER NOT NULL CHECK (start_offset_ms >= 0),
    duration_ms INTEGER NOT NULL CHECK (duration_ms > 0),
    transcript_text TEXT NULL,
    transcript_sha256 TEXT NULL CHECK (
        transcript_sha256 IS NULL OR transcript_sha256 ~ '^[0-9a-f]{64}$'
    ),
    taxonomy_version TEXT NOT NULL CHECK (
        taxonomy_version = 'confidence-five-state-v1'
    ),
    blindness_policy_version TEXT NOT NULL CHECK (
        blindness_policy_version = 'first-client-confidence-blind-v1'
    ),
    playback_reference_id UUID NOT NULL UNIQUE,
    packet_sha256 TEXT NOT NULL CHECK (packet_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    learning_surface_id TEXT NOT NULL DEFAULT 'confidence_classification'
        CHECK (learning_surface_id = 'confidence_classification'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK (expires_at > assigned_at),
    CHECK (
        (evidence_kind = 'original_source'
         AND source_audio_lineage_id IS NOT NULL
         AND practice_attempt_id IS NULL)
        OR (evidence_kind = 'first_valid_practice'
            AND source_audio_lineage_id IS NULL
            AND practice_attempt_id IS NOT NULL)
    ),
    UNIQUE (practice_session_id, reviewer_principal_id, evidence_kind),
    UNIQUE (id, acquisition_principal_id, reviewer_principal_id)
);

ALTER TABLE public.exercise_service_confidence_assignments
    ADD COLUMN IF NOT EXISTS assignment_revision INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS supersedes_assignment_id UUID NULL
        REFERENCES public.exercise_service_confidence_assignments(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS renewal_reason TEXT NULL;
DO $$
DECLARE constraint_name TEXT;
BEGIN
    SELECT conname INTO constraint_name FROM pg_constraint
     WHERE conrelid = 'public.exercise_service_confidence_assignments'::regclass
       AND contype = 'u'
       AND pg_get_constraintdef(oid) LIKE
           '%(practice_session_id, reviewer_principal_id, evidence_kind)%'
     LIMIT 1;
    IF constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE public.exercise_service_confidence_assignments DROP CONSTRAINT %I',
            constraint_name
        );
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS
    exercise_service_confidence_assignment_revision_unique
ON public.exercise_service_confidence_assignments (
    practice_session_id, reviewer_principal_id, evidence_kind,
    assignment_revision
);

CREATE TABLE IF NOT EXISTS public.exercise_service_confidence_render_receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id UUID NOT NULL,
    acquisition_principal_id UUID NOT NULL,
    reviewer_principal_id UUID NOT NULL,
    render_instance_id UUID NOT NULL,
    packet_sha256 TEXT NOT NULL CHECK (packet_sha256 ~ '^[0-9a-f]{64}$'),
    rendered_at TIMESTAMPTZ NOT NULL,
    client_version TEXT NOT NULL CHECK (length(btrim(client_version)) > 0),
    receipt_sha256 TEXT NOT NULL CHECK (receipt_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (assignment_id, acquisition_principal_id,
                 reviewer_principal_id)
        REFERENCES public.exercise_service_confidence_assignments(
            id, acquisition_principal_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (assignment_id, render_instance_id),
    UNIQUE (id, assignment_id, reviewer_principal_id)
);

CREATE TABLE IF NOT EXISTS public.exercise_service_confidence_judgments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id UUID NOT NULL UNIQUE,
    acquisition_principal_id UUID NOT NULL,
    reviewer_principal_id UUID NOT NULL,
    render_receipt_id UUID NOT NULL UNIQUE,
    decision TEXT NOT NULL CHECK (decision IN (
        'rating_yes', 'rating_in_between', 'rating_no',
        'rating_not_sure', 'rating_audio_unclear'
    )),
    actor_provenance TEXT NOT NULL CHECK (actor_provenance = 'blind_coach'),
    taxonomy_version TEXT NOT NULL CHECK (
        taxonomy_version = 'confidence-five-state-v1'
    ),
    judgment_sha256 TEXT NOT NULL CHECK (judgment_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    decided_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    learning_surface_id TEXT NOT NULL DEFAULT 'confidence_classification'
        CHECK (learning_surface_id = 'confidence_classification'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (assignment_id, acquisition_principal_id,
                 reviewer_principal_id)
        REFERENCES public.exercise_service_confidence_assignments(
            id, acquisition_principal_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (render_receipt_id, assignment_id, reviewer_principal_id)
        REFERENCES public.exercise_service_confidence_render_receipts(
            id, assignment_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (id, assignment_id, reviewer_principal_id)
);

-- A randomized A/B preference may be linked later, but cannot substitute for
-- either five-state confidence judgment.
CREATE TABLE IF NOT EXISTS public.exercise_service_blind_review_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    practice_session_id UUID NOT NULL
        REFERENCES public.exercise_practice_sessions(id) ON DELETE RESTRICT,
    source_audio_lineage_id UUID NOT NULL
        REFERENCES public.exercise_audio_lineages(id) ON DELETE RESTRICT,
    practice_attempt_id UUID NOT NULL
        REFERENCES public.exercise_practice_attempts(id) ON DELETE RESTRICT,
    source_confidence_assignment_id UUID NOT NULL UNIQUE
        REFERENCES public.exercise_service_confidence_assignments(id)
        ON DELETE RESTRICT,
    practice_confidence_assignment_id UUID NOT NULL UNIQUE
        REFERENCES public.exercise_service_confidence_assignments(id)
        ON DELETE RESTRICT,
    paired_preference_assignment_id UUID NULL UNIQUE
        REFERENCES public.exercise_pair_assignments(id) ON DELETE RESTRICT,
    review_set_sha256 TEXT NOT NULL CHECK (review_set_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(btrim(idempotency_key)) BETWEEN 1 AND 200
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK (source_confidence_assignment_id <> practice_confidence_assignment_id),
    UNIQUE (id, acquisition_principal_id, reviewer_principal_id),
    UNIQUE (practice_session_id, reviewer_principal_id)
);

ALTER TABLE public.exercise_service_blind_review_sets
    ADD COLUMN IF NOT EXISTS review_revision INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS supersedes_review_set_id UUID NULL
        REFERENCES public.exercise_service_blind_review_sets(id)
        ON DELETE RESTRICT;
ALTER TABLE public.exercise_service_blind_review_sets
    DROP CONSTRAINT IF EXISTS
        exercise_service_blind_review_sets_source_confidence_assignment_id_key;
ALTER TABLE public.exercise_service_blind_review_sets
    DROP CONSTRAINT IF EXISTS
        exercise_service_blind_review_sets_practice_confidence_assignment_id_key;
DO $$
DECLARE constraint_name TEXT;
BEGIN
    FOR constraint_name IN
        SELECT conname FROM pg_constraint
         WHERE conrelid = 'public.exercise_service_blind_review_sets'::regclass
           AND contype = 'u'
           AND pg_get_constraintdef(oid) IN (
               'UNIQUE (source_confidence_assignment_id)',
               'UNIQUE (practice_confidence_assignment_id)'
           )
    LOOP
        EXECUTE format(
            'ALTER TABLE public.exercise_service_blind_review_sets DROP CONSTRAINT %I',
            constraint_name
        );
    END LOOP;
END $$;
DO $$
DECLARE constraint_name TEXT;
BEGIN
    SELECT conname INTO constraint_name FROM pg_constraint
     WHERE conrelid = 'public.exercise_service_blind_review_sets'::regclass
       AND contype = 'u'
       AND pg_get_constraintdef(oid) LIKE
           '%(practice_session_id, reviewer_principal_id)%'
     LIMIT 1;
    IF constraint_name IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE public.exercise_service_blind_review_sets DROP CONSTRAINT %I',
            constraint_name
        );
    END IF;
END $$;
CREATE UNIQUE INDEX IF NOT EXISTS exercise_service_review_set_revision_unique
ON public.exercise_service_blind_review_sets (
    practice_session_id, reviewer_principal_id, review_revision
);
CREATE UNIQUE INDEX IF NOT EXISTS exercise_service_review_set_pair_unique
ON public.exercise_service_blind_review_sets (
    source_confidence_assignment_id, practice_confidence_assignment_id
);

CREATE TABLE IF NOT EXISTS public.exercise_service_blind_reveal_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_set_id UUID NOT NULL UNIQUE,
    acquisition_principal_id UUID NOT NULL,
    reviewer_principal_id UUID NOT NULL,
    source_judgment_id UUID NOT NULL UNIQUE,
    practice_judgment_id UUID NOT NULL UNIQUE,
    judgment_inventory_sha256 TEXT NOT NULL CHECK (
        judgment_inventory_sha256 ~ '^[0-9a-f]{64}$'
    ),
    grant_sha256 TEXT NOT NULL CHECK (grant_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    granted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (review_set_id, acquisition_principal_id,
                 reviewer_principal_id)
        REFERENCES public.exercise_service_blind_review_sets(
            id, acquisition_principal_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (source_judgment_id)
        REFERENCES public.exercise_service_confidence_judgments(id)
        ON DELETE RESTRICT,
    FOREIGN KEY (practice_judgment_id)
        REFERENCES public.exercise_service_confidence_judgments(id)
        ON DELETE RESTRICT,
    UNIQUE (id, acquisition_principal_id, reviewer_principal_id)
);

CREATE TABLE IF NOT EXISTS public.exercise_service_blind_reveal_accesses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reveal_grant_id UUID NOT NULL,
    acquisition_principal_id UUID NOT NULL,
    reviewer_principal_id UUID NOT NULL,
    assignment_id UUID NOT NULL,
    judgment_id UUID NOT NULL,
    access_purpose TEXT NOT NULL CHECK (
        access_purpose IN ('acoustic_reference', 'guidance_authoring')
    ),
    access_sha256 TEXT NOT NULL CHECK (access_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    FOREIGN KEY (reveal_grant_id, acquisition_principal_id,
                 reviewer_principal_id)
        REFERENCES public.exercise_service_blind_reveal_grants(
            id, acquisition_principal_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    FOREIGN KEY (judgment_id, assignment_id, reviewer_principal_id)
        REFERENCES public.exercise_service_confidence_judgments(
            id, assignment_id, reviewer_principal_id
        ) ON DELETE RESTRICT,
    UNIQUE (reveal_grant_id, assignment_id, access_purpose),
    UNIQUE (id, acquisition_principal_id, reviewer_principal_id)
);

-- Extend the existing D3 guidance/media ledger in place.  Service records use
-- the same tables as dark records; no parallel pilot attachment or exposure
-- store is introduced.
ALTER TABLE public.coach_guidance_upload_permits
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS service_reveal_access_id UUID NULL
        REFERENCES public.exercise_service_blind_reveal_accesses(id)
        ON DELETE RESTRICT;
ALTER TABLE public.coach_guidance_upload_permits
    ALTER COLUMN reveal_access_id DROP NOT NULL;
ALTER TABLE public.coach_guidance_upload_permits
    DROP CONSTRAINT IF EXISTS coach_guidance_upload_permits_synthetic_only_check;
ALTER TABLE public.coach_guidance_upload_permits
    DROP CONSTRAINT IF EXISTS coach_guidance_upload_permits_service_mode_check;
ALTER TABLE public.coach_guidance_upload_permits
    ADD CONSTRAINT coach_guidance_upload_permits_service_mode_check CHECK (
        (operation_mode = 'synthetic_dark' AND synthetic_only
         AND service_contract_version IS NULL
         AND service_reveal_access_id IS NULL
         AND reveal_access_id IS NOT NULL)
        OR (operation_mode = 'allowlisted_service' AND NOT synthetic_only
            AND service_contract_version = 'mlc3-first-client-service-v1'
            AND service_reveal_access_id IS NOT NULL
            AND reveal_access_id IS NULL)
    );

DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'coach_guidance_upload_recoveries',
        'coach_guidance_upload_events',
        'coach_guidance_media_validity_events',
        'coach_guidance_independent_media_reviews'
    ] LOOP
        EXECUTE format(
            'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS operation_mode '
            'TEXT NOT NULL DEFAULT ''synthetic_dark''', relation_name
        );
        EXECUTE format(
            'ALTER TABLE public.%I ADD COLUMN IF NOT EXISTS '
            'service_contract_version TEXT NULL', relation_name
        );
        EXECUTE format(
            'ALTER TABLE public.%I DROP CONSTRAINT IF EXISTS %I',
            relation_name, relation_name || '_synthetic_only_check'
        );
        EXECUTE format(
            'ALTER TABLE public.%I DROP CONSTRAINT IF EXISTS %I',
            relation_name, relation_name || '_service_mode_check'
        );
        EXECUTE format(
            'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK ('
            '(operation_mode = ''synthetic_dark'' AND synthetic_only '
            'AND service_contract_version IS NULL) OR '
            '(operation_mode = ''allowlisted_service'' AND NOT synthetic_only '
            'AND service_contract_version = ''mlc3-first-client-service-v1''))',
            relation_name, relation_name || '_service_mode_check'
        );
    END LOOP;
END;
$$;

ALTER TABLE public.coach_guidance_media_bindings
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL;
ALTER TABLE public.coach_guidance_media_bindings
    DROP CONSTRAINT IF EXISTS coach_guidance_media_bindings_service_mode_check;
ALTER TABLE public.coach_guidance_media_bindings
    ADD CONSTRAINT coach_guidance_media_bindings_service_mode_check CHECK (
        (operation_mode = 'synthetic_dark'
         AND service_contract_version IS NULL)
        OR (operation_mode = 'allowlisted_service'
            AND service_contract_version = 'mlc3-first-client-service-v1')
    );

ALTER TABLE public.coach_guidance_attachments
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS service_review_set_id UUID NULL
        REFERENCES public.exercise_service_blind_review_sets(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS service_reveal_grant_id UUID NULL
        REFERENCES public.exercise_service_blind_reveal_grants(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS service_reveal_access_id UUID NULL
        REFERENCES public.exercise_service_blind_reveal_accesses(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS service_blind_judgment_id UUID NULL
        REFERENCES public.exercise_service_confidence_judgments(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS service_review_assignment_id UUID NULL
        REFERENCES public.exercise_service_confidence_assignments(id)
        ON DELETE RESTRICT;
ALTER TABLE public.coach_guidance_attachments
    ALTER COLUMN review_batch_id DROP NOT NULL,
    ALTER COLUMN reveal_grant_id DROP NOT NULL,
    ALTER COLUMN reveal_access_id DROP NOT NULL,
    ALTER COLUMN blind_judgment_id DROP NOT NULL,
    ALTER COLUMN review_assignment_id DROP NOT NULL;
ALTER TABLE public.coach_guidance_attachments
    DROP CONSTRAINT IF EXISTS coach_guidance_attachments_service_mode_check;
ALTER TABLE public.coach_guidance_attachments
    ADD CONSTRAINT coach_guidance_attachments_service_mode_check CHECK (
        (operation_mode = 'synthetic_dark'
         AND service_contract_version IS NULL
         AND review_batch_id IS NOT NULL AND reveal_grant_id IS NOT NULL
         AND reveal_access_id IS NOT NULL AND blind_judgment_id IS NOT NULL
         AND review_assignment_id IS NOT NULL
         AND service_review_set_id IS NULL
         AND service_reveal_grant_id IS NULL
         AND service_reveal_access_id IS NULL
         AND service_blind_judgment_id IS NULL
         AND service_review_assignment_id IS NULL)
        OR (operation_mode = 'allowlisted_service'
            AND service_contract_version = 'mlc3-first-client-service-v1'
            AND review_batch_id IS NULL AND reveal_grant_id IS NULL
            AND reveal_access_id IS NULL AND blind_judgment_id IS NULL
            AND review_assignment_id IS NULL
            AND service_review_set_id IS NOT NULL
            AND service_reveal_grant_id IS NOT NULL
            AND service_reveal_access_id IS NOT NULL
            AND service_blind_judgment_id IS NOT NULL
            AND service_review_assignment_id IS NOT NULL)
    );

ALTER TABLE public.coach_guidance_attachment_versions
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL;
ALTER TABLE public.coach_guidance_attachment_versions
    DROP CONSTRAINT IF EXISTS coach_guidance_attachment_versions_serves_user_check;
ALTER TABLE public.coach_guidance_attachment_versions
    DROP CONSTRAINT IF EXISTS coach_guidance_attachment_versions_service_mode_check;
ALTER TABLE public.coach_guidance_attachment_versions
    ADD CONSTRAINT coach_guidance_attachment_versions_service_mode_check CHECK (
        (operation_mode = 'synthetic_dark' AND NOT serves_user
         AND service_contract_version IS NULL)
        OR (operation_mode = 'allowlisted_service' AND serves_user
            AND service_contract_version = 'mlc3-first-client-service-v1')
    );

ALTER TABLE public.coach_guidance_lifecycle_events
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS recipient_principal_id UUID NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS render_instance_id UUID NULL;
ALTER TABLE public.coach_guidance_lifecycle_events
    DROP CONSTRAINT IF EXISTS coach_guidance_lifecycle_events_synthetic_only_check;
ALTER TABLE public.coach_guidance_lifecycle_events
    DROP CONSTRAINT IF EXISTS coach_guidance_lifecycle_events_serves_user_check;
ALTER TABLE public.coach_guidance_lifecycle_events
    DROP CONSTRAINT IF EXISTS coach_guidance_lifecycle_events_service_mode_check;
ALTER TABLE public.coach_guidance_lifecycle_events
    ADD CONSTRAINT coach_guidance_lifecycle_events_service_mode_check CHECK (
        (operation_mode = 'synthetic_dark' AND synthetic_only
         AND NOT serves_user AND service_contract_version IS NULL
         AND recipient_principal_id IS NULL AND render_instance_id IS NULL)
        OR (operation_mode = 'allowlisted_service' AND NOT synthetic_only
            AND service_contract_version = 'mlc3-first-client-service-v1'
            AND recipient_principal_id IS NOT NULL
            AND (event_kind <> 'rendered' OR render_instance_id IS NOT NULL)
            AND (event_kind = 'rendered' OR render_instance_id IS NULL)
            AND serves_user = (event_kind IN ('delivered', 'rendered', 'played')))
    );

ALTER TABLE public.coach_guidance_publications
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL;
ALTER TABLE public.coach_guidance_publications
    DROP CONSTRAINT IF EXISTS coach_guidance_publications_service_mode_check;
ALTER TABLE public.coach_guidance_publications
    ADD CONSTRAINT coach_guidance_publications_service_mode_check CHECK (
        (operation_mode = 'synthetic_dark'
         AND service_contract_version IS NULL AND NOT serves_user)
        OR (operation_mode = 'allowlisted_service'
            AND service_contract_version = 'mlc3-first-client-service-v1'
            AND NOT serves_user)
    );

ALTER TABLE public.coach_guidance_publication_invalidations
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL;
ALTER TABLE public.coach_guidance_publication_invalidations
    DROP CONSTRAINT IF EXISTS coach_guidance_publication_invalidations_service_mode_check;
ALTER TABLE public.coach_guidance_publication_invalidations
    ADD CONSTRAINT coach_guidance_publication_invalidations_service_mode_check
    CHECK (
        (operation_mode = 'synthetic_dark'
         AND service_contract_version IS NULL)
        OR (operation_mode = 'allowlisted_service'
            AND service_contract_version = 'mlc3-first-client-service-v1')
    );

ALTER TABLE public.exercise_service_offers
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS feedback_response_binding_id UUID NULL
        REFERENCES public.feedback_v3_service_response_bindings(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS feedback_render_receipt_id UUID NULL
        REFERENCES public.feedback_v3_service_render_receipts(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_service_offer_candidates
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_service_offer_events
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS recipient_user_id UUID NULL,
    ADD COLUMN IF NOT EXISTS render_instance_id UUID NULL,
    ADD COLUMN IF NOT EXISTS content_identity_sha256 TEXT NULL,
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;

ALTER TABLE public.exercise_service_offers
    DROP CONSTRAINT IF EXISTS exercise_service_offers_outcome_check;
ALTER TABLE public.exercise_service_offers
    ADD CONSTRAINT exercise_service_offers_outcome_check CHECK (outcome IN (
        'synthetic_matched', 'synthetic_no_match',
        'service_matched', 'coach_exercise_requested'
    ));
ALTER TABLE public.exercise_service_offers
    DROP CONSTRAINT IF EXISTS exercise_service_offers_check;
ALTER TABLE public.exercise_service_offers
    DROP CONSTRAINT IF EXISTS exercise_service_offers_selection_check;
DO $$
DECLARE legacy_constraint TEXT;
BEGIN
    FOR legacy_constraint IN
        SELECT conname
          FROM pg_constraint
         WHERE conrelid = 'public.exercise_service_offers'::regclass
           AND contype = 'c'
           AND pg_get_constraintdef(oid) ILIKE '%outcome%'
           AND pg_get_constraintdef(oid) ILIKE
               '%selected_exercise_version_id%'
    LOOP
        EXECUTE format(
            'ALTER TABLE public.exercise_service_offers DROP CONSTRAINT %I',
            legacy_constraint
        );
    END LOOP;
END;
$$;
ALTER TABLE public.exercise_service_offers
    ADD CONSTRAINT exercise_service_offers_selection_check CHECK (
        (outcome IN ('synthetic_matched', 'service_matched')
         AND selected_exercise_version_id IS NOT NULL)
        OR (outcome IN ('synthetic_no_match', 'coach_exercise_requested')
            AND selected_exercise_version_id IS NULL)
    );
ALTER TABLE public.exercise_service_offers
    DROP CONSTRAINT IF EXISTS exercise_service_offers_serves_user_check;
ALTER TABLE public.exercise_service_offers
    DROP CONSTRAINT IF EXISTS exercise_service_offers_operation_mode_check;
ALTER TABLE public.exercise_service_offers
    ADD CONSTRAINT exercise_service_offers_operation_mode_check CHECK (
        (operation_mode = 'synthetic_dark' AND NOT serves_user
         AND service_contract_version IS NULL
         AND feedback_response_binding_id IS NULL
         AND feedback_render_receipt_id IS NULL
         AND service_identity_sha256 IS NULL
         AND outcome IN ('synthetic_matched', 'synthetic_no_match'))
        OR (operation_mode = 'allowlisted_service' AND serves_user
            AND service_contract_version = 'mlc3-first-client-service-v1'
            AND feedback_response_binding_id IS NOT NULL
            AND feedback_render_receipt_id IS NOT NULL
            AND service_identity_sha256 ~ '^[0-9a-f]{64}$'
            AND outcome IN ('service_matched', 'coach_exercise_requested'))
    );
ALTER TABLE public.exercise_service_offers
    DROP CONSTRAINT IF EXISTS exercise_service_offers_feedback_membership_id_feedback_candidat_key;
ALTER TABLE public.exercise_service_offers
    DROP CONSTRAINT IF EXISTS exercise_service_offers_mode_unique;
ALTER TABLE public.exercise_service_offers
    ADD CONSTRAINT exercise_service_offers_mode_unique UNIQUE (
        feedback_membership_id, feedback_candidate_id,
        matching_policy_version, operation_mode
    );
ALTER TABLE public.exercise_service_offer_candidates
    DROP CONSTRAINT IF EXISTS exercise_service_offer_candidates_serves_user_check;
ALTER TABLE public.exercise_service_offer_candidates
    DROP CONSTRAINT IF EXISTS exercise_service_offer_candidates_operation_mode_check;
ALTER TABLE public.exercise_service_offer_candidates
    ADD CONSTRAINT exercise_service_offer_candidates_operation_mode_check CHECK (
        operation_mode IN ('synthetic_dark', 'allowlisted_service')
        AND NOT serves_user AND NOT dataset_eligible
        AND ((operation_mode = 'synthetic_dark'
              AND service_identity_sha256 IS NULL)
             OR (operation_mode = 'allowlisted_service'
                 AND service_identity_sha256 ~ '^[0-9a-f]{64}$'))
    );
ALTER TABLE public.exercise_service_offer_events
    DROP CONSTRAINT IF EXISTS exercise_service_offer_events_serves_user_check;
ALTER TABLE public.exercise_service_offer_events
    DROP CONSTRAINT IF EXISTS exercise_service_offer_events_operation_mode_check;
ALTER TABLE public.exercise_service_offer_events
    ADD CONSTRAINT exercise_service_offer_events_operation_mode_check CHECK (
        operation_mode IN ('synthetic_dark', 'allowlisted_service')
        AND NOT dataset_eligible
        AND ((operation_mode = 'synthetic_dark' AND NOT serves_user
              AND service_identity_sha256 IS NULL
              AND recipient_user_id IS NULL
              AND render_instance_id IS NULL
              AND content_identity_sha256 IS NULL)
             OR (operation_mode = 'allowlisted_service'
                 AND service_identity_sha256 ~ '^[0-9a-f]{64}$'
                 AND serves_user = (event_kind IN (
                     'delivery_prepared', 'render_confirmed',
                     'playback_started', 'playback_completed'
                 ))
                 AND ((event_kind = 'assignment_prepared'
                       AND recipient_user_id IS NULL
                       AND render_instance_id IS NULL)
                      OR (event_kind <> 'assignment_prepared'
                          AND recipient_user_id IS NOT NULL
                          AND content_identity_sha256 ~ '^[0-9a-f]{64}$'
                          AND (event_kind <> 'render_confirmed'
                               OR render_instance_id IS NOT NULL))))
    ));

ALTER TABLE public.exercise_service_offers
    DROP CONSTRAINT IF EXISTS exercise_service_offers_feedback_response_fk;
ALTER TABLE public.exercise_service_offers
    ADD CONSTRAINT exercise_service_offers_feedback_response_fk FOREIGN KEY (
        feedback_response_binding_id, acquisition_principal_id,
        feedback_membership_id, feedback_candidate_id, feedback_render_receipt_id
    ) REFERENCES public.feedback_v3_service_response_bindings(
        id, acquisition_principal_id, membership_id, candidate_id,
        render_receipt_id
    ) ON DELETE RESTRICT;

CREATE OR REPLACE FUNCTION public.prepare_exercise_service_row_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
DECLARE requested_mode TEXT := COALESCE(NULLIF(
    current_setting('willab.mlc3_operation_mode', true), ''
), 'synthetic_dark');
BEGIN
    IF requested_mode = 'allowlisted_service' THEN
        NEW.operation_mode := requested_mode;
        NEW.dataset_eligible := false;
        IF TG_TABLE_NAME = 'exercise_service_offers' THEN
            NEW.serves_user := true;
            NEW.service_contract_version := 'mlc3-first-client-service-v1';
        ELSIF TG_TABLE_NAME = 'exercise_service_offer_events' THEN
            NEW.serves_user := NEW.event_kind IN (
                'delivery_prepared', 'render_confirmed',
                'playback_started', 'playback_completed'
            );
        ELSE
            NEW.serves_user := false;
        END IF;
        NEW.service_identity_sha256 := public.exercise_json_sha256_v1(
            (to_jsonb(NEW) - 'service_identity_sha256' - 'created_at'
             - 'prepared_at') || jsonb_build_object(
                'operation_mode', requested_mode,
                'service_contract_version', 'mlc3-first-client-service-v1'
             )
        );
    ELSE
        NEW.operation_mode := 'synthetic_dark';
        NEW.serves_user := false;
        NEW.dataset_eligible := false;
        NEW.service_identity_sha256 := NULL;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS exercise_service_offers_service_mode
    ON public.exercise_service_offers;
CREATE TRIGGER exercise_service_offers_service_mode
BEFORE INSERT ON public.exercise_service_offers FOR EACH ROW
EXECUTE FUNCTION public.prepare_exercise_service_row_v1();

ALTER TABLE public.exercise_practice_sessions
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS source_acquisition_receipt_id UUID NULL
        REFERENCES public.exercise_service_acquisition_receipts(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS measurement_extractor_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS measurement_feature_schema_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS validity_contract_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_practice_upload_recoveries
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS byte_size BIGINT NULL,
    ADD COLUMN IF NOT EXISTS content_type TEXT NULL,
    ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS recording_id UUID NULL,
    ADD COLUMN IF NOT EXISTS authorization_snapshot_id UUID NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS pooled_authorization_snapshot_id UUID NULL
        REFERENCES public.processing_authorization_snapshots(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS authorization_check_id UUID NULL
        REFERENCES public.exercise_authorization_checks(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_practice_attempts
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS practice_acquisition_receipt_id UUID NULL
        REFERENCES public.exercise_service_acquisition_receipts(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS transcript_state TEXT NOT NULL
        DEFAULT 'available',
    ADD COLUMN IF NOT EXISTS transcript_missing_reason TEXT NULL,
    ADD COLUMN IF NOT EXISTS transcription_run_id UUID NULL
        REFERENCES public.exercise_practice_transcription_runs(id)
        ON DELETE RESTRICT,
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_practice_attempts
    ALTER COLUMN transcript_text DROP NOT NULL;
ALTER TABLE public.exercise_practice_attempts
    ALTER COLUMN transcript_sha256 DROP NOT NULL;
ALTER TABLE public.exercise_practice_measurement_revisions
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_practice_validity_assessments
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_practice_selection_revisions
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_practice_events
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS recipient_user_id UUID NULL,
    ADD COLUMN IF NOT EXISTS render_instance_id UUID NULL,
    ADD COLUMN IF NOT EXISTS content_identity_sha256 TEXT NULL,
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;

ALTER TABLE public.exercise_practice_sessions
    DROP CONSTRAINT IF EXISTS exercise_practice_sessions_serves_user_check;
ALTER TABLE public.exercise_practice_sessions
    DROP CONSTRAINT IF EXISTS exercise_practice_sessions_operation_mode_check;
ALTER TABLE public.exercise_practice_sessions
    ADD CONSTRAINT exercise_practice_sessions_operation_mode_check CHECK (
        (operation_mode = 'synthetic_dark' AND NOT serves_user
         AND service_contract_version IS NULL
         AND source_acquisition_receipt_id IS NULL
         AND measurement_extractor_version IS NULL
         AND measurement_feature_schema_version IS NULL
         AND validity_contract_version IS NULL
         AND service_identity_sha256 IS NULL)
        OR (operation_mode = 'allowlisted_service' AND serves_user
            AND service_contract_version = 'mlc3-first-client-service-v1'
            AND source_acquisition_receipt_id IS NOT NULL
            AND measurement_extractor_version =
                'rushed-phrase-endings-n1-extractor-v1'
            AND measurement_feature_schema_version =
                'rushed-phrase-endings-n1-features-v1'
            AND validity_contract_version =
                'rushed-phrase-endings-n1-validity-v1'
            AND service_identity_sha256 ~ '^[0-9a-f]{64}$')
    );
ALTER TABLE public.exercise_practice_upload_recoveries
    DROP CONSTRAINT IF EXISTS exercise_practice_upload_recoveries_storage_provider_check;
ALTER TABLE public.exercise_practice_upload_recoveries
    DROP CONSTRAINT IF EXISTS exercise_practice_upload_recoveries_provider_check;
ALTER TABLE public.exercise_practice_upload_recoveries
    ADD CONSTRAINT exercise_practice_upload_recoveries_provider_check CHECK (
        (operation_mode = 'synthetic_dark'
         AND storage_provider = 'local_synthetic'
         AND byte_size IS NULL AND content_type IS NULL
         AND expires_at IS NULL AND recording_id IS NULL
         AND authorization_snapshot_id IS NULL
         AND pooled_authorization_snapshot_id IS NULL
         AND authorization_check_id IS NULL
         AND service_identity_sha256 IS NULL)
        OR (operation_mode = 'allowlisted_service'
            AND storage_provider = 'r2'
            AND byte_size > 0
            AND content_type LIKE 'audio/%'
            AND expires_at IS NOT NULL
            AND recording_id IS NOT NULL
            AND authorization_snapshot_id IS NOT NULL
            AND authorization_check_id IS NOT NULL
            AND service_identity_sha256 ~ '^[0-9a-f]{64}$')
    );
ALTER TABLE public.exercise_practice_upload_recoveries
    DROP CONSTRAINT IF EXISTS exercise_practice_upload_recoveries_status_check;
ALTER TABLE public.exercise_practice_upload_recoveries
    ADD CONSTRAINT exercise_practice_upload_recoveries_status_check CHECK (
        status IN (
            'write_started', 'write_acknowledged', 'attached',
            'orphaned', 'deleted'
        )
    );

DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'exercise_practice_attempts',
        'exercise_practice_measurement_revisions',
        'exercise_practice_validity_assessments',
        'exercise_practice_selection_revisions'
    ] LOOP
        EXECUTE format(
            'ALTER TABLE public.%I DROP CONSTRAINT IF EXISTS %I',
            relation_name, relation_name || '_serves_user_check'
        );
        EXECUTE format(
            'ALTER TABLE public.%I DROP CONSTRAINT IF EXISTS %I',
            relation_name, relation_name || '_operation_mode_check'
        );
        EXECUTE format(
            'ALTER TABLE public.%I ADD CONSTRAINT %I CHECK ('
            'operation_mode IN (''synthetic_dark'',''allowlisted_service'') '
            'AND NOT serves_user AND NOT dataset_eligible AND ('
            '(operation_mode=''synthetic_dark'' AND service_identity_sha256 IS NULL) OR '
            '(operation_mode=''allowlisted_service'' AND '
            'service_identity_sha256 ~ ''^[0-9a-f]{64}$'')))',
            relation_name, relation_name || '_operation_mode_check'
        );
    END LOOP;
END;
$$;

ALTER TABLE public.exercise_practice_attempts
    DROP CONSTRAINT IF EXISTS exercise_practice_attempt_service_receipt_check;
ALTER TABLE public.exercise_practice_attempts
    ADD CONSTRAINT exercise_practice_attempt_service_receipt_check CHECK (
        (operation_mode = 'synthetic_dark'
         AND practice_acquisition_receipt_id IS NULL
         AND transcription_run_id IS NULL)
        OR (operation_mode = 'allowlisted_service'
            AND practice_acquisition_receipt_id IS NOT NULL
            AND transcription_run_id IS NOT NULL)
    );
ALTER TABLE public.exercise_practice_attempts
    DROP CONSTRAINT IF EXISTS exercise_practice_attempt_transcription_run_fk;
ALTER TABLE public.exercise_practice_attempts
    ADD CONSTRAINT exercise_practice_attempt_transcription_run_fk FOREIGN KEY (
        transcription_run_id, acquisition_principal_id,
        processing_audio_object_id
    ) REFERENCES public.exercise_practice_transcription_runs(
        id, acquisition_principal_id, processing_audio_object_id
    ) ON DELETE RESTRICT;
ALTER TABLE public.exercise_practice_attempts
    DROP CONSTRAINT IF EXISTS exercise_practice_attempt_transcript_state_check;
ALTER TABLE public.exercise_practice_attempts
    ADD CONSTRAINT exercise_practice_attempt_transcript_state_check CHECK (
        (transcript_state = 'available' AND transcript_text IS NOT NULL
         AND length(btrim(transcript_text)) > 0
         AND transcript_sha256 ~ '^[0-9a-f]{64}$'
         AND transcript_missing_reason IS NULL)
        OR (operation_mode = 'allowlisted_service'
            AND transcript_state = 'missing'
            AND transcript_text IS NULL AND transcript_sha256 IS NULL
            AND length(btrim(transcript_missing_reason)) > 0)
    );
ALTER TABLE public.exercise_practice_events
    DROP CONSTRAINT IF EXISTS exercise_practice_events_serves_user_check;
ALTER TABLE public.exercise_practice_events
    DROP CONSTRAINT IF EXISTS exercise_practice_events_operation_mode_check;
ALTER TABLE public.exercise_practice_events
    ADD CONSTRAINT exercise_practice_events_operation_mode_check CHECK (
        operation_mode IN ('synthetic_dark', 'allowlisted_service')
        AND NOT dataset_eligible
        AND ((operation_mode = 'synthetic_dark' AND NOT serves_user
              AND service_identity_sha256 IS NULL
              AND recipient_user_id IS NULL
              AND render_instance_id IS NULL
              AND content_identity_sha256 IS NULL)
             OR (operation_mode = 'allowlisted_service'
                 AND service_identity_sha256 ~ '^[0-9a-f]{64}$'
                 AND serves_user = (event_kind IN (
                     'delivery_prepared', 'render_confirmed',
                     'playback_started', 'playback_completed'
                 ))
                 AND recipient_user_id IS NOT NULL
                 AND content_identity_sha256 ~ '^[0-9a-f]{64}$'
                 AND (event_kind <> 'render_confirmed'
                      OR render_instance_id IS NOT NULL)))
    );

CREATE OR REPLACE FUNCTION public.prepare_exercise_practice_service_row_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
DECLARE requested_mode TEXT := COALESCE(NULLIF(
    current_setting('willab.mlc3_operation_mode', true), ''
), 'synthetic_dark');
BEGIN
    IF requested_mode = 'allowlisted_service' THEN
        NEW.operation_mode := requested_mode;
        IF TG_TABLE_NAME = 'exercise_practice_sessions' THEN
            NEW.serves_user := true;
            NEW.dataset_eligible := false;
            NEW.service_contract_version := 'mlc3-first-client-service-v1';
        ELSIF TG_TABLE_NAME = 'exercise_practice_events' THEN
            NEW.serves_user := NEW.event_kind IN (
                'delivery_prepared', 'render_confirmed',
                'playback_started', 'playback_completed'
            );
            NEW.dataset_eligible := false;
        ELSIF TG_TABLE_NAME <> 'exercise_practice_upload_recoveries' THEN
            NEW.serves_user := false;
            NEW.dataset_eligible := false;
        END IF;
        NEW.service_identity_sha256 := public.exercise_json_sha256_v1(
            (to_jsonb(NEW) - 'service_identity_sha256' - 'created_at')
            || jsonb_build_object(
                'operation_mode', requested_mode,
                'service_contract_version', 'mlc3-first-client-service-v1'
            )
        );
    ELSE
        NEW.operation_mode := 'synthetic_dark';
        IF TG_TABLE_NAME <> 'exercise_practice_upload_recoveries' THEN
            NEW.serves_user := false;
            NEW.dataset_eligible := false;
        END IF;
        NEW.service_identity_sha256 := NULL;
    END IF;
    RETURN NEW;
END;
$$;

DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'exercise_practice_sessions',
        'exercise_practice_upload_recoveries',
        'exercise_practice_attempts',
        'exercise_practice_measurement_revisions',
        'exercise_practice_validity_assessments',
        'exercise_practice_selection_revisions',
        'exercise_practice_events'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',
            relation_name || '_service_mode', relation_name);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE INSERT ON public.%I FOR EACH ROW '
            'EXECUTE FUNCTION public.prepare_exercise_practice_service_row_v1()',
            relation_name || '_service_mode', relation_name
        );
    END LOOP;
END;
$$;
DROP TRIGGER IF EXISTS exercise_service_offer_candidates_service_mode
    ON public.exercise_service_offer_candidates;
CREATE TRIGGER exercise_service_offer_candidates_service_mode
BEFORE INSERT ON public.exercise_service_offer_candidates FOR EACH ROW
EXECUTE FUNCTION public.prepare_exercise_service_row_v1();
DROP TRIGGER IF EXISTS exercise_service_offer_events_service_mode
    ON public.exercise_service_offer_events;
CREATE TRIGGER exercise_service_offer_events_service_mode
BEFORE INSERT ON public.exercise_service_offer_events FOR EACH ROW
EXECUTE FUNCTION public.prepare_exercise_service_row_v1();

-- A service exposure is prepared with the frozen candidate set and becomes
-- canonically shown only when the authenticated client confirms rendering.
ALTER TABLE public.feedback_exposures
    DROP CONSTRAINT IF EXISTS feedback_exposure_shown_check;
DO $$
DECLARE legacy_constraint TEXT;
BEGIN
    FOR legacy_constraint IN
        SELECT conname
          FROM pg_constraint
         WHERE conrelid = 'public.feedback_exposures'::regclass
           AND contype = 'c'
           AND pg_get_constraintdef(oid) ILIKE '%is_selected%'
           AND pg_get_constraintdef(oid) ILIKE '%shown_at%'
    LOOP
        EXECUTE format(
            'ALTER TABLE public.feedback_exposures DROP CONSTRAINT %I',
            legacy_constraint
        );
    END LOOP;
END;
$$;
ALTER TABLE public.feedback_exposures
    ADD CONSTRAINT feedback_exposure_shown_check CHECK (
        (is_selected AND position_shown IS NOT NULL)
        OR (NOT is_selected AND position_shown IS NULL AND shown_at IS NULL)
    );

CREATE OR REPLACE FUNCTION public.reject_feedback_exposure_mutation_v2()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF current_setting(
        'willab.feedback_exposure_render_transition', true
    ) = 'on'
       AND OLD.is_selected
       AND OLD.shown_at IS NULL
       AND NEW.shown_at IS NOT NULL
       AND (to_jsonb(NEW) - 'shown_at') = (to_jsonb(OLD) - 'shown_at')
    THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'canonical feedback evidence is append-only';
END;
$$;

DROP TRIGGER IF EXISTS feedback_exposures_append_only
    ON public.feedback_exposures;
CREATE TRIGGER feedback_exposures_append_only
BEFORE UPDATE OR DELETE ON public.feedback_exposures FOR EACH ROW
EXECUTE FUNCTION public.reject_feedback_exposure_mutation_v2();

CREATE OR REPLACE FUNCTION public.require_mlc3_service_principal_v1(
    p_acquisition_principal_id UUID
) RETURNS public.mlc3_service_contracts
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    contract public.mlc3_service_contracts;
    wall_now TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'MLC3_SERVICE_REQUIRES_READ_COMMITTED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-principal:' || p_acquisition_principal_id::TEXT, 0
    ));
    SELECT * INTO contract
      FROM public.mlc3_service_contracts
     WHERE contract_version = 'mlc3-first-client-service-v1'
       AND state = 'active'
       AND active_from <= wall_now
       AND (retired_at IS NULL OR retired_at > wall_now)
       AND length(btrim(practice_bucket)) > 0
       AND length(btrim(coach_video_bucket)) > 0
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'MLC3_SERVICE_CONTRACT_NOT_ACTIVE';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.mlc3_service_principal_allowlist allowed
         WHERE allowed.acquisition_principal_id = p_acquisition_principal_id
           AND allowed.contract_version = contract.contract_version
           AND allowed.state = 'active'
           AND allowed.revoked_at IS NULL
    ) OR EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id = p_acquisition_principal_id
           AND purge.state <> 'done'
    ) THEN
        RAISE EXCEPTION 'MLC3_SERVICE_PRINCIPAL_NOT_ALLOWED';
    END IF;
    RETURN contract;
END;
$$;

CREATE OR REPLACE FUNCTION public.serialize_mlc3_service_purge_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-principal:' || NEW.acquisition_principal_id::TEXT, 0
    ));
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS data_purge_requests_mlc3_service_serialization
    ON public.data_purge_requests;
CREATE TRIGGER data_purge_requests_mlc3_service_serialization
BEFORE INSERT OR UPDATE ON public.data_purge_requests FOR EACH ROW
EXECUTE FUNCTION public.serialize_mlc3_service_purge_v1();

CREATE OR REPLACE FUNCTION public.record_exercise_service_acquisition_receipt_v1(
    p_acquisition_principal_id UUID,
    p_acquisition_kind TEXT,
    p_processing_recording_attempt_id UUID,
    p_processing_audio_object_id UUID,
    p_service_authorization_snapshot_id UUID,
    p_pooled_authorization_snapshot_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_acquisition_receipts
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    recording_attempt public.processing_recording_attempts;
    audio_object public.processing_audio_objects;
    service_snapshot public.processing_authorization_snapshots;
    pooled_snapshot public.processing_authorization_snapshots;
    result public.exercise_service_acquisition_receipts;
    derived_hash TEXT;
BEGIN
    IF p_acquisition_kind NOT IN ('source_recording', 'practice_recording')
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_ACQUISITION_RECEIPT_INVALID';
    END IF;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT * INTO STRICT recording_attempt
      FROM public.processing_recording_attempts row
     WHERE row.id = p_processing_recording_attempt_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.authorization_snapshot_id =
           p_service_authorization_snapshot_id
       AND row.status NOT IN ('cancelled', 'purged');
    SELECT * INTO STRICT audio_object
      FROM public.processing_audio_objects row
     WHERE row.id = p_processing_audio_object_id
       AND row.recording_attempt_id = recording_attempt.id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.deleted_at IS NULL;
    SELECT * INTO STRICT service_snapshot
      FROM public.processing_authorization_snapshots row
     WHERE row.id = p_service_authorization_snapshot_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.source_recording_id = recording_attempt.recording_id
       AND row.purpose_id IN (
           'recording_voice_processing', 'transcription_feedback',
           'personalized_exercise_recommendation'
       );
    IF p_pooled_authorization_snapshot_id IS NOT NULL THEN
        SELECT * INTO STRICT pooled_snapshot
          FROM public.processing_authorization_snapshots row
         WHERE row.id = p_pooled_authorization_snapshot_id
           AND row.acquisition_principal_id = p_acquisition_principal_id
           AND row.source_recording_id = recording_attempt.recording_id
           AND row.purpose_id = 'pooled_model_improvement'
           AND row.receipt_id = service_snapshot.receipt_id
           AND row.policy_id = service_snapshot.policy_id
           AND row.created_at <= recording_attempt.created_at
           AND row.authority_checked_at <= recording_attempt.created_at;
    END IF;
    derived_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-first-client-service-v1',
        'acquisition_principal_id', p_acquisition_principal_id,
        'acquisition_kind', p_acquisition_kind,
        'processing_recording_attempt_id', recording_attempt.id,
        'processing_audio_object_id', audio_object.id,
        'exact_audio_sha256', audio_object.exact_bytes_sha256,
        'service_authorization_snapshot_id', service_snapshot.id,
        'pooled_authorization_snapshot_id', pooled_snapshot.id,
        'pooled_state_at_acquisition', CASE
            WHEN pooled_snapshot.id IS NULL THEN 'not_authorized'
            ELSE 'authorized' END
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-acquisition:' || p_idempotency_key, 0
    ));
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_recording_attempts attempt
          JOIN public.processing_audio_objects object_row
            ON object_row.recording_attempt_id = attempt.id
           AND object_row.id = audio_object.id
           AND object_row.deleted_at IS NULL
         WHERE attempt.id = recording_attempt.id
           AND attempt.acquisition_principal_id = p_acquisition_principal_id
           AND attempt.status NOT IN ('cancelled', 'purged')
    ) THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_ACQUISITION_NOT_LIVE';
    END IF;
    SELECT * INTO result
      FROM public.exercise_service_acquisition_receipts row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.receipt_sha256 <> derived_hash THEN
            RAISE EXCEPTION 'EXERCISE_SERVICE_ACQUISITION_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.exercise_service_acquisition_receipts (
        acquisition_principal_id, acquisition_kind,
        processing_recording_attempt_id, processing_audio_object_id,
        service_authorization_snapshot_id,
        pooled_authorization_snapshot_id, pooled_state_at_acquisition,
        future_release_state, receipt_sha256, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_acquisition_kind,
        recording_attempt.id, audio_object.id, service_snapshot.id,
        pooled_snapshot.id,
        CASE WHEN pooled_snapshot.id IS NULL
             THEN 'not_authorized' ELSE 'authorized' END,
        CASE WHEN pooled_snapshot.id IS NULL
             THEN 'excluded_no_acquisition_pooling'
             ELSE 'requires_release_revalidation' END,
        derived_hash, p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_feedback_v3_service_membership_live_v1(
    p_membership_id UUID,
    p_acquisition_principal_id UUID
) RETURNS public.feedback_v3_memberships
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    membership public.feedback_v3_memberships;
    snapshot public.ideal_text_document_snapshots;
    take_row public.v2_sessions;
    invalid_item_count INTEGER;
BEGIN
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT * INTO STRICT membership
      FROM public.feedback_v3_memberships
     WHERE id = p_membership_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND operation_mode = 'allowlisted_service'
       AND serves_user
       AND NOT dataset_eligible
       AND service_identity_sha256 ~ '^[0-9a-f]{64}$';
    SELECT * INTO STRICT snapshot
      FROM public.ideal_text_document_snapshots
     WHERE id = membership.document_snapshot_id
       AND project_id = membership.project_id
       AND acquisition_principal_id = membership.acquisition_principal_id
       AND source_take_session_id = membership.take_id;
    SELECT * INTO STRICT take_row
      FROM public.v2_sessions
     WHERE id = membership.take_id
       AND project_id = membership.project_id
       AND owner_principal_id = membership.acquisition_principal_id;
    IF NOT EXISTS (
        SELECT 1
          FROM public.ideal_text_document_heads head
          JOIN public.ideal_text_document_generations generation
            ON generation.arc_id = head.arc_id
         WHERE head.snapshot_id = snapshot.id
           AND generation.generation = snapshot.source_generation
    ) OR membership.document_snapshot_sha256 <> snapshot.payload_sha256
       OR membership.content_identity_sha256 <>
          public.feedback_v3_content_identity_v1(snapshot.payload)
       OR EXISTS (
          SELECT 1 FROM public.data_purge_requests purge
           WHERE purge.acquisition_principal_id =
                 membership.acquisition_principal_id
             AND purge.state <> 'done'
       ) THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_SOURCE_STALE';
    END IF;
    SELECT count(*) INTO invalid_item_count
      FROM public.feedback_v3_membership_items item
      LEFT JOIN public.evidence_spans evidence
        ON evidence.id = item.evidence_span_id
       AND evidence.owner_principal_id = membership.acquisition_principal_id
       AND evidence.project_id = membership.project_id
       AND evidence.take_id = membership.take_id
       AND evidence.recording_id = take_row.recording_1_id
      LEFT JOIN public.snippets snippet
        ON snippet.id = item.snippet_id
       AND snippet.id = evidence.legacy_piece_id
       AND snippet.session_id = membership.take_id
       AND snippet.recording_id = take_row.recording_1_id
       AND snippet.start_offset_ms = evidence.start_ms
       AND snippet.duration_ms = evidence.end_ms - evidence.start_ms
     WHERE item.membership_id = membership.id
       AND (item.operation_mode <> 'allowlisted_service'
            OR NOT item.serves_user
            OR item.dataset_eligible
            OR item.service_identity_sha256 IS NULL
            OR evidence.id IS NULL OR snippet.id IS NULL);
    IF invalid_item_count <> 0 OR NOT EXISTS (
        SELECT 1
          FROM public.processing_recording_attempts attempt
          JOIN public.processing_audio_objects object_row
            ON object_row.recording_attempt_id = attempt.id
           AND object_row.acquisition_principal_id =
               membership.acquisition_principal_id
           AND object_row.deleted_at IS NULL
         WHERE attempt.id = membership.take_id
           AND attempt.acquisition_principal_id =
               membership.acquisition_principal_id
           AND attempt.project_id = membership.project_id
           AND attempt.recording_id = take_row.recording_1_id
    ) THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_SOURCE_STALE';
    END IF;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    RETURN membership;
END;
$$;

-- Record the complete V3 candidate inventory without weakening the historical
-- exact-three writer.  Selection is product preparation here; a separate
-- authenticated render receipt is the only evidence that a card was shown.
CREATE OR REPLACE FUNCTION public.record_feedback_v3_service_candidate_set_v1(
    p_acquisition_principal_id UUID,
    p_project_id UUID,
    p_take_id UUID,
    p_bundle JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    take_row public.v2_sessions;
    transcript JSONB;
    versions JSONB;
    selected_keys JSONB;
    candidate_rows JSONB;
    transcript_id UUID;
    candidate_set_id UUID;
    slide_value JSONB;
    paragraph_value JSONB;
    candidate_value JSONB;
    evidence JSONB;
    slide_id UUID;
    paragraph_id UUID;
    evidence_id UUID;
    candidate_id UUID;
    selected_position INTEGER;
    stored_hash TEXT;
    candidate_count INTEGER;
    selected_count INTEGER;
BEGIN
    IF jsonb_typeof(p_bundle) <> 'object' THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_BUNDLE_INVALID';
    END IF;
    transcript := p_bundle->'transcript';
    versions := p_bundle->'versions';
    selected_keys := p_bundle->'selected_keys';
    candidate_rows := p_bundle->'candidates';
    IF jsonb_typeof(transcript) <> 'object'
       OR jsonb_typeof(versions) <> 'object'
       OR versions->>'manager_rules_version' <>
          'take-feedback-policy-v3-serving-v1'
       OR jsonb_typeof(selected_keys) <> 'array'
       OR jsonb_array_length(selected_keys) < 1
       OR NOT selected_keys @>
          '[{"feedback_family":"confident_voice"}]'::JSONB
       OR jsonb_typeof(candidate_rows) <> 'array'
       OR jsonb_array_length(candidate_rows) <
          jsonb_array_length(selected_keys)
       OR COALESCE(btrim(p_bundle->>'idempotency_key'), '') = ''
       OR p_bundle->>'owner_principal_id' <>
          p_acquisition_principal_id::TEXT
       OR p_bundle->>'project_id' <> p_project_id::TEXT
       OR p_bundle->>'take_id' <> p_take_id::TEXT
    THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_BUNDLE_INVALID';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(candidate_rows) value
         WHERE value->>'feedback_family' NOT IN (
            'confident_voice', 'rewrite_clarity', 'great_formulation'
         )
            OR COALESCE((value->>'training_eligible')::BOOLEAN, false)
            OR COALESCE(value->>'ineligibility_reason', '') <>
               'service_product_evidence_only'
    ) OR EXISTS (
        SELECT 1 FROM jsonb_array_elements(selected_keys) value
         WHERE value->>'feedback_family' NOT IN (
            'confident_voice', 'rewrite_clarity', 'great_formulation'
         ) OR COALESCE(value->>'id', '') = ''
    ) THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_DATASET_BOUNDARY_INVALID';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'feedback-v3-service-candidate-set:' ||
        p_bundle->>'idempotency_key', 0
    ));
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT * INTO STRICT take_row
      FROM public.v2_sessions row
     WHERE row.id = p_take_id
       AND row.project_id = p_project_id
       AND row.owner_principal_id = p_acquisition_principal_id
       AND COALESCE(row.recording_kind, 'spoken') = 'spoken'
       AND row.paired_session_id IS NULL
     FOR SHARE;
    IF NOT EXISTS (
        SELECT 1 FROM public.projects project
         WHERE project.id = p_project_id
           AND project.owner_principal_id = p_acquisition_principal_id
    ) OR NOT EXISTS (
        SELECT 1
          FROM public.processing_recording_attempts attempt
          JOIN public.processing_audio_objects object_row
            ON object_row.recording_attempt_id = attempt.id
           AND object_row.acquisition_principal_id =
               p_acquisition_principal_id
           AND object_row.deleted_at IS NULL
         WHERE attempt.id = p_take_id
           AND attempt.project_id = p_project_id
           AND attempt.recording_id = take_row.recording_1_id
           AND attempt.status NOT IN ('cancelled', 'purged')
    ) THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_SOURCE_NOT_LIVE';
    END IF;

    SELECT row.id, row.input_hash INTO candidate_set_id, stored_hash
      FROM public.candidate_sets row
     WHERE row.idempotency_key = p_bundle->>'idempotency_key';
    IF candidate_set_id IS NOT NULL THEN
        IF stored_hash IS DISTINCT FROM p_bundle->>'input_hash'
           OR NOT EXISTS (
                SELECT 1 FROM public.candidate_sets row
                 WHERE row.id = candidate_set_id
                   AND row.owner_principal_id = p_acquisition_principal_id
                   AND row.project_id = p_project_id
                   AND row.take_id = p_take_id
                   AND row.manager_rules_version =
                       'take-feedback-policy-v3-serving-v1'
           ) THEN
            RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_CANDIDATE_REPLAY_CONFLICT';
        END IF;
        RETURN jsonb_build_object(
            'candidate_set_id', candidate_set_id,
            'candidate_count', (
                SELECT count(*) FROM public.feedback_candidates row
                 WHERE row.candidate_set_id = candidate_set_id
            ),
            'selected_count', (
                SELECT count(*) FROM public.feedback_exposures row
                 WHERE row.candidate_set_id = candidate_set_id
                   AND row.is_selected
            ),
            'replayed', true
        );
    END IF;

    transcript_id := (transcript->>'id')::UUID;
    INSERT INTO public.transcript_versions (
        id, owner_principal_id, project_id, take_id, version, source_kind,
        transcript_text, transcript_hash, input_hash, model_version,
        prompt_version, code_commit
    ) VALUES (
        transcript_id, p_acquisition_principal_id, p_project_id, p_take_id,
        (transcript->>'version')::INTEGER, transcript->>'source_kind',
        transcript->>'text', transcript->>'transcript_hash',
        transcript->>'input_hash', NULLIF(transcript->>'model_version', ''),
        NULLIF(transcript->>'prompt_version', ''), p_bundle->>'code_commit'
    ) ON CONFLICT (take_id, version) DO NOTHING;
    SELECT row.id, row.transcript_hash INTO transcript_id, stored_hash
      FROM public.transcript_versions row
     WHERE row.take_id = p_take_id
       AND row.version = (transcript->>'version')::INTEGER;
    IF transcript_id IS NULL
       OR stored_hash IS DISTINCT FROM transcript->>'transcript_hash' THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_TRANSCRIPT_CONFLICT';
    END IF;

    FOR slide_value IN SELECT value FROM jsonb_array_elements(
        COALESCE(transcript->'slides', '[]'::JSONB)
    ) LOOP
        INSERT INTO public.slides (
            id, owner_principal_id, project_id, take_id,
            transcript_version_id, slide_index, title, source_payload
        ) VALUES (
            (slide_value->>'id')::UUID, p_acquisition_principal_id,
            p_project_id, p_take_id, transcript_id,
            (slide_value->>'slide_index')::INTEGER,
            NULLIF(slide_value->>'title', ''),
            COALESCE(slide_value->'source_payload', '{}'::JSONB)
        ) ON CONFLICT (transcript_version_id, slide_index) DO NOTHING;
    END LOOP;
    FOR paragraph_value IN SELECT value FROM jsonb_array_elements(
        COALESCE(transcript->'paragraphs', '[]'::JSONB)
    ) LOOP
        slide_id := NULL;
        IF NULLIF(paragraph_value->>'slide_index', '') IS NOT NULL THEN
            SELECT row.id INTO slide_id FROM public.slides row
             WHERE row.transcript_version_id = transcript_id
               AND row.slide_index =
                   (paragraph_value->>'slide_index')::INTEGER;
        END IF;
        INSERT INTO public.paragraphs (
            id, owner_principal_id, project_id, take_id,
            transcript_version_id, slide_id, paragraph_index,
            source_ideal_part_id, paragraph_text, start_char, end_char
        ) VALUES (
            (paragraph_value->>'id')::UUID, p_acquisition_principal_id,
            p_project_id, p_take_id, transcript_id, slide_id,
            (paragraph_value->>'paragraph_index')::INTEGER,
            NULLIF(paragraph_value->>'source_ideal_part_id', '')::UUID,
            paragraph_value->>'text',
            (paragraph_value->>'start_char')::INTEGER,
            (paragraph_value->>'end_char')::INTEGER
        ) ON CONFLICT (transcript_version_id, paragraph_index) DO NOTHING;
    END LOOP;

    candidate_set_id := (p_bundle->>'candidate_set_id')::UUID;
    INSERT INTO public.candidate_sets (
        id, owner_principal_id, project_id, take_id, taxonomy_version,
        selector_version, manager_rules_version, threshold_version,
        model_version, prompt_version, feature_schema_version,
        speaker_baseline_version, experiment_assignment, input_hash,
        idempotency_key, code_commit
    ) VALUES (
        candidate_set_id, p_acquisition_principal_id, p_project_id, p_take_id,
        versions->>'taxonomy_version', versions->>'selector_version',
        versions->>'manager_rules_version', versions->>'threshold_version',
        NULLIF(versions->>'model_version', ''),
        NULLIF(versions->>'prompt_version', ''),
        NULLIF(versions->>'feature_schema_version', ''),
        NULLIF(versions->>'speaker_baseline_version', ''),
        COALESCE(p_bundle->'experiment_assignment', '{}'::JSONB),
        p_bundle->>'input_hash', p_bundle->>'idempotency_key',
        p_bundle->>'code_commit'
    );

    FOR candidate_value IN
        SELECT value FROM jsonb_array_elements(candidate_rows)
    LOOP
        evidence := candidate_value->'evidence';
        IF COALESCE(candidate_value->>'candidate_key', '') = ''
           OR jsonb_typeof(evidence) <> 'object'
           OR evidence->>'recording_id' <> take_row.recording_1_id::TEXT
           OR NULLIF(evidence->>'legacy_piece_id', '') IS NULL
           OR NOT EXISTS (
                SELECT 1
                  FROM public.snippets source_snippet
                 WHERE source_snippet.id =
                       (evidence->>'legacy_piece_id')::UUID
                   AND source_snippet.session_id = p_take_id
                   AND source_snippet.recording_id = take_row.recording_1_id
                   AND source_snippet.start_offset_ms >= 0
                   AND source_snippet.duration_ms > 0
                   AND (
                       NULLIF(evidence->>'start_ms', '') IS NULL
                       OR source_snippet.start_offset_ms =
                          (evidence->>'start_ms')::INTEGER
                   )
                   AND (
                       NULLIF(evidence->>'end_ms', '') IS NULL
                       OR source_snippet.start_offset_ms +
                          source_snippet.duration_ms =
                          (evidence->>'end_ms')::INTEGER
                   )
           )
        THEN
            RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_CANDIDATE_INVALID';
        END IF;
        slide_id := NULL;
        paragraph_id := NULL;
        IF NULLIF(evidence->>'slide_index', '') IS NOT NULL THEN
            SELECT row.id INTO slide_id FROM public.slides row
             WHERE row.transcript_version_id = transcript_id
               AND row.slide_index = (evidence->>'slide_index')::INTEGER;
        END IF;
        IF NULLIF(evidence->>'paragraph_index', '') IS NOT NULL THEN
            SELECT row.id INTO paragraph_id FROM public.paragraphs row
             WHERE row.transcript_version_id = transcript_id
               AND row.paragraph_index =
                   (evidence->>'paragraph_index')::INTEGER;
        END IF;
        evidence_id := (evidence->>'id')::UUID;
        INSERT INTO public.evidence_spans (
            id, owner_principal_id, project_id, take_id, recording_id,
            transcript_version_id, slide_id, paragraph_id, legacy_piece_id,
            evidence_kind, task_type, audio_ref, start_ms, end_ms,
            start_char, end_char, exact_text, replacement_text,
            target_locator, technical_metadata, evidence_hash, input_hash
        ) VALUES (
            evidence_id, p_acquisition_principal_id, p_project_id, p_take_id,
            take_row.recording_1_id, transcript_id, slide_id, paragraph_id,
            (evidence->>'legacy_piece_id')::UUID,
            evidence->>'evidence_kind', evidence->>'task_type',
            NULLIF(evidence->>'audio_ref', ''),
            NULLIF(evidence->>'start_ms', '')::INTEGER,
            NULLIF(evidence->>'end_ms', '')::INTEGER,
            NULLIF(evidence->>'start_char', '')::INTEGER,
            NULLIF(evidence->>'end_char', '')::INTEGER,
            NULLIF(evidence->>'exact_text', ''),
            NULLIF(evidence->>'replacement_text', ''),
            COALESCE(evidence->'target_locator', '{}'::JSONB),
            COALESCE(evidence->'technical_metadata', '{}'::JSONB),
            evidence->>'evidence_hash', evidence->>'input_hash'
        ) ON CONFLICT (evidence_hash) DO NOTHING;
        SELECT row.id INTO evidence_id FROM public.evidence_spans row
         WHERE row.evidence_hash = evidence->>'evidence_hash'
           AND row.owner_principal_id = p_acquisition_principal_id
           AND row.project_id = p_project_id
           AND row.take_id = p_take_id
           AND row.recording_id = take_row.recording_1_id
           AND row.legacy_piece_id = (evidence->>'legacy_piece_id')::UUID;
        IF evidence_id IS NULL THEN
            RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_EVIDENCE_CONFLICT';
        END IF;
        candidate_id := (candidate_value->>'id')::UUID;
        INSERT INTO public.feedback_candidates (
            id, candidate_set_id, evidence_span_id, feedback_family, lane,
            candidate_key, candidate_score, rank_evidence, generated_output,
            detector_version, rule_version, model_version, prompt_version,
            training_eligible, ineligibility_reason
        ) VALUES (
            candidate_id, candidate_set_id, evidence_id,
            candidate_value->>'feedback_family', candidate_value->>'lane',
            candidate_value->>'candidate_key',
            NULLIF(candidate_value->>'candidate_score', '')::DOUBLE PRECISION,
            COALESCE(candidate_value->'rank_evidence', '{}'::JSONB),
            COALESCE(candidate_value->'generated_output', '{}'::JSONB),
            NULLIF(candidate_value->>'detector_version', ''),
            NULLIF(candidate_value->>'rule_version', ''),
            NULLIF(candidate_value->>'model_version', ''),
            NULLIF(candidate_value->>'prompt_version', ''), false,
            'service_product_evidence_only'
        );
        selected_position := NULL;
        SELECT ordinal::INTEGER INTO selected_position
          FROM jsonb_array_elements(selected_keys) WITH ORDINALITY
               AS chosen(value, ordinal)
         WHERE chosen.value->>'id' = candidate_value->>'candidate_key'
           AND chosen.value->>'feedback_family' =
               candidate_value->>'feedback_family'
         LIMIT 1;
        INSERT INTO public.feedback_exposures (
            id, candidate_set_id, candidate_id, feedback_family, lane,
            is_selected, position_shown, shown_at, selector_version,
            manager_rules_version, threshold_version, model_version,
            prompt_version, experiment_assignment, input_hash
        ) VALUES (
            (candidate_value->>'exposure_id')::UUID, candidate_set_id,
            candidate_id, candidate_value->>'feedback_family',
            candidate_value->>'lane', selected_position IS NOT NULL,
            selected_position, NULL, versions->>'selector_version',
            versions->>'manager_rules_version', versions->>'threshold_version',
            NULLIF(versions->>'model_version', ''),
            NULLIF(versions->>'prompt_version', ''),
            COALESCE(p_bundle->'experiment_assignment', '{}'::JSONB),
            p_bundle->>'input_hash'
        );
    END LOOP;
    SELECT count(*) INTO candidate_count
      FROM public.feedback_candidates row
     WHERE row.candidate_set_id = candidate_set_id;
    SELECT count(*) INTO selected_count
      FROM public.feedback_exposures row
     WHERE row.candidate_set_id = candidate_set_id AND row.is_selected;
    IF candidate_count <> jsonb_array_length(candidate_rows)
       OR selected_count <> jsonb_array_length(selected_keys)
    THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_LEDGER_INCOMPLETE';
    END IF;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    RETURN jsonb_build_object(
        'candidate_set_id', candidate_set_id,
        'candidate_count', candidate_count,
        'selected_count', selected_count,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.freeze_feedback_v3_service_membership_v1(
    p_acquisition_principal_id UUID,
    p_project_id UUID,
    p_take_id UUID,
    p_candidate_set_id UUID,
    p_document_snapshot_id UUID,
    p_block_partition_version TEXT,
    p_items JSONB,
    p_idempotency_key TEXT
) RETURNS public.feedback_v3_memberships
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    take_row public.v2_sessions;
    candidate_set public.candidate_sets;
    snapshot public.ideal_text_document_snapshots;
    result public.feedback_v3_memberships;
    item JSONB;
    candidate public.feedback_candidates;
    evidence public.evidence_spans;
    snippet public.snippets;
    part JSONB;
    piece JSONB;
    content_hash TEXT;
    item_count INTEGER;
    selected_count INTEGER;
    derived_membership_hash TEXT;
BEGIN
    IF jsonb_typeof(p_items) <> 'array'
       OR COALESCE(btrim(p_block_partition_version), '') = ''
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_MEMBERSHIP_INVALID';
    END IF;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT * INTO STRICT take_row
      FROM public.v2_sessions
     WHERE id = p_take_id
       AND project_id = p_project_id
       AND owner_principal_id = p_acquisition_principal_id
       AND COALESCE(recording_kind, 'spoken') = 'spoken'
       AND paired_session_id IS NULL;
    SELECT * INTO STRICT candidate_set
      FROM public.candidate_sets
     WHERE id = p_candidate_set_id
       AND take_id = p_take_id
       AND project_id = p_project_id
       AND owner_principal_id = p_acquisition_principal_id
       AND manager_rules_version LIKE 'take-feedback-policy-v3%';
    SELECT * INTO STRICT snapshot
      FROM public.ideal_text_document_snapshots
     WHERE id = p_document_snapshot_id
       AND project_id = p_project_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND source_take_session_id = p_take_id;
    IF NOT EXISTS (
        SELECT 1
          FROM public.ideal_text_document_heads head
          JOIN public.ideal_text_document_generations generation
            ON generation.arc_id = head.arc_id
         WHERE head.snapshot_id = snapshot.id
           AND generation.generation = snapshot.source_generation
    ) THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_DOCUMENT_STALE';
    END IF;
    content_hash := public.feedback_v3_content_identity_v1(snapshot.payload);
    item_count := jsonb_array_length(p_items);
    IF item_count <> (
        SELECT count(*) FROM public.feedback_candidates row
         WHERE row.candidate_set_id = candidate_set.id
    ) OR item_count <> (
        SELECT count(DISTINCT value->>'candidate_id')
          FROM jsonb_array_elements(p_items) value
    ) THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_INVENTORY_INCOMPLETE';
    END IF;
    SELECT count(*) INTO selected_count
      FROM jsonb_array_elements(p_items) value
     WHERE COALESCE((value->>'selected')::boolean, false);
    derived_membership_hash := public.exercise_json_sha256_v1(
        jsonb_build_object(
            'acquisition_principal_id', p_acquisition_principal_id,
            'project_id', p_project_id,
            'take_id', p_take_id,
            'candidate_set_id', p_candidate_set_id,
            'document_snapshot_id', p_document_snapshot_id,
            'document_snapshot_sha256', snapshot.payload_sha256,
            'content_identity_sha256', content_hash,
            'policy_version', 'take-feedback-policy-v3-serving-v1',
            'block_partition_version', p_block_partition_version,
            'operation_mode', 'allowlisted_service',
            'service_contract_version', 'mlc3-first-client-service-v1',
            'items', p_items
        )
    );
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'feedback-v3-service-membership:' || p_idempotency_key, 0
    ));
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.ideal_text_document_heads head
         WHERE head.snapshot_id = snapshot.id
    ) OR NOT EXISTS (
        SELECT 1
          FROM public.processing_recording_attempts attempt
          JOIN public.processing_audio_objects object_row
            ON object_row.recording_attempt_id = attempt.id
           AND object_row.acquisition_principal_id =
               p_acquisition_principal_id
           AND object_row.deleted_at IS NULL
         WHERE attempt.id = take_row.id
           AND attempt.acquisition_principal_id = p_acquisition_principal_id
           AND attempt.project_id = p_project_id
           AND attempt.recording_id = take_row.recording_1_id
    ) THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_SOURCE_STALE';
    END IF;
    SELECT * INTO result
      FROM public.feedback_v3_memberships
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.acquisition_principal_id <> p_acquisition_principal_id
           OR result.candidate_set_id <> p_candidate_set_id
           OR result.document_snapshot_id <> p_document_snapshot_id
           OR result.membership_sha256 <> derived_membership_hash
           OR result.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_MEMBERSHIP_REPLAY_CONFLICT';
        END IF;
        RETURN public.require_feedback_v3_service_membership_live_v1(
            result.id, p_acquisition_principal_id
        );
    END IF;
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.feedback_v3_memberships (
        acquisition_principal_id, project_id, take_id, candidate_set_id,
        document_snapshot_id, document_snapshot_sha256,
        content_identity_sha256, policy_version, block_partition_version,
        take_index, item_count, selected_count, membership_sha256,
        idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_project_id, p_take_id,
        p_candidate_set_id, snapshot.id, snapshot.payload_sha256, content_hash,
        'take-feedback-policy-v3-serving-v1', p_block_partition_version,
        take_row.take_index, item_count, selected_count,
        derived_membership_hash, p_idempotency_key
    ) RETURNING * INTO result;
    FOR item IN SELECT value FROM jsonb_array_elements(p_items) LOOP
        SELECT * INTO STRICT candidate
          FROM public.feedback_candidates row
         WHERE row.id = (item->>'candidate_id')::UUID
           AND row.candidate_set_id = candidate_set.id
           AND row.candidate_key = item->>'candidate_key'
           AND row.feedback_family = item->>'feedback_family';
        SELECT * INTO STRICT evidence
          FROM public.evidence_spans row
         WHERE row.id = candidate.evidence_span_id
           AND row.take_id = p_take_id
           AND row.project_id = p_project_id
           AND row.owner_principal_id = p_acquisition_principal_id
           AND row.recording_id = take_row.recording_1_id;
        SELECT * INTO STRICT snippet
          FROM public.snippets row
         WHERE row.id = evidence.legacy_piece_id
           AND row.session_id = p_take_id
           AND row.recording_id = take_row.recording_1_id
           AND row.start_offset_ms = evidence.start_ms
           AND row.duration_ms = evidence.end_ms - evidence.start_ms
           AND row.start_offset_ms >= 0
           AND row.duration_ms > 0;
        SELECT value INTO part
          FROM jsonb_array_elements(snapshot.payload->'parts') value
         WHERE value->>'id' = item->>'source_ideal_part_id' LIMIT 1;
        SELECT value INTO piece
          FROM jsonb_array_elements(snapshot.payload->'pieces') value
         WHERE value->>'part_id' = item->>'source_ideal_part_id' LIMIT 1;
        IF part IS NULL OR piece IS NULL
           OR (piece->>'slide_index')::INTEGER <>
              (item->>'slide_index')::INTEGER
           OR item->>'eligibility' NOT IN ('eligible', 'excluded')
           OR (COALESCE((item->>'selected')::boolean, false)
               AND item->>'eligibility' <> 'eligible')
        THEN
            RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_ITEM_LINEAGE_INVALID';
        END IF;
        INSERT INTO public.feedback_v3_membership_items (
            membership_id, acquisition_principal_id, candidate_id,
            evidence_span_id, candidate_key, feedback_family, slide_index,
            block_key, source_ideal_part_id, snippet_id, eligibility,
            exclusion_reason, selected, position_shown, item_sha256
        ) VALUES (
            result.id, p_acquisition_principal_id, candidate.id, evidence.id,
            candidate.candidate_key, candidate.feedback_family,
            (item->>'slide_index')::INTEGER,
            (item->>'block_key')::INTEGER,
            (item->>'source_ideal_part_id')::UUID,
            snippet.id, item->>'eligibility',
            NULLIF(item->>'exclusion_reason', ''),
            COALESCE((item->>'selected')::boolean, false),
            NULLIF(item->>'position_shown', '')::INTEGER,
            public.exercise_json_sha256_v1(item)
        );
    END LOOP;
    SET CONSTRAINTS feedback_v3_membership_complete IMMEDIATE;
    RETURN public.require_feedback_v3_service_membership_live_v1(
        result.id, p_acquisition_principal_id
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.ack_feedback_v3_service_render_v1(
    p_acquisition_principal_id UUID,
    p_owner_user_id UUID,
    p_membership_id UUID,
    p_candidate_id UUID,
    p_feedback_exposure_id UUID,
    p_render_instance_id UUID,
    p_content_identity_sha256 TEXT,
    p_rendered_at TIMESTAMPTZ,
    p_client_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.feedback_v3_service_render_receipts
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    membership public.feedback_v3_memberships;
    item public.feedback_v3_membership_items;
    exposed public.feedback_exposures;
    result public.feedback_v3_service_render_receipts;
    derived_hash TEXT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = ''
       OR COALESCE(btrim(p_client_version), '') = ''
       OR p_content_identity_sha256 !~ '^[0-9a-f]{64}$'
       OR p_rendered_at > clock_timestamp() + interval '5 minutes'
    THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_RENDER_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'feedback-v3-service-render:' || p_idempotency_key, 0
    ));
    membership := public.require_feedback_v3_service_membership_live_v1(
        p_membership_id, p_acquisition_principal_id
    );
    IF membership.content_identity_sha256 <> p_content_identity_sha256
       OR NOT EXISTS (
           SELECT 1 FROM public.owner_principals owner
            WHERE owner.id = p_acquisition_principal_id
              AND owner.user_id = p_owner_user_id
       ) THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_RENDER_LINEAGE_INVALID';
    END IF;
    SELECT * INTO STRICT item
      FROM public.feedback_v3_membership_items row
     WHERE row.membership_id = membership.id
       AND row.candidate_id = p_candidate_id
       AND row.selected AND row.eligibility = 'eligible';
    SELECT * INTO STRICT exposed
      FROM public.feedback_exposures row
     WHERE row.id = p_feedback_exposure_id
       AND row.candidate_set_id = membership.candidate_set_id
       AND row.candidate_id = item.candidate_id
       AND row.feedback_family = item.feedback_family
       AND row.is_selected
       AND row.position_shown = item.position_shown;
    derived_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-first-client-service-v1',
        'acquisition_principal_id', p_acquisition_principal_id,
        'owner_user_id', p_owner_user_id,
        'membership_id', membership.id,
        'candidate_id', item.candidate_id,
        'feedback_exposure_id', exposed.id,
        'render_instance_id', p_render_instance_id,
        'content_identity_sha256', p_content_identity_sha256,
        'rendered_at', p_rendered_at,
        'client_version', p_client_version
    ));
    SELECT * INTO result
      FROM public.feedback_v3_service_render_receipts row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.receipt_sha256 <> derived_hash THEN
            RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_RENDER_REPLAY_CONFLICT';
        END IF;
        IF exposed.shown_at IS NULL THEN
            RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_RENDER_STATE_INVALID';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.feedback_v3_service_render_receipts (
        acquisition_principal_id, owner_user_id, membership_id, candidate_id,
        feedback_exposure_id, render_instance_id, content_identity_sha256,
        rendered_at, client_version, receipt_sha256, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_owner_user_id, membership.id,
        item.candidate_id, exposed.id, p_render_instance_id,
        p_content_identity_sha256, p_rendered_at, p_client_version,
        derived_hash, p_idempotency_key
    ) RETURNING * INTO result;
    PERFORM set_config(
        'willab.feedback_exposure_render_transition', 'on', true
    );
    UPDATE public.feedback_exposures row
       SET shown_at = p_rendered_at
     WHERE row.id = exposed.id
       AND row.candidate_id = item.candidate_id
       AND row.shown_at IS NULL;
    SELECT * INTO STRICT exposed
      FROM public.feedback_exposures row
     WHERE row.id = p_feedback_exposure_id
       AND row.candidate_id = item.candidate_id
       AND row.shown_at IS NOT NULL;
    PERFORM public.require_feedback_v3_service_membership_live_v1(
        membership.id, p_acquisition_principal_id
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_feedback_v3_service_response_v1(
    p_project_id UUID,
    p_take_id UUID,
    p_acquisition_principal_id UUID,
    p_owner_user_id UUID,
    p_feedback_membership_id UUID,
    p_candidate_id UUID,
    p_feedback_exposure_id UUID,
    p_render_receipt_id UUID,
    p_response TEXT,
    p_idempotency_key TEXT
) RETURNS public.feedback_v3_service_response_bindings
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    membership public.feedback_v3_memberships;
    membership_item public.feedback_v3_membership_items;
    exposure public.feedback_exposures;
    render_receipt public.feedback_v3_service_render_receipts;
    v3_response public.feedback_v3_owner_responses;
    normalized_value TEXT;
    decision_id UUID;
    binding_hash TEXT;
    result public.feedback_v3_service_response_bindings;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = ''
       OR p_response NOT IN (
           'confident_yes', 'confident_in_between', 'confident_no',
           'confident_not_sure', 'confident_audio_unclear'
       ) THEN
        RAISE EXCEPTION 'MLC3_SERVICE_RESPONSE_INVALID';
    END IF;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-response:' || p_idempotency_key, 0
    ));
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    membership := public.require_feedback_v3_service_membership_live_v1(
        p_feedback_membership_id, p_acquisition_principal_id
    );
    IF membership.acquisition_principal_id <> p_acquisition_principal_id
       OR membership.project_id <> p_project_id
       OR membership.take_id <> p_take_id
       OR NOT EXISTS (
           SELECT 1 FROM public.owner_principals owner
            WHERE owner.id = p_acquisition_principal_id
              AND owner.user_id = p_owner_user_id
       ) THEN
        RAISE EXCEPTION 'MLC3_SERVICE_RESPONSE_LINEAGE_INVALID';
    END IF;
    SELECT * INTO STRICT membership_item
      FROM public.feedback_v3_membership_items item
     WHERE item.membership_id = membership.id
       AND item.candidate_id = p_candidate_id
       AND item.feedback_family = 'confident_voice'
       AND item.eligibility = 'eligible'
       AND item.selected;
    SELECT * INTO STRICT exposure
      FROM public.feedback_exposures exposed
     WHERE exposed.id = p_feedback_exposure_id
       AND exposed.candidate_set_id = membership.candidate_set_id
       AND exposed.candidate_id = membership_item.candidate_id
       AND exposed.feedback_family = 'confident_voice'
       AND exposed.is_selected
       AND exposed.position_shown = membership_item.position_shown
       AND exposed.shown_at IS NOT NULL;
    SELECT * INTO STRICT render_receipt
      FROM public.feedback_v3_service_render_receipts receipt
     WHERE receipt.id = p_render_receipt_id
       AND receipt.acquisition_principal_id = p_acquisition_principal_id
       AND receipt.owner_user_id = p_owner_user_id
       AND receipt.membership_id = membership.id
       AND receipt.candidate_id = membership_item.candidate_id
       AND receipt.feedback_exposure_id = exposure.id;
    normalized_value := CASE p_response
        WHEN 'confident_yes' THEN 'yes'
        WHEN 'confident_in_between' THEN 'in_between'
        WHEN 'confident_no' THEN 'no'
        WHEN 'confident_not_sure' THEN 'not_sure'
        WHEN 'confident_audio_unclear' THEN 'audio_unclear'
    END;
    SELECT id INTO decision_id
      FROM public.confidence_self_reports report
     WHERE report.idempotency_key = p_idempotency_key || ':canonical';
    IF decision_id IS NULL THEN
        decision_id := gen_random_uuid();
        INSERT INTO public.confidence_self_reports (
            id, evidence_span_id, value, rater_id, taxonomy_version,
            idempotency_key
        ) VALUES (
            decision_id, membership_item.evidence_span_id, normalized_value,
            p_owner_user_id, 'confidence-owner-five-state-v1',
            p_idempotency_key || ':canonical'
        );
    ELSIF NOT EXISTS (
        SELECT 1 FROM public.confidence_self_reports report
         WHERE report.id = decision_id
           AND report.evidence_span_id = membership_item.evidence_span_id
           AND report.value = normalized_value
           AND report.rater_id = p_owner_user_id
           AND report.taxonomy_version = 'confidence-owner-five-state-v1'
    ) THEN
        RAISE EXCEPTION 'MLC3_SERVICE_RESPONSE_REPLAY_CONFLICT';
    END IF;
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.feedback_v3_owner_responses (
        membership_id, candidate_id, acquisition_principal_id,
        owner_user_id, response, response_taxonomy_version, idempotency_key
    ) VALUES (
        membership.id, membership_item.candidate_id,
        p_acquisition_principal_id, p_owner_user_id, p_response,
        'confidence-owner-five-state-v1', p_idempotency_key || ':v3'
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO STRICT v3_response
      FROM public.feedback_v3_owner_responses row
     WHERE row.idempotency_key = p_idempotency_key || ':v3'
       AND row.operation_mode = 'allowlisted_service';
    IF v3_response.membership_id <> membership.id
       OR v3_response.candidate_id <> membership_item.candidate_id
       OR v3_response.owner_user_id <> p_owner_user_id
       OR v3_response.response <> p_response
    THEN
        RAISE EXCEPTION 'MLC3_SERVICE_RESPONSE_REPLAY_CONFLICT';
    END IF;
    binding_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-first-client-service-v1',
        'acquisition_principal_id', p_acquisition_principal_id,
        'owner_user_id', p_owner_user_id,
        'membership_id', membership.id,
        'candidate_id', membership_item.candidate_id,
        'feedback_exposure_id', exposure.id,
        'render_receipt_id', render_receipt.id,
        'v3_owner_response_id', v3_response.id,
        'confidence_self_report_id', decision_id,
        'response', p_response,
        'response_taxonomy_version', 'confidence-owner-five-state-v1'
    ));
    SELECT * INTO result
      FROM public.feedback_v3_service_response_bindings
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.binding_sha256 <> binding_hash THEN
            RAISE EXCEPTION 'MLC3_SERVICE_RESPONSE_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.feedback_v3_service_response_bindings (
        acquisition_principal_id, owner_user_id, membership_id, candidate_id,
        feedback_exposure_id, render_receipt_id, v3_owner_response_id,
        confidence_self_report_id, response, response_taxonomy_version,
        binding_sha256, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, p_owner_user_id, membership.id,
        membership_item.candidate_id, exposure.id, render_receipt.id,
        v3_response.id, decision_id, p_response,
        'confidence-owner-five-state-v1', binding_hash, p_idempotency_key
    ) RETURNING * INTO result;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    PERFORM public.require_feedback_v3_service_membership_live_v1(
        p_feedback_membership_id, p_acquisition_principal_id
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_feedback_v3_service_response_v1(
    p_binding_id UUID,
    p_acquisition_principal_id UUID,
    p_membership_id UUID,
    p_candidate_id UUID,
    p_feedback_exposure_id UUID
) RETURNS public.feedback_v3_service_response_bindings
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE result public.feedback_v3_service_response_bindings;
BEGIN
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT * INTO STRICT result
      FROM public.feedback_v3_service_response_bindings binding
     WHERE binding.id = p_binding_id
       AND binding.acquisition_principal_id = p_acquisition_principal_id
       AND binding.membership_id = p_membership_id
       AND binding.candidate_id = p_candidate_id
       AND binding.feedback_exposure_id = p_feedback_exposure_id
       AND binding.response IN (
           'confident_yes', 'confident_in_between', 'confident_no',
           'confident_not_sure'
       );
    PERFORM public.require_feedback_v3_service_membership_live_v1(
        result.membership_id, p_acquisition_principal_id
    );
    RETURN result;
END;
$$;

DROP FUNCTION IF EXISTS public.freeze_exercise_service_offer_v2(
    UUID,UUID,UUID,TEXT
);
CREATE OR REPLACE FUNCTION public.freeze_exercise_service_offer_v2(
    p_acquisition_principal_id UUID,
    p_feedback_response_binding_id UUID,
    p_n1_candidate_set_id UUID,
    p_authorization_check_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_offers
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    response_binding public.feedback_v3_service_response_bindings;
    membership public.feedback_v3_memberships;
    feedback_item public.feedback_v3_membership_items;
    n1_snapshot public.exercise_n1_pattern_snapshots;
    candidate_set public.exercise_candidate_sets;
    lineage public.exercise_audio_lineages;
    existing public.exercise_service_offers;
    inventory JSONB;
    inventory_hash TEXT;
    offer_hash TEXT;
    chosen UUID;
    total_count INTEGER;
    eligible_count INTEGER;
    inventory_item RECORD;
    rank_index INTEGER := 0;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_KEY_REQUIRED';
    END IF;
    SELECT * INTO STRICT response_binding
      FROM public.feedback_v3_service_response_bindings row
     WHERE row.id = p_feedback_response_binding_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.response IN (
           'confident_yes', 'confident_in_between', 'confident_no',
           'confident_not_sure'
       );
    response_binding := public.require_feedback_v3_service_response_v1(
        response_binding.id,
        p_acquisition_principal_id,
        response_binding.membership_id,
        response_binding.candidate_id,
        response_binding.feedback_exposure_id
    );
    membership := public.require_feedback_v3_service_membership_live_v1(
        response_binding.membership_id,
        p_acquisition_principal_id
    );
    SELECT * INTO STRICT feedback_item
      FROM public.feedback_v3_membership_items row
     WHERE row.membership_id = membership.id
       AND row.candidate_id = response_binding.candidate_id
       AND row.feedback_family = 'confident_voice'
       AND row.selected AND row.eligibility = 'eligible';
    SELECT * INTO STRICT n1_snapshot
      FROM public.exercise_n1_pattern_snapshots row
     WHERE row.candidate_set_id = p_n1_candidate_set_id
       AND row.acquisition_principal_id = membership.acquisition_principal_id;
    SELECT * INTO STRICT candidate_set
      FROM public.exercise_candidate_sets row
     WHERE row.id = n1_snapshot.candidate_set_id
       AND row.acquisition_principal_id = membership.acquisition_principal_id;
    SELECT * INTO STRICT lineage
      FROM public.exercise_audio_lineages row
     WHERE row.id = candidate_set.audio_lineage_id
       AND row.acquisition_principal_id = membership.acquisition_principal_id
       AND row.take_id = membership.take_id
       AND row.snippet_id = feedback_item.snippet_id;
    IF candidate_set.source_candidate_id <> feedback_item.candidate_key
       OR feedback_item.evidence_span_id IS NULL
    THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_FEEDBACK_LINEAGE_INVALID';
    END IF;
    PERFORM public.require_exercise_service_current_authority_v1(
        p_authorization_check_id, membership.acquisition_principal_id
    );
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'exercise_version_id', source.exercise_version_id,
        'eligibility', CASE
            WHEN base.eligibility = 'eligible'
             AND source.compatibility_state = 'rankable'
            THEN 'eligible' ELSE 'excluded' END,
        'exclusion_reasons', CASE
            WHEN base.eligibility = 'eligible'
             AND source.compatibility_state = 'rankable'
            THEN '[]'::JSONB
            ELSE to_jsonb(CASE
                WHEN source.compatibility_state = 'excluded'
                THEN array_append(
                    base.exclusion_reasons, source.exclusion_reason
                ) ELSE base.exclusion_reasons END) END,
        'source_pattern', source.source_pattern,
        'supported_confidence_patterns',
            to_jsonb(source.supported_confidence_patterns),
        'pattern_distance', source.pattern_distance,
        'base_rank', base.deterministic_rank,
        'editorial_priority', COALESCE(profile.editorial_priority, 0)
    ) ORDER BY
        CASE WHEN base.eligibility = 'eligible'
              AND source.compatibility_state = 'rankable'
             THEN 0 ELSE 1 END,
        source.pattern_distance NULLS LAST,
        base.deterministic_rank NULLS LAST,
        COALESCE(profile.editorial_priority, 0) DESC,
        source.exercise_version_id), '[]'::JSONB)
      INTO inventory
      FROM public.exercise_n1_pattern_candidates source
      JOIN public.exercise_candidates base
        ON base.candidate_set_id = source.candidate_set_id
       AND base.exercise_version_id = source.exercise_version_id
      LEFT JOIN public.exercise_n1_version_compatibility_profiles profile
        ON profile.id = source.compatibility_profile_id
     WHERE source.candidate_set_id = n1_snapshot.candidate_set_id
       AND source.acquisition_principal_id =
           membership.acquisition_principal_id;
    total_count := jsonb_array_length(inventory);
    IF total_count <> n1_snapshot.candidate_count THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_INVENTORY_INCOMPLETE';
    END IF;
    SELECT count(*) INTO eligible_count
      FROM jsonb_array_elements(inventory) value
     WHERE value->>'eligibility' = 'eligible';
    SELECT (value->>'exercise_version_id')::UUID INTO chosen
      FROM jsonb_array_elements(inventory) value
     WHERE value->>'eligibility' = 'eligible'
     ORDER BY (value->>'pattern_distance')::INTEGER,
              COALESCE((value->>'base_rank')::INTEGER, 2147483647),
              COALESCE((value->>'editorial_priority')::INTEGER, 0) DESC,
              value->>'exercise_version_id'
     LIMIT 1;
    inventory_hash := public.exercise_json_sha256_v1(inventory);
    offer_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'service_contract_version', 'mlc3-first-client-service-v1',
        'acquisition_principal_id', membership.acquisition_principal_id,
        'project_id', membership.project_id,
        'source_take_id', membership.take_id,
        'source_audio_lineage_id', lineage.id,
        'feedback_membership_id', membership.id,
        'feedback_candidate_id', feedback_item.candidate_id,
        'feedback_response_binding_id', response_binding.id,
        'feedback_render_receipt_id', response_binding.render_receipt_id,
        'n1_candidate_set_id', n1_snapshot.candidate_set_id,
        'authorization_check_id', p_authorization_check_id,
        'selected_exercise_version_id', chosen,
        'candidate_count', total_count,
        'eligible_count', eligible_count,
        'inventory_sha256', inventory_hash,
        'matching_policy_version', 'exercise-proximity-service-v1'
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-allowlisted-service-offer:' || p_idempotency_key, 0
    ));
    response_binding := public.require_feedback_v3_service_response_v1(
        response_binding.id,
        response_binding.acquisition_principal_id,
        response_binding.membership_id,
        response_binding.candidate_id,
        response_binding.feedback_exposure_id
    );
    PERFORM public.require_exercise_service_current_authority_v1(
        p_authorization_check_id, membership.acquisition_principal_id
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_audio_objects object_row
         WHERE object_row.id = lineage.processing_audio_object_id
           AND object_row.acquisition_principal_id =
               membership.acquisition_principal_id
           AND object_row.deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_SOURCE_NOT_LIVE';
    END IF;
    SELECT * INTO existing
      FROM public.exercise_service_offers row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.offer_sha256 <> offer_hash
           OR existing.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.exercise_service_offers (
        acquisition_principal_id, project_id, source_take_id,
        source_audio_lineage_id, feedback_membership_id,
        feedback_candidate_id, n1_candidate_set_id, authorization_check_id,
        selected_exercise_version_id, outcome, candidate_count,
        eligible_count, inventory, inventory_sha256, matching_policy_version,
        offer_sha256, idempotency_key, feedback_response_binding_id,
        feedback_render_receipt_id
    ) VALUES (
        membership.acquisition_principal_id, membership.project_id,
        membership.take_id, lineage.id, membership.id,
        feedback_item.candidate_id, n1_snapshot.candidate_set_id,
        p_authorization_check_id, chosen,
        CASE WHEN chosen IS NULL THEN 'coach_exercise_requested'
             ELSE 'service_matched' END,
        total_count, eligible_count, inventory, inventory_hash,
        'exercise-proximity-service-v1', offer_hash, p_idempotency_key,
        response_binding.id, response_binding.render_receipt_id
    ) RETURNING * INTO existing;
    FOR inventory_item IN
        SELECT value FROM jsonb_array_elements(inventory)
    LOOP
        IF inventory_item.value->>'eligibility' = 'eligible' THEN
            rank_index := rank_index + 1;
        END IF;
        INSERT INTO public.exercise_service_offer_candidates (
            offer_id, acquisition_principal_id, exercise_version_id,
            eligibility, exclusion_reasons, source_pattern,
            supported_confidence_patterns, pattern_distance,
            deterministic_rank, candidate_sha256
        ) VALUES (
            existing.id, existing.acquisition_principal_id,
            (inventory_item.value->>'exercise_version_id')::UUID,
            inventory_item.value->>'eligibility', ARRAY(
                SELECT jsonb_array_elements_text(
                    inventory_item.value->'exclusion_reasons'
                )
            ), inventory_item.value->>'source_pattern', ARRAY(
                SELECT jsonb_array_elements_text(
                    inventory_item.value->'supported_confidence_patterns'
                )
            ), NULLIF(
                inventory_item.value->>'pattern_distance', ''
            )::INTEGER,
            CASE WHEN inventory_item.value->>'eligibility' = 'eligible'
                 THEN rank_index ELSE NULL END,
            public.exercise_json_sha256_v1(inventory_item.value)
        );
    END LOOP;
    INSERT INTO public.exercise_service_offer_events (
        offer_id, acquisition_principal_id, event_kind, event_payload,
        event_sha256, idempotency_key, occurred_at
    ) VALUES (
        existing.id, existing.acquisition_principal_id,
        'assignment_prepared',
        jsonb_build_object('offer_sha256', existing.offer_sha256),
        public.exercise_json_sha256_v1(jsonb_build_object(
            'offer_id', existing.id,
            'event_kind', 'assignment_prepared',
            'operation_mode', 'allowlisted_service'
        )), p_idempotency_key || ':assignment-prepared', clock_timestamp()
    );
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.issue_exercise_service_authority_v1(
    p_acquisition_principal_id UUID,
    p_source_take_id UUID,
    p_source_recording_id UUID,
    p_operation_kind TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    receipt public.processing_authorization_receipts;
    policy public.processing_policy_versions;
    service_snapshot_id UUID;
    pooled_snapshot_id UUID;
    authority_hash TEXT;
    auth_check public.exercise_authorization_checks;
BEGIN
    IF p_operation_kind NOT IN (
        'catalog_assignment', 'practice_processing',
        'blind_review_preparation'
    ) OR COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'MLC3_SERVICE_AUTHORITY_REQUEST_INVALID';
    END IF;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT receipt_row.*
      INTO receipt
      FROM public.processing_authorization_receipts receipt_row
      JOIN public.processing_policy_versions policy_row
        ON policy_row.id = receipt_row.policy_id
     WHERE receipt_row.acquisition_principal_id = p_acquisition_principal_id
       AND policy_row.status = 'active'
       AND policy_row.activated_at <= clock_timestamp()
       AND (policy_row.retired_at IS NULL
            OR policy_row.retired_at > clock_timestamp())
       AND EXISTS (
           SELECT 1
             FROM public.processing_authorization_receipt_purposes purpose
            WHERE purpose.receipt_id = receipt_row.id
              AND purpose.purpose_id =
                  'personalized_exercise_recommendation'
       )
       AND EXISTS (
           SELECT 1 FROM public.processing_policy_purposes purpose
            WHERE purpose.policy_id = policy_row.id
              AND purpose.purpose_id =
                  'personalized_exercise_recommendation'
       )
     ORDER BY receipt_row.accepted_at DESC, receipt_row.id DESC
     LIMIT 1;
    IF receipt.id IS NOT NULL THEN
        SELECT * INTO policy
          FROM public.processing_policy_versions row
         WHERE row.id = receipt.policy_id;
    END IF;
    IF receipt.id IS NULL OR policy.id IS NULL THEN
        RAISE EXCEPTION 'MLC3_SERVICE_AUTHORITY_REQUIRED';
    END IF;
    authority_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'mlc3-first-client-service-v1',
        'acquisition_principal_id', p_acquisition_principal_id,
        'receipt_id', receipt.id,
        'policy_id', policy.id,
        'purpose_id', 'personalized_exercise_recommendation',
        'operation_kind', p_operation_kind,
        'source_take_id', p_source_take_id,
        'source_recording_id', p_source_recording_id,
        'idempotency_key', p_idempotency_key
    ));
    SELECT snapshot.id INTO service_snapshot_id
      FROM public.processing_authorization_snapshots snapshot
     WHERE snapshot.authority_evidence_sha256 = authority_hash
       AND snapshot.acquisition_principal_id = p_acquisition_principal_id;
    IF service_snapshot_id IS NULL THEN
        INSERT INTO public.processing_authorization_snapshots (
            acquisition_principal_id, receipt_id, policy_id, purpose_id,
            operation_kind, source_take_id, source_recording_id,
            authority_evidence_sha256, pooled_learning_eligible,
            authority_checked_at
        ) VALUES (
            p_acquisition_principal_id, receipt.id, policy.id,
            'personalized_exercise_recommendation', p_operation_kind,
            p_source_take_id, p_source_recording_id, authority_hash, false,
            clock_timestamp()
        ) RETURNING id INTO service_snapshot_id;
    END IF;
    auth_check := public.record_exercise_authorization_check_v1(
        p_acquisition_principal_id, service_snapshot_id, p_operation_kind,
        p_idempotency_key || ':check'
    );
    IF NOT auth_check.authorized THEN
        RAISE EXCEPTION 'MLC3_SERVICE_AUTHORITY_REQUIRED';
    END IF;
    -- Pooled acquisition evidence may be frozen only before a new recording
    -- attempt exists.  Current authority checks for historical/source audio
    -- must never manufacture retroactive pooling provenance.
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_recording_attempts attempt
         WHERE attempt.recording_id = p_source_recording_id
    ) AND EXISTS (
        SELECT 1
          FROM public.processing_authorization_receipt_purposes purpose
         WHERE purpose.receipt_id = receipt.id
           AND purpose.purpose_id = 'pooled_model_improvement'
    ) AND EXISTS (
        SELECT 1 FROM public.processing_policy_purposes purpose
         WHERE purpose.policy_id = policy.id
           AND purpose.purpose_id = 'pooled_model_improvement'
    ) THEN
        authority_hash := public.exercise_json_sha256_v1(jsonb_build_object(
            'contract_version', 'mlc3-first-client-service-v1',
            'acquisition_principal_id', p_acquisition_principal_id,
            'receipt_id', receipt.id,
            'policy_id', policy.id,
            'purpose_id', 'pooled_model_improvement',
            'operation_kind', p_operation_kind,
            'source_take_id', p_source_take_id,
            'source_recording_id', p_source_recording_id,
            'idempotency_key', p_idempotency_key
        ));
        SELECT snapshot.id INTO pooled_snapshot_id
          FROM public.processing_authorization_snapshots snapshot
         WHERE snapshot.authority_evidence_sha256 = authority_hash
           AND snapshot.acquisition_principal_id = p_acquisition_principal_id;
        IF pooled_snapshot_id IS NULL THEN
            INSERT INTO public.processing_authorization_snapshots (
                acquisition_principal_id, receipt_id, policy_id, purpose_id,
                operation_kind, source_take_id, source_recording_id,
                authority_evidence_sha256, pooled_learning_eligible,
                authority_checked_at
            ) VALUES (
                p_acquisition_principal_id, receipt.id, policy.id,
                'pooled_model_improvement', p_operation_kind,
                p_source_take_id, p_source_recording_id,
                authority_hash, false, clock_timestamp()
            ) RETURNING id INTO pooled_snapshot_id;
        END IF;
    END IF;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    RETURN jsonb_build_object(
        'authorization_check_id', auth_check.id,
        'authorization_snapshot_id', service_snapshot_id,
        'pooled_authorization_snapshot_id', pooled_snapshot_id
    );
END;
$$;

-- A check stored on a service object is immutable acquisition evidence, not a
-- bearer permit for the full 24-hour service window.  Every service operation
-- derives a new current check from the historical check's exact source
-- identity and the principal's current receipt/policy state.  Callers invoke
-- this helper again after every potentially blocking lock and before replay
-- returns.
CREATE OR REPLACE FUNCTION public.require_exercise_service_current_authority_v1(
    p_historical_authorization_check_id UUID,
    p_acquisition_principal_id UUID
) RETURNS public.exercise_authorization_checks
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    historical public.exercise_authorization_checks;
    historical_snapshot public.processing_authorization_snapshots;
    current_authority JSONB;
    current_check public.exercise_authorization_checks;
    current_check_id UUID;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'MLC3_SERVICE_REQUIRES_READ_COMMITTED';
    END IF;
    SELECT check_row.* INTO STRICT historical
      FROM public.exercise_authorization_checks check_row
     WHERE check_row.id = p_historical_authorization_check_id
       AND check_row.acquisition_principal_id =
           p_acquisition_principal_id
       AND check_row.authorized
       AND check_row.purpose_id =
           'personalized_exercise_recommendation'
       AND check_row.operation_kind IN (
           'catalog_assignment', 'practice_processing',
           'blind_review_preparation'
       );
    SELECT snapshot.* INTO STRICT historical_snapshot
      FROM public.processing_authorization_snapshots snapshot
     WHERE snapshot.id = historical.authorization_snapshot_id
       AND snapshot.acquisition_principal_id =
           historical.acquisition_principal_id
       AND snapshot.purpose_id = historical.purpose_id;

    BEGIN
        current_authority := public.issue_exercise_service_authority_v1(
            historical.acquisition_principal_id,
            historical_snapshot.source_take_id,
            historical_snapshot.source_recording_id,
            historical.operation_kind,
            'mlc3-service-current:' || historical.id::TEXT || ':' ||
                gen_random_uuid()::TEXT
        );
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'MLC3_SERVICE_AUTHORITY_REQUIRED' THEN
            RAISE EXCEPTION 'EXERCISE_CURRENT_AUTHORIZATION_REVOKED';
        END IF;
        RAISE;
    END;
    current_check_id :=
        (current_authority->>'authorization_check_id')::UUID;
    SELECT * INTO STRICT current_check
      FROM public.exercise_authorization_checks check_row
     WHERE check_row.id = current_check_id
       AND check_row.acquisition_principal_id =
           historical.acquisition_principal_id
       AND check_row.operation_kind = historical.operation_kind
       AND check_row.authorized;
    IF historical.operation_kind = 'catalog_assignment' THEN
        PERFORM public.require_exercise_assignment_authority_v1(
            current_check.id, current_check.acquisition_principal_id
        );
    ELSIF historical.operation_kind = 'practice_processing' THEN
        PERFORM public.require_practice_processing_authority_v1(
            current_check.id, current_check.acquisition_principal_id
        );
    ELSE
        -- Blind-review checks share the same current purpose, receipt,
        -- policy, principal and service-block boundary.  The newly recorded
        -- check proves that state at this operation's serialization point.
        PERFORM public.require_current_exercise_authorization_v1(
            current_check.id, current_check.acquisition_principal_id,
            'blind_review_preparation'
        );
    END IF;
    RETURN current_check;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_exercise_service_offer_live_v1(
    p_offer_id UUID,
    p_acquisition_principal_id UUID
) RETURNS public.exercise_service_offers
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    offer public.exercise_service_offers;
    lineage public.exercise_audio_lineages;
    source_attempt public.processing_recording_attempts;
BEGIN
    SELECT * INTO STRICT offer
      FROM public.exercise_service_offers row
     WHERE row.id = p_offer_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.serves_user AND NOT row.dataset_eligible;
    SELECT * INTO STRICT lineage
      FROM public.exercise_audio_lineages row
     WHERE row.id = offer.source_audio_lineage_id
       AND row.acquisition_principal_id = offer.acquisition_principal_id
       AND row.project_id = offer.project_id
       AND row.take_id = offer.source_take_id;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-processing-audio-object:' ||
        lineage.processing_audio_object_id::TEXT, 0
    ));
    PERFORM public.require_exercise_service_current_authority_v1(
        offer.authorization_check_id, offer.acquisition_principal_id
    );
    SELECT * INTO STRICT source_attempt
      FROM public.processing_recording_attempts row
     WHERE row.id = lineage.recording_attempt_id
       AND row.acquisition_principal_id = offer.acquisition_principal_id
       AND row.project_id = offer.project_id
       AND row.recording_id = lineage.recording_id
       AND row.status NOT IN ('cancelled', 'purged');
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_audio_objects object_row
         WHERE object_row.id = lineage.processing_audio_object_id
           AND object_row.recording_attempt_id = source_attempt.id
           AND object_row.acquisition_principal_id =
               offer.acquisition_principal_id
           AND object_row.exact_bytes_sha256 = lineage.exact_audio_sha256
           AND object_row.deleted_at IS NULL
           AND NOT EXISTS (
               SELECT 1
                 FROM public.processing_audio_object_deletion_events deletion
                WHERE deletion.audio_object_id = object_row.id
           )
    ) THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_SOURCE_NOT_LIVE';
    END IF;
    PERFORM public.require_mlc3_service_principal_v1(
        offer.acquisition_principal_id
    );
    RETURN offer;
END;
$$;

-- Resolve the exact, already frozen N1 provenance needed by one V3 item.
-- This creates fresh service authority and source-acquisition evidence; it
-- never converts the historical dark assignment into a served assignment.
CREATE OR REPLACE FUNCTION public.prepare_feedback_v3_service_context_v1(
    p_membership_id UUID,
    p_candidate_id UUID,
    p_acquisition_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    membership public.feedback_v3_memberships;
    membership_item public.feedback_v3_membership_items;
    take_row public.v2_sessions;
    n1_snapshot public.exercise_n1_pattern_snapshots;
    candidate_set public.exercise_candidate_sets;
    lineage public.exercise_audio_lineages;
    source_attempt public.processing_recording_attempts;
    source_pooled_snapshot_id UUID;
    authority JSONB;
    receipt public.exercise_service_acquisition_receipts;
    feedback_exposure_id UUID;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_CONTEXT_KEY_REQUIRED';
    END IF;
    membership := public.require_feedback_v3_service_membership_live_v1(
        p_membership_id, p_acquisition_principal_id
    );
    SELECT * INTO STRICT membership_item
      FROM public.feedback_v3_membership_items row
     WHERE row.membership_id = membership.id
       AND row.candidate_id = p_candidate_id
       AND row.feedback_family = 'confident_voice'
       AND row.selected AND row.eligibility = 'eligible'
       AND row.operation_mode = 'allowlisted_service'
       AND row.serves_user AND NOT row.dataset_eligible;
    SELECT row.id INTO STRICT feedback_exposure_id
      FROM public.feedback_exposures row
     WHERE row.candidate_set_id = membership.candidate_set_id
       AND row.candidate_id = membership_item.candidate_id
       AND row.feedback_family = membership_item.feedback_family
       AND row.is_selected
       AND row.position_shown = membership_item.position_shown;
    SELECT * INTO STRICT take_row FROM public.v2_sessions row
     WHERE row.id = membership.take_id
       AND row.owner_principal_id = p_acquisition_principal_id
       AND row.project_id = membership.project_id;
    SELECT snapshot.*
      INTO n1_snapshot
      FROM public.exercise_n1_pattern_snapshots snapshot
      JOIN public.exercise_candidate_sets candidate
        ON candidate.id = snapshot.candidate_set_id
       AND candidate.acquisition_principal_id =
           snapshot.acquisition_principal_id
      JOIN public.exercise_audio_lineages source
        ON source.id = candidate.audio_lineage_id
       AND source.acquisition_principal_id =
           candidate.acquisition_principal_id
     WHERE snapshot.acquisition_principal_id =
           p_acquisition_principal_id
       AND source.take_id = membership.take_id
       AND source.recording_id = take_row.recording_1_id
       AND source.snippet_id = membership_item.snippet_id
       AND candidate.source_candidate_id = membership_item.candidate_key
       AND NOT snapshot.serves_user
       AND NOT snapshot.dataset_eligible
     ORDER BY candidate.assigned_at DESC, candidate.id DESC
     LIMIT 1;
    IF n1_snapshot.candidate_set_id IS NULL THEN
        RAISE EXCEPTION 'FEEDBACK_V3_SERVICE_N1_CONTEXT_NOT_READY';
    END IF;
    SELECT * INTO STRICT candidate_set
      FROM public.exercise_candidate_sets row
     WHERE row.id = n1_snapshot.candidate_set_id
       AND row.acquisition_principal_id = p_acquisition_principal_id;
    SELECT * INTO STRICT lineage
      FROM public.exercise_audio_lineages row
     WHERE row.id = candidate_set.audio_lineage_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.take_id = membership.take_id
       AND row.recording_id = take_row.recording_1_id
       AND row.snippet_id = membership_item.snippet_id;
    SELECT * INTO STRICT source_attempt
      FROM public.processing_recording_attempts row
     WHERE row.id = lineage.recording_attempt_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.project_id = membership.project_id
       AND row.recording_id = lineage.recording_id
       AND row.status NOT IN ('cancelled', 'purged');
    SELECT pooled.id INTO source_pooled_snapshot_id
      FROM public.processing_authorization_snapshots pooled
      JOIN public.processing_authorization_snapshots service
        ON service.id = source_attempt.authorization_snapshot_id
       AND pooled.receipt_id = service.receipt_id
       AND pooled.policy_id = service.policy_id
     WHERE pooled.acquisition_principal_id = p_acquisition_principal_id
       AND pooled.source_recording_id = source_attempt.recording_id
       AND pooled.purpose_id = 'pooled_model_improvement'
       AND pooled.created_at <= source_attempt.created_at
       AND pooled.authority_checked_at <= source_attempt.created_at
     ORDER BY pooled.created_at DESC, pooled.id DESC
     LIMIT 1;
    authority := public.issue_exercise_service_authority_v1(
        p_acquisition_principal_id, membership.take_id,
        take_row.recording_1_id, 'catalog_assignment',
        p_idempotency_key || ':authority'
    );
    receipt := public.record_exercise_service_acquisition_receipt_v1(
        p_acquisition_principal_id, 'source_recording',
        lineage.recording_attempt_id, lineage.processing_audio_object_id,
        source_attempt.authorization_snapshot_id,
        source_pooled_snapshot_id,
        p_idempotency_key || ':source-receipt'
    );
    PERFORM public.require_exercise_service_current_authority_v1(
        (authority->>'authorization_check_id')::UUID,
        p_acquisition_principal_id
    );
    membership := public.require_feedback_v3_service_membership_live_v1(
        membership.id, p_acquisition_principal_id
    );
    RETURN jsonb_build_object(
        'membership_id', membership.id,
        'candidate_id', membership_item.candidate_id,
        'feedback_exposure_id', feedback_exposure_id,
        'n1_candidate_set_id', n1_snapshot.candidate_set_id,
        'authorization_check_id', authority->>'authorization_check_id',
        'source_acquisition_receipt_id', receipt.id,
        'pooled_state_at_acquisition', receipt.pooled_state_at_acquisition,
        'future_release_state', receipt.future_release_state
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.require_exercise_practice_service_live_v1(
    p_session_id UUID,
    p_acquisition_principal_id UUID
) RETURNS public.exercise_practice_sessions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    practice public.exercise_practice_sessions;
    lineage public.exercise_audio_lineages;
    source_attempt public.processing_recording_attempts;
    source_object public.processing_audio_objects;
BEGIN
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT * INTO STRICT practice
      FROM public.exercise_practice_sessions row
     WHERE row.id = p_session_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.serves_user AND NOT row.dataset_eligible
       AND row.service_contract_version = 'mlc3-first-client-service-v1'
       AND row.service_identity_sha256 ~ '^[0-9a-f]{64}$'
       AND row.state IN ('open', 'completed')
       AND row.opens_at <= clock_timestamp()
       AND row.closes_at > clock_timestamp();
    SELECT * INTO STRICT lineage
      FROM public.exercise_audio_lineages row
     WHERE row.id = practice.source_audio_lineage_id
       AND row.acquisition_principal_id =
           practice.acquisition_principal_id
       AND row.project_id = practice.project_id
       AND row.take_id = practice.source_take_id;
    SELECT * INTO STRICT source_attempt
      FROM public.processing_recording_attempts row
     WHERE row.id = lineage.recording_attempt_id
       AND row.acquisition_principal_id =
           practice.acquisition_principal_id
       AND row.project_id = practice.project_id
       AND row.recording_id = lineage.recording_id
       AND row.status NOT IN ('cancelled', 'purged');
    SELECT * INTO STRICT source_object
      FROM public.processing_audio_objects row
     WHERE row.id = lineage.processing_audio_object_id
       AND row.recording_attempt_id = source_attempt.id
       AND row.acquisition_principal_id =
           practice.acquisition_principal_id
       AND row.exact_bytes_sha256 = lineage.exact_audio_sha256
       AND row.deleted_at IS NULL
       AND NOT EXISTS (
           SELECT 1
             FROM public.processing_audio_object_deletion_events deletion
            WHERE deletion.audio_object_id = row.id
       );
    IF EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id =
               practice.acquisition_principal_id
           AND purge.state <> 'done'
    ) THEN
        RAISE EXCEPTION 'PRACTICE_SOURCE_NOT_LIVE';
    END IF;
    PERFORM public.require_exercise_service_current_authority_v1(
        practice.authorization_check_id,
        practice.acquisition_principal_id
    );
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    RETURN practice;
END;
$$;

DROP FUNCTION IF EXISTS public.create_exercise_practice_service_session_v1(
    UUID,UUID,TEXT,TEXT,TIMESTAMPTZ,TIMESTAMPTZ,TEXT
);
CREATE OR REPLACE FUNCTION public.create_exercise_practice_service_session_v1(
    p_offer_id UUID,
    p_acquisition_principal_id UUID,
    p_source_acquisition_receipt_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_sessions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    offer public.exercise_service_offers;
    source_receipt public.exercise_service_acquisition_receipts;
    authority JSONB;
    result public.exercise_practice_sessions;
    source_evidence public.evidence_spans;
    exact_passage TEXT;
    opens_at TIMESTAMPTZ;
    closes_at TIMESTAMPTZ;
    session_window_version CONSTANT TEXT := 'practice-window-v1-24h';
    passage_hash TEXT;
    recipient_user_id UUID;
    source_content_identity_sha256 TEXT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_SESSION_INVALID';
    END IF;
    SELECT * INTO STRICT offer
     FROM public.exercise_service_offers row
     WHERE row.id = p_offer_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.outcome = 'service_matched'
       AND row.serves_user AND NOT row.dataset_eligible;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT evidence.* INTO STRICT source_evidence
      FROM public.feedback_candidates candidate
      JOIN public.evidence_spans evidence
        ON evidence.id = candidate.evidence_span_id
      JOIN public.feedback_v3_memberships membership
        ON membership.id = offer.feedback_membership_id
       AND membership.candidate_set_id = candidate.candidate_set_id
       AND membership.acquisition_principal_id = p_acquisition_principal_id
     WHERE candidate.id = offer.feedback_candidate_id
       AND evidence.owner_principal_id = p_acquisition_principal_id
       AND evidence.project_id = offer.project_id
       AND evidence.take_id = offer.source_take_id;
    exact_passage := btrim(source_evidence.exact_text);
    IF exact_passage = '' THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_PASSAGE_NOT_DERIVABLE';
    END IF;
    opens_at := clock_timestamp();
    closes_at := opens_at + INTERVAL '24 hours';
    SELECT * INTO STRICT source_receipt
      FROM public.exercise_service_acquisition_receipts row
     WHERE row.id = p_source_acquisition_receipt_id
       AND row.acquisition_principal_id = offer.acquisition_principal_id
       AND row.acquisition_kind = 'source_recording'
       AND row.processing_audio_object_id = (
           SELECT lineage.processing_audio_object_id
             FROM public.exercise_audio_lineages lineage
            WHERE lineage.id = offer.source_audio_lineage_id
       );
    SELECT owner.user_id, membership.content_identity_sha256
      INTO STRICT recipient_user_id, source_content_identity_sha256
      FROM public.owner_principals owner
      JOIN public.feedback_v3_memberships membership
        ON membership.id = offer.feedback_membership_id
       AND membership.acquisition_principal_id = owner.id
     WHERE owner.id = p_acquisition_principal_id
       AND owner.user_id IS NOT NULL;
    authority := public.issue_exercise_service_authority_v1(
        offer.acquisition_principal_id, offer.source_take_id,
        (SELECT attempt.recording_id
           FROM public.processing_recording_attempts attempt
          WHERE attempt.id = source_receipt.processing_recording_attempt_id),
        'practice_processing', p_idempotency_key || ':authority'
    );
    passage_hash := public.exercise_json_sha256_v1(to_jsonb(exact_passage));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-allowlisted-service-session:' || p_idempotency_key, 0
    ));
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT * INTO result
      FROM public.exercise_practice_sessions row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.source_offer_id <> offer.id
           OR result.source_acquisition_receipt_id <> source_receipt.id
           OR result.exact_passage_sha256 <> passage_hash
           OR result.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_SESSION_REPLAY_CONFLICT';
        END IF;
        RETURN public.require_exercise_practice_service_live_v1(
            result.id, result.acquisition_principal_id
        );
    END IF;
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.exercise_practice_sessions (
        acquisition_principal_id, project_id, source_take_id,
        source_audio_lineage_id, source_offer_id, exercise_version_id,
        authorization_check_id, exact_passage, exact_passage_sha256,
        session_window_version, opens_at, closes_at, idempotency_key,
        source_acquisition_receipt_id, measurement_extractor_version,
        measurement_feature_schema_version, validity_contract_version
    ) VALUES (
        offer.acquisition_principal_id, offer.project_id,
        offer.source_take_id, offer.source_audio_lineage_id, offer.id,
        offer.selected_exercise_version_id,
        (authority->>'authorization_check_id')::UUID,
        exact_passage, passage_hash, session_window_version,
        opens_at, closes_at, p_idempotency_key, source_receipt.id,
        'rushed-phrase-endings-n1-extractor-v1',
        'rushed-phrase-endings-n1-features-v1',
        'rushed-phrase-endings-n1-validity-v1'
    ) RETURNING * INTO result;
    INSERT INTO public.exercise_practice_events (
        session_id, acquisition_principal_id, event_kind, event_payload,
        occurred_at, event_sha256, idempotency_key,
        recipient_user_id, content_identity_sha256
    ) VALUES (
        result.id, result.acquisition_principal_id, 'assignment_prepared',
        jsonb_build_object(
            'session_sha256', result.service_identity_sha256,
            'source_offer_id', result.source_offer_id
        ), clock_timestamp(),
        public.exercise_json_sha256_v1(jsonb_build_object(
            'session_id', result.id,
            'event_kind', 'assignment_prepared',
            'operation_mode', 'allowlisted_service'
        )), p_idempotency_key || ':assignment-prepared',
        recipient_user_id, source_content_identity_sha256
    );
    RETURN public.require_exercise_practice_service_live_v1(
        result.id, result.acquisition_principal_id
    );
END;
$$;

DROP FUNCTION IF EXISTS public.reserve_exercise_practice_service_upload_v1(
    UUID, UUID, INTEGER, UUID, TEXT, BIGINT, TEXT, TEXT, TEXT, INTEGER
);
CREATE OR REPLACE FUNCTION public.reserve_exercise_practice_service_upload_v1(
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
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    practice public.exercise_practice_sessions;
    contract public.mlc3_service_contracts;
    authority JSONB;
    result public.exercise_practice_upload_recoveries;
    allocated_attempt_index INTEGER;
BEGIN
    IF p_intended_exact_bytes_sha256 !~ '^[0-9a-f]{64}$'
       OR p_byte_size < 1
       OR p_content_type NOT LIKE 'audio/%'
       OR COALESCE(btrim(p_object_key), '') = ''
       OR COALESCE(btrim(p_idempotency_key), '') = ''
       OR p_ttl_seconds NOT BETWEEN 30 AND 900
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_UPLOAD_RESERVATION_INVALID';
    END IF;
    practice := public.require_exercise_practice_service_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    contract := public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    IF p_object_key NOT LIKE (
        'mlc3-practice/' || p_acquisition_principal_id::TEXT || '/'
        || p_session_id::TEXT || '/%'
    ) THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_OBJECT_KEY_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-upload-session:' || p_session_id::TEXT, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-upload:' || p_idempotency_key, 0
    ));
    practice := public.require_exercise_practice_service_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    SELECT * INTO result
      FROM public.exercise_practice_upload_recoveries row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.session_id <> practice.id
           OR result.acquisition_principal_id <> p_acquisition_principal_id
           OR result.recording_id <> p_recording_id
           OR result.storage_provider <> 'r2'
           OR result.bucket <> contract.practice_bucket
           OR result.object_key <> p_object_key
           OR result.byte_size <> p_byte_size
           OR result.content_type <> p_content_type
           OR result.intended_exact_bytes_sha256 <>
              lower(p_intended_exact_bytes_sha256)
           OR result.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_UPLOAD_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    IF practice.state <> 'open' THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_SESSION_NOT_OPEN';
    END IF;
    SELECT COALESCE(max(row.attempt_index), 0) + 1
      INTO allocated_attempt_index
      FROM public.exercise_practice_upload_recoveries row
     WHERE row.session_id = practice.id;
    authority := public.issue_exercise_service_authority_v1(
        p_acquisition_principal_id, practice.source_take_id,
        p_recording_id, 'practice_processing',
        p_idempotency_key || ':authority'
    );
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.exercise_practice_upload_recoveries (
        session_id, acquisition_principal_id, attempt_index,
        storage_provider, bucket, object_key,
        intended_exact_bytes_sha256, status, idempotency_key,
        byte_size, content_type, expires_at, recording_id,
        authorization_snapshot_id, pooled_authorization_snapshot_id,
        authorization_check_id
    ) VALUES (
        practice.id, p_acquisition_principal_id, allocated_attempt_index,
        'r2', contract.practice_bucket, p_object_key,
        lower(p_intended_exact_bytes_sha256), 'write_started',
        p_idempotency_key, p_byte_size, p_content_type,
        clock_timestamp() + make_interval(secs => p_ttl_seconds),
        p_recording_id,
        (authority->>'authorization_snapshot_id')::UUID,
        NULLIF(authority->>'pooled_authorization_snapshot_id', '')::UUID,
        (authority->>'authorization_check_id')::UUID
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.ack_exercise_practice_service_upload_v1(
    p_recovery_id UUID,
    p_acquisition_principal_id UUID,
    p_exact_bytes_sha256 TEXT,
    p_byte_size BIGINT,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_upload_recoveries
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    result public.exercise_practice_upload_recoveries;
    verified_audio_object_id UUID;
BEGIN
    IF p_exact_bytes_sha256 !~ '^[0-9a-f]{64}$'
       OR p_byte_size < 1
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_UPLOAD_ACK_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-upload-recovery:' || p_recovery_id::TEXT, 0
    ));
    SELECT * INTO STRICT result
      FROM public.exercise_practice_upload_recoveries row
     WHERE row.id = p_recovery_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
     FOR UPDATE;
    PERFORM public.require_exercise_practice_service_live_v1(
        result.session_id, result.acquisition_principal_id
    );
    PERFORM public.require_exercise_service_current_authority_v1(
        result.authorization_check_id, result.acquisition_principal_id
    );
    IF result.intended_exact_bytes_sha256 <>
           lower(p_exact_bytes_sha256)
       OR result.byte_size <> p_byte_size
       OR result.status NOT IN (
           'write_started', 'write_acknowledged', 'attached'
       )
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_UPLOAD_ACK_MISMATCH';
    END IF;
    IF result.status = 'attached' THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'mlc3-processing-audio-object:' ||
            result.processing_audio_object_id::TEXT, 0
        ));
        IF NOT EXISTS (
            SELECT 1
              FROM public.processing_audio_objects object_row
             WHERE object_row.id = result.processing_audio_object_id
               AND object_row.acquisition_principal_id =
                   result.acquisition_principal_id
               AND object_row.bucket = result.bucket
               AND object_row.object_key = result.object_key
               AND object_row.byte_size = p_byte_size
               AND object_row.exact_bytes_sha256 =
                   lower(p_exact_bytes_sha256)
               AND object_row.deleted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1
                     FROM public.processing_audio_object_deletion_events deletion
                    WHERE deletion.audio_object_id = object_row.id
               )
        ) THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_UPLOAD_ACK_MISMATCH';
        END IF;
        PERFORM public.require_exercise_practice_service_live_v1(
            result.session_id, result.acquisition_principal_id
        );
        RETURN result;
    END IF;
    IF result.expires_at <= clock_timestamp() THEN
        -- An upload permit may expire after media finalization but before the
        -- HTTP response or downstream attempt attachment. Recover only when
        -- the exact verified immutable object already exists.
        SELECT object_row.id INTO verified_audio_object_id
          FROM public.processing_audio_objects object_row
         WHERE object_row.acquisition_principal_id =
                   result.acquisition_principal_id
           AND object_row.storage_provider = 'r2'
           AND object_row.bucket = result.bucket
           AND object_row.object_key = result.object_key
           AND object_row.byte_size = result.byte_size
           AND object_row.content_type = result.content_type
           AND object_row.exact_bytes_sha256 =
                   result.intended_exact_bytes_sha256
           AND object_row.deleted_at IS NULL
         LIMIT 1;
        IF result.status <> 'write_acknowledged'
           OR verified_audio_object_id IS NULL
        THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_UPLOAD_ACK_MISMATCH';
        END IF;
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'mlc3-processing-audio-object:' ||
            verified_audio_object_id::TEXT, 0
        ));
        IF NOT EXISTS (
            SELECT 1 FROM public.processing_audio_objects object_row
             WHERE object_row.id = verified_audio_object_id
               AND object_row.deleted_at IS NULL
               AND NOT EXISTS (
                   SELECT 1
                     FROM public.processing_audio_object_deletion_events deletion
                    WHERE deletion.audio_object_id = object_row.id
               )
        ) THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_UPLOAD_ACK_MISMATCH';
        END IF;
        PERFORM public.require_exercise_practice_service_live_v1(
            result.session_id, result.acquisition_principal_id
        );
        RETURN result;
    END IF;
    UPDATE public.exercise_practice_upload_recoveries
       SET status = 'write_acknowledged'
     WHERE id = result.id
     RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_exercise_practice_service_media_v1(
    p_recovery_id UUID,
    p_acquisition_principal_id UUID,
    p_processing_recording_attempt_id UUID,
    p_processing_audio_object_id UUID,
    p_verification_method TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    recovery public.exercise_practice_upload_recoveries;
    practice public.exercise_practice_sessions;
    receipt public.exercise_service_acquisition_receipts;
BEGIN
    IF p_verification_method <> 'read_after_write_sha256'
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_MEDIA_FINALIZATION_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-upload-recovery:' || p_recovery_id::TEXT, 0
    ));
    SELECT * INTO STRICT recovery
      FROM public.exercise_practice_upload_recoveries row
     WHERE row.id = p_recovery_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
     FOR UPDATE;
    practice := public.require_exercise_practice_service_live_v1(
        recovery.session_id, recovery.acquisition_principal_id
    );
    PERFORM public.require_exercise_service_current_authority_v1(
        recovery.authorization_check_id, recovery.acquisition_principal_id
    );
    IF recovery.status NOT IN ('write_acknowledged', 'attached')
       OR (recovery.status = 'write_acknowledged'
           AND recovery.expires_at <= clock_timestamp()
           AND NOT EXISTS (
               SELECT 1 FROM public.processing_audio_objects object_row
                WHERE object_row.id = p_processing_audio_object_id
                  AND object_row.acquisition_principal_id =
                      recovery.acquisition_principal_id
                  AND object_row.storage_provider = 'r2'
                  AND object_row.bucket = recovery.bucket
                  AND object_row.object_key = recovery.object_key
                  AND object_row.byte_size = recovery.byte_size
                  AND object_row.content_type = recovery.content_type
                  AND object_row.exact_bytes_sha256 =
                      recovery.intended_exact_bytes_sha256
                  AND object_row.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                        FROM public.processing_audio_object_deletion_events deletion
                       WHERE deletion.audio_object_id = object_row.id
                  )
           ))
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_MEDIA_NOT_ACKNOWLEDGED';
    END IF;
    INSERT INTO public.processing_recording_attempts (
        id, acquisition_principal_id, project_id, recording_id,
        upload_idempotency_key, authorization_snapshot_id, status
    ) VALUES (
        p_processing_recording_attempt_id,
        recovery.acquisition_principal_id, practice.project_id,
        recovery.recording_id, p_idempotency_key || ':recording',
        recovery.authorization_snapshot_id, 'accepted'
    ) ON CONFLICT (id) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_recording_attempts row
         WHERE row.id = p_processing_recording_attempt_id
           AND row.acquisition_principal_id = recovery.acquisition_principal_id
           AND row.project_id = practice.project_id
           AND row.recording_id = recovery.recording_id
           AND row.authorization_snapshot_id = recovery.authorization_snapshot_id
           AND row.status NOT IN ('cancelled', 'purged')
    ) THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_RECORDING_REPLAY_CONFLICT';
    END IF;
    INSERT INTO public.processing_audio_objects (
        id, acquisition_principal_id, recording_attempt_id,
        storage_provider, bucket, object_key, byte_size, content_type,
        exact_bytes_sha256, verified_at, verification_method
    ) VALUES (
        p_processing_audio_object_id, recovery.acquisition_principal_id,
        p_processing_recording_attempt_id, 'r2', recovery.bucket,
        recovery.object_key, recovery.byte_size, recovery.content_type,
        recovery.intended_exact_bytes_sha256, clock_timestamp(),
        p_verification_method
    ) ON CONFLICT (id) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_audio_objects row
         WHERE row.id = p_processing_audio_object_id
           AND row.acquisition_principal_id = recovery.acquisition_principal_id
           AND row.recording_attempt_id = p_processing_recording_attempt_id
           AND row.storage_provider = 'r2'
           AND row.bucket = recovery.bucket
           AND row.object_key = recovery.object_key
           AND row.byte_size = recovery.byte_size
           AND row.content_type = recovery.content_type
           AND row.exact_bytes_sha256 =
               recovery.intended_exact_bytes_sha256
           AND row.deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_AUDIO_REPLAY_CONFLICT';
    END IF;
    receipt := public.record_exercise_service_acquisition_receipt_v1(
        recovery.acquisition_principal_id, 'practice_recording',
        p_processing_recording_attempt_id, p_processing_audio_object_id,
        recovery.authorization_snapshot_id,
        recovery.pooled_authorization_snapshot_id,
        p_idempotency_key || ':acquisition'
    );
    RETURN jsonb_build_object(
        'recovery_id', recovery.id,
        'processing_recording_attempt_id', p_processing_recording_attempt_id,
        'processing_audio_object_id', p_processing_audio_object_id,
        'practice_acquisition_receipt_id', receipt.id,
        'exact_bytes_sha256', recovery.intended_exact_bytes_sha256
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.guard_exercise_practice_transcription_run_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    IF TG_OP = 'DELETE' OR
       current_setting('willab.practice_transcription_transition', true)
           IS DISTINCT FROM 'allowed'
    THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_RUN_IMMUTABLE';
    END IF;
    IF NOT (
           (OLD.status = 'authorized' AND NEW.status = 'dispatched')
           OR (
               OLD.status = 'dispatched'
               AND NEW.status IN (
                   'finalized', 'uncertain', 'failed',
                   'expired_after_dispatch', 'revoked_after_dispatch',
                   'outcome_uncommitted'
               )
           )
       )
       OR NEW.id <> OLD.id
       OR NEW.session_id <> OLD.session_id
       OR NEW.upload_recovery_id <> OLD.upload_recovery_id
       OR NEW.acquisition_principal_id <> OLD.acquisition_principal_id
       OR NEW.processing_recording_attempt_id <>
          OLD.processing_recording_attempt_id
       OR NEW.processing_audio_object_id <> OLD.processing_audio_object_id
       OR NEW.practice_acquisition_receipt_id <>
          OLD.practice_acquisition_receipt_id
       OR NEW.authorization_check_id <> OLD.authorization_check_id
       OR NEW.exact_audio_sha256 <> OLD.exact_audio_sha256
       OR NEW.provider <> OLD.provider
       OR NEW.model_version <> OLD.model_version
       OR NEW.prompt_version <> OLD.prompt_version
       OR NEW.language_policy_version <> OLD.language_policy_version
       OR NEW.language_hint IS DISTINCT FROM OLD.language_hint
       OR NEW.output_schema_version <> OLD.output_schema_version
       OR NEW.request_sha256 <> OLD.request_sha256
       OR NEW.permit_sha256 <> OLD.permit_sha256
       OR NEW.idempotency_key <> OLD.idempotency_key
       OR NEW.authorized_at <> OLD.authorized_at
       OR NEW.permit_expires_at <> OLD.permit_expires_at
       OR (
           OLD.status = 'dispatched'
           AND (
               NEW.dispatch_idempotency_key IS DISTINCT FROM
                   OLD.dispatch_idempotency_key
               OR NEW.dispatch_sha256 IS DISTINCT FROM OLD.dispatch_sha256
               OR NEW.dispatched_at IS DISTINCT FROM OLD.dispatched_at
           )
       )
       OR NEW.serves_user OR NEW.dataset_eligible
    THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_RUN_TRANSITION_INVALID';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS exercise_practice_transcription_runs_immutable
    ON public.exercise_practice_transcription_runs;
CREATE TRIGGER exercise_practice_transcription_runs_immutable
BEFORE UPDATE OR DELETE ON public.exercise_practice_transcription_runs
FOR EACH ROW EXECUTE FUNCTION
    public.guard_exercise_practice_transcription_run_v1();

CREATE OR REPLACE FUNCTION public.authorize_exercise_practice_transcription_v1(
    p_recovery_id UUID,
    p_acquisition_principal_id UUID,
    p_processing_recording_attempt_id UUID,
    p_processing_audio_object_id UUID,
    p_practice_acquisition_receipt_id UUID,
    p_provider TEXT,
    p_model_version TEXT,
    p_prompt_version TEXT,
    p_language_policy_version TEXT,
    p_language_hint TEXT,
    p_output_schema_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_transcription_runs
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    recovery public.exercise_practice_upload_recoveries;
    practice public.exercise_practice_sessions;
    processing_attempt public.processing_recording_attempts;
    audio_object public.processing_audio_objects;
    acquisition_receipt public.exercise_service_acquisition_receipts;
    result public.exercise_practice_transcription_runs;
    request_hash TEXT;
    permit_hash TEXT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_CONTRACT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-upload-recovery:' || p_recovery_id::TEXT, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-transcription:' || p_idempotency_key, 0
    ));
    SELECT * INTO STRICT recovery
      FROM public.exercise_practice_upload_recoveries row
     WHERE row.id = p_recovery_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.status IN ('write_acknowledged', 'attached')
     FOR UPDATE;
    practice := public.require_exercise_practice_service_live_v1(
        recovery.session_id, recovery.acquisition_principal_id
    );
    PERFORM public.require_exercise_service_current_authority_v1(
        recovery.authorization_check_id, recovery.acquisition_principal_id
    );
    SELECT * INTO STRICT processing_attempt
      FROM public.processing_recording_attempts row
     WHERE row.id = p_processing_recording_attempt_id
       AND row.acquisition_principal_id = recovery.acquisition_principal_id
       AND row.project_id = practice.project_id
       AND row.recording_id = recovery.recording_id
       AND row.authorization_snapshot_id = recovery.authorization_snapshot_id
       AND row.status NOT IN ('cancelled', 'purged');
    SELECT * INTO STRICT audio_object
      FROM public.processing_audio_objects row
     WHERE row.id = p_processing_audio_object_id
       AND row.recording_attempt_id = processing_attempt.id
       AND row.acquisition_principal_id = recovery.acquisition_principal_id
       AND row.storage_provider = 'r2'
       AND row.bucket = recovery.bucket
       AND row.object_key = recovery.object_key
       AND row.exact_bytes_sha256 = recovery.intended_exact_bytes_sha256
       AND row.deleted_at IS NULL;
    SELECT * INTO STRICT acquisition_receipt
      FROM public.exercise_service_acquisition_receipts row
     WHERE row.id = p_practice_acquisition_receipt_id
       AND row.acquisition_principal_id = recovery.acquisition_principal_id
       AND row.acquisition_kind = 'practice_recording'
       AND row.processing_recording_attempt_id = processing_attempt.id
       AND row.processing_audio_object_id = audio_object.id
       AND row.service_authorization_snapshot_id =
           recovery.authorization_snapshot_id;
    request_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'practice-transcription-run-v1',
        'session_id', practice.id,
        'upload_recovery_id', recovery.id,
        'acquisition_principal_id', recovery.acquisition_principal_id,
        'processing_recording_attempt_id', processing_attempt.id,
        'processing_audio_object_id', audio_object.id,
        'exact_audio_sha256', audio_object.exact_bytes_sha256,
        'provider', p_provider,
        'model_version', p_model_version,
        'prompt_version', p_prompt_version,
        'language_policy_version', p_language_policy_version,
        'language_hint', p_language_hint,
        'output_schema_version', p_output_schema_version
    ));
    permit_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'request_sha256', request_hash,
        'authorization_check_id', recovery.authorization_check_id,
        'authorization_snapshot_id', recovery.authorization_snapshot_id,
        'practice_acquisition_receipt_id', acquisition_receipt.id
    ));
    SELECT * INTO result
      FROM public.exercise_practice_transcription_runs row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.session_id <> practice.id
           OR result.upload_recovery_id <> recovery.id
           OR result.acquisition_principal_id <>
              recovery.acquisition_principal_id
           OR result.processing_recording_attempt_id <>
              processing_attempt.id
           OR result.processing_audio_object_id <> audio_object.id
           OR result.practice_acquisition_receipt_id <>
              acquisition_receipt.id
           OR result.authorization_check_id <>
              recovery.authorization_check_id
           OR result.request_sha256 <> request_hash
           OR result.permit_sha256 <> permit_hash
        THEN
            RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_REPLAY_CONFLICT';
        END IF;
        PERFORM public.require_exercise_service_current_authority_v1(
            recovery.authorization_check_id,
            recovery.acquisition_principal_id
        );
        RETURN result;
    END IF;
    IF p_provider <> 'openai'
       OR p_model_version <> 'whisper-1'
       OR p_prompt_version <> 'disfluent-preservation-v1'
       OR p_language_policy_version <> 'auto-detect-no-hint-v1'
       OR p_language_hint IS NOT NULL
       OR p_output_schema_version <>
          'whisper-verbose-word-timestamps-v1'
    THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_CONTRACT_INVALID';
    END IF;
    INSERT INTO public.exercise_practice_transcription_runs (
        session_id, upload_recovery_id, acquisition_principal_id,
        processing_recording_attempt_id, processing_audio_object_id,
        practice_acquisition_receipt_id, authorization_check_id,
        exact_audio_sha256, provider, model_version, prompt_version,
        language_policy_version, language_hint, output_schema_version,
        request_sha256, permit_sha256, status, idempotency_key,
        permit_expires_at
    ) VALUES (
        practice.id, recovery.id, recovery.acquisition_principal_id,
        processing_attempt.id, audio_object.id, acquisition_receipt.id,
        recovery.authorization_check_id, audio_object.exact_bytes_sha256,
        p_provider, p_model_version, p_prompt_version,
        p_language_policy_version, p_language_hint,
        p_output_schema_version, request_hash, permit_hash, 'authorized',
        p_idempotency_key, clock_timestamp() + INTERVAL '2 minutes'
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.mark_exercise_practice_transcription_dispatched_v1(
    p_run_id UUID,
    p_acquisition_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_transcription_runs
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    result public.exercise_practice_transcription_runs;
    dispatch_hash TEXT;
    audio_is_live BOOLEAN;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_DISPATCH_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-transcription-run:' || p_run_id::TEXT, 0
    ));
    SELECT * INTO STRICT result
      FROM public.exercise_practice_transcription_runs row
     WHERE row.id = p_run_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
     FOR UPDATE;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-processing-audio-object:' ||
        result.processing_audio_object_id::TEXT, 0
    ));
    audio_is_live := NOT EXISTS (
        SELECT 1
          FROM public.processing_audio_object_deletion_events deletion
         WHERE deletion.audio_object_id = result.processing_audio_object_id
    ) AND EXISTS (
        SELECT 1 FROM public.processing_audio_objects object_row
         WHERE object_row.id = result.processing_audio_object_id
           AND object_row.recording_attempt_id =
               result.processing_recording_attempt_id
           AND object_row.acquisition_principal_id =
               result.acquisition_principal_id
           AND object_row.exact_bytes_sha256 = result.exact_audio_sha256
           AND object_row.deleted_at IS NULL
    );
    IF NOT audio_is_live THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_AUDIO_NOT_LIVE';
    END IF;
    dispatch_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'contract_version', 'practice-transcription-dispatch-v1',
        'run_id', result.id,
        'request_sha256', result.request_sha256,
        'permit_sha256', result.permit_sha256,
        'idempotency_key', p_idempotency_key
    ));
    IF result.status <> 'authorized' THEN
        IF result.status <> 'dispatched'
           OR result.dispatch_idempotency_key <> p_idempotency_key
           OR result.dispatch_sha256 <> dispatch_hash
        THEN
            RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_DISPATCH_REPLAY_CONFLICT';
        END IF;
        PERFORM public.require_exercise_practice_service_live_v1(
            result.session_id, result.acquisition_principal_id
        );
        PERFORM public.require_exercise_service_current_authority_v1(
            result.authorization_check_id, result.acquisition_principal_id
        );
        IF clock_timestamp() > result.permit_expires_at THEN
            RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_PERMIT_EXPIRED';
        END IF;
        RETURN result;
    END IF;
    IF clock_timestamp() > result.permit_expires_at THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_PERMIT_EXPIRED';
    END IF;
    PERFORM public.require_exercise_practice_service_live_v1(
        result.session_id, result.acquisition_principal_id
    );
    PERFORM public.require_exercise_service_current_authority_v1(
        result.authorization_check_id, result.acquisition_principal_id
    );
    -- The durable dispatched state is committed before bytes leave the
    -- service.  It is therefore the reconciliation inventory if the process
    -- or terminal database write fails after the provider call.
    PERFORM set_config(
        'willab.practice_transcription_transition', 'allowed', true
    );
    UPDATE public.exercise_practice_transcription_runs
       SET status = 'dispatched',
           dispatch_idempotency_key = p_idempotency_key,
           dispatch_sha256 = dispatch_hash,
           dispatched_at = clock_timestamp()
     WHERE id = result.id
     RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_exercise_practice_transcription_v1(
    p_run_id UUID,
    p_acquisition_principal_id UUID,
    p_terminal_status TEXT,
    p_normalized_output JSONB,
    p_provider_error_code TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_transcription_runs
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    result public.exercise_practice_transcription_runs;
    recovery public.exercise_practice_upload_recoveries;
    response_hash TEXT;
    transcript_value TEXT;
    transcript_hash TEXT;
    transcript_state_value TEXT;
    final_hash TEXT;
    accepted_status TEXT;
    accepted_error_code TEXT;
    authority_is_live BOOLEAN := true;
    audio_is_live BOOLEAN;
BEGIN
    IF p_terminal_status NOT IN ('finalized', 'uncertain', 'failed')
       OR COALESCE(btrim(p_idempotency_key), '') = ''
       OR (p_terminal_status = 'finalized' AND (
           jsonb_typeof(p_normalized_output) <> 'object'
           OR jsonb_typeof(p_normalized_output->'words') <> 'array'
           OR p_provider_error_code IS NOT NULL
       ))
       OR (p_terminal_status IN ('uncertain', 'failed') AND (
           p_normalized_output IS NOT NULL
           OR COALESCE(btrim(p_provider_error_code), '') = ''
       ))
    THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_FINALIZATION_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-transcription-run:' || p_run_id::TEXT, 0
    ));
    SELECT * INTO STRICT result
      FROM public.exercise_practice_transcription_runs row
     WHERE row.id = p_run_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
     FOR UPDATE;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-processing-audio-object:' ||
        result.processing_audio_object_id::TEXT, 0
    ));
    audio_is_live := NOT EXISTS (
        SELECT 1
          FROM public.processing_audio_object_deletion_events deletion
         WHERE deletion.audio_object_id = result.processing_audio_object_id
    ) AND EXISTS (
        SELECT 1 FROM public.processing_audio_objects object_row
         WHERE object_row.id = result.processing_audio_object_id
           AND object_row.recording_attempt_id =
               result.processing_recording_attempt_id
           AND object_row.acquisition_principal_id =
               result.acquisition_principal_id
           AND object_row.exact_bytes_sha256 = result.exact_audio_sha256
           AND object_row.deleted_at IS NULL
    );
    IF result.status NOT IN ('authorized', 'dispatched') THEN
        IF result.finalization_idempotency_key <> p_idempotency_key THEN
            RAISE EXCEPTION
                'PRACTICE_TRANSCRIPTION_FINALIZATION_REPLAY_CONFLICT';
        END IF;
        -- Sanitized terminal rows contain no provider output; their exact
        -- retry key is sufficient to replay the immutable terminal fact.
        IF result.status IN (
            'expired_after_dispatch', 'revoked_after_dispatch',
            'outcome_uncommitted'
        ) THEN
            RETURN result;
        END IF;
        IF NOT audio_is_live THEN
            RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_AUDIO_NOT_LIVE';
        END IF;
        response_hash := CASE WHEN p_normalized_output IS NOT NULL
            THEN public.exercise_json_sha256_v1(p_normalized_output)
            ELSE NULL END;
        IF result.status <> p_terminal_status
           OR result.response_sha256 IS DISTINCT FROM response_hash
           OR result.provider_error_code IS DISTINCT FROM p_provider_error_code
        THEN
            RAISE EXCEPTION
                'PRACTICE_TRANSCRIPTION_FINALIZATION_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    IF result.status = 'authorized' THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_NOT_DISPATCHED';
    END IF;
    SELECT * INTO STRICT recovery
      FROM public.exercise_practice_upload_recoveries row
     WHERE row.id = result.upload_recovery_id
       AND row.acquisition_principal_id = result.acquisition_principal_id;
    IF NOT audio_is_live THEN
        authority_is_live := false;
    END IF;
    IF authority_is_live THEN
        BEGIN
            PERFORM public.require_exercise_practice_service_live_v1(
                result.session_id, result.acquisition_principal_id
            );
            PERFORM public.require_exercise_service_current_authority_v1(
                result.authorization_check_id,
                result.acquisition_principal_id
            );
        EXCEPTION WHEN raise_exception THEN
            IF SQLERRM IN (
                'MLC3_SERVICE_CONTRACT_NOT_ACTIVE',
                'MLC3_SERVICE_PRINCIPAL_NOT_ALLOWED',
                'PRACTICE_SOURCE_NOT_LIVE',
                'EXERCISE_CURRENT_AUTHORIZATION_REVOKED',
                'EXERCISE_CURRENT_AUTHORIZATION_REQUIRED'
            ) THEN
                authority_is_live := false;
            ELSE
                RAISE;
            END IF;
        END;
    END IF;
    accepted_status := CASE
        WHEN clock_timestamp() > result.permit_expires_at
            THEN 'expired_after_dispatch'
        WHEN NOT authority_is_live THEN 'revoked_after_dispatch'
        ELSE p_terminal_status
    END;
    accepted_error_code := CASE accepted_status
        WHEN 'expired_after_dispatch'
            THEN 'PERMIT_EXPIRED_AFTER_DISPATCH'
        WHEN 'revoked_after_dispatch'
            THEN 'AUTHORITY_REVOKED_AFTER_DISPATCH'
        ELSE p_provider_error_code
    END;
    transcript_value := CASE WHEN accepted_status = 'finalized'
        THEN NULLIF(btrim(p_normalized_output->>'transcript'), '')
        ELSE NULL END;
    transcript_state_value := CASE WHEN accepted_status = 'finalized'
        THEN CASE WHEN transcript_value IS NULL THEN 'missing'
                  ELSE 'available' END
        ELSE NULL END;
    transcript_hash := CASE WHEN transcript_value IS NOT NULL
        THEN public.exercise_json_sha256_v1(to_jsonb(transcript_value))
        ELSE NULL END;
    response_hash := CASE WHEN accepted_status = 'finalized'
        THEN public.exercise_json_sha256_v1(p_normalized_output)
        ELSE NULL END;
    final_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'request_sha256', result.request_sha256,
        'permit_sha256', result.permit_sha256,
        'dispatch_sha256', result.dispatch_sha256,
        'terminal_status', accepted_status,
        'response_sha256', response_hash,
        'transcript_state', transcript_state_value,
        'transcript_sha256', transcript_hash,
        'provider_error_code', accepted_error_code,
        'finalization_idempotency_key', p_idempotency_key
    ));
    PERFORM set_config(
        'willab.practice_transcription_transition', 'allowed', true
    );
    UPDATE public.exercise_practice_transcription_runs
       SET status = accepted_status,
           normalized_output = CASE WHEN accepted_status = 'finalized'
               THEN p_normalized_output ELSE NULL END,
           response_sha256 = response_hash,
           transcript_state = transcript_state_value,
           transcript_text = transcript_value,
           transcript_sha256 = transcript_hash,
           provider_error_code = accepted_error_code,
           run_sha256 = final_hash,
           finalization_idempotency_key = p_idempotency_key,
           finalized_at = clock_timestamp()
     WHERE id = result.id
     RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.reconcile_exercise_practice_transcription_v1(
    p_run_id UUID,
    p_acquisition_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_transcription_runs
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    result public.exercise_practice_transcription_runs;
    final_hash TEXT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_RECONCILIATION_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-transcription-run:' || p_run_id::TEXT, 0
    ));
    SELECT * INTO STRICT result
      FROM public.exercise_practice_transcription_runs row
     WHERE row.id = p_run_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
     FOR UPDATE;
    IF result.status <> 'dispatched' THEN
        IF result.status = 'outcome_uncommitted'
           AND result.finalization_idempotency_key = p_idempotency_key
        THEN
            RETURN result;
        END IF;
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_RECONCILIATION_CONFLICT';
    END IF;
    final_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'request_sha256', result.request_sha256,
        'permit_sha256', result.permit_sha256,
        'dispatch_sha256', result.dispatch_sha256,
        'terminal_status', 'outcome_uncommitted',
        'response_sha256', NULL,
        'transcript_state', NULL,
        'transcript_sha256', NULL,
        'provider_error_code', 'PROVIDER_OUTCOME_NOT_COMMITTED',
        'finalization_idempotency_key', p_idempotency_key
    ));
    PERFORM set_config(
        'willab.practice_transcription_transition', 'allowed', true
    );
    UPDATE public.exercise_practice_transcription_runs
       SET status = 'outcome_uncommitted',
           provider_error_code = 'PROVIDER_OUTCOME_NOT_COMMITTED',
           run_sha256 = final_hash,
           finalization_idempotency_key = p_idempotency_key,
           finalized_at = clock_timestamp()
     WHERE id = result.id
     RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.reconcile_exercise_practice_transcription_request_v1(
    p_recovery_id UUID,
    p_acquisition_principal_id UUID,
    p_authorization_idempotency_key TEXT,
    p_reconciliation_idempotency_key TEXT
) RETURNS public.exercise_practice_transcription_runs
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    result public.exercise_practice_transcription_runs;
BEGIN
    IF COALESCE(btrim(p_authorization_idempotency_key), '') = ''
       OR COALESCE(btrim(p_reconciliation_idempotency_key), '') = ''
    THEN
        RAISE EXCEPTION 'PRACTICE_TRANSCRIPTION_RECONCILIATION_INVALID';
    END IF;
    -- Match the authorization lock order.  This recovery path intentionally
    -- does not require continuing service authority: it can only discard an
    -- unresolved provider outcome and stores no provider response.
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-upload-recovery:' || p_recovery_id::TEXT, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-transcription:' || p_authorization_idempotency_key, 0
    ));
    SELECT * INTO result
      FROM public.exercise_practice_transcription_runs row
     WHERE row.upload_recovery_id = p_recovery_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.idempotency_key = p_authorization_idempotency_key;
    IF result.id IS NULL THEN
        RETURN NULL;
    END IF;
    RETURN public.reconcile_exercise_practice_transcription_v1(
        result.id, result.acquisition_principal_id,
        p_reconciliation_idempotency_key
    );
END;
$$;

DROP FUNCTION IF EXISTS public.attach_exercise_practice_service_attempt_v1(
    UUID,UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,INTEGER,
    TIMESTAMPTZ,TIMESTAMPTZ,JSONB,TEXT
);
CREATE OR REPLACE FUNCTION public.attach_exercise_practice_service_attempt_v1(
    p_recovery_id UUID,
    p_processing_recording_attempt_id UUID,
    p_processing_audio_object_id UUID,
    p_practice_acquisition_receipt_id UUID,
    p_transcription_run_id UUID,
    p_exact_passage TEXT,
    p_duration_ms INTEGER,
    p_capture_started_at TIMESTAMPTZ,
    p_capture_completed_at TIMESTAMPTZ,
    p_recording_conditions JSONB,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_attempts
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    recovery public.exercise_practice_upload_recoveries;
    practice public.exercise_practice_sessions;
    processing_attempt public.processing_recording_attempts;
    audio_object public.processing_audio_objects;
    acquisition_receipt public.exercise_service_acquisition_receipts;
    transcription_run public.exercise_practice_transcription_runs;
    result public.exercise_practice_attempts;
    transcript_sha256 TEXT;
    derived_attempt_sha256 TEXT;
BEGIN
    IF p_duration_ms < 1
       OR p_capture_completed_at < p_capture_started_at
       OR jsonb_typeof(p_recording_conditions) <> 'object'
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_ATTEMPT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-upload-recovery:' || p_recovery_id::TEXT, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-attempt:' || p_idempotency_key, 0
    ));
    SELECT * INTO STRICT recovery
      FROM public.exercise_practice_upload_recoveries row
     WHERE row.id = p_recovery_id
       AND row.operation_mode = 'allowlisted_service'
     FOR UPDATE;
    practice := public.require_exercise_practice_service_live_v1(
        recovery.session_id, recovery.acquisition_principal_id
    );
    SELECT * INTO STRICT processing_attempt
      FROM public.processing_recording_attempts row
     WHERE row.id = p_processing_recording_attempt_id
       AND row.acquisition_principal_id = practice.acquisition_principal_id
       AND row.project_id = practice.project_id
       AND row.recording_id = recovery.recording_id
       AND row.authorization_snapshot_id = recovery.authorization_snapshot_id
       AND row.status NOT IN ('cancelled', 'purged');
    SELECT * INTO STRICT audio_object
      FROM public.processing_audio_objects row
     WHERE row.id = p_processing_audio_object_id
       AND row.recording_attempt_id = processing_attempt.id
       AND row.acquisition_principal_id = practice.acquisition_principal_id
       AND row.storage_provider = 'r2'
       AND row.bucket = recovery.bucket
       AND row.object_key = recovery.object_key
       AND row.byte_size = recovery.byte_size
       AND row.content_type = recovery.content_type
       AND row.exact_bytes_sha256 = recovery.intended_exact_bytes_sha256
       AND row.deleted_at IS NULL;
    SELECT * INTO STRICT acquisition_receipt
      FROM public.exercise_service_acquisition_receipts row
     WHERE row.id = p_practice_acquisition_receipt_id
       AND row.acquisition_principal_id = practice.acquisition_principal_id
       AND row.acquisition_kind = 'practice_recording'
       AND row.processing_recording_attempt_id = processing_attempt.id
       AND row.processing_audio_object_id = audio_object.id
       AND row.service_authorization_snapshot_id =
           recovery.authorization_snapshot_id
       AND row.pooled_authorization_snapshot_id IS NOT DISTINCT FROM
           recovery.pooled_authorization_snapshot_id;
    SELECT * INTO STRICT transcription_run
      FROM public.exercise_practice_transcription_runs row
     WHERE row.id = p_transcription_run_id
       AND row.session_id = practice.id
       AND row.upload_recovery_id = recovery.id
       AND row.acquisition_principal_id = practice.acquisition_principal_id
       AND row.processing_recording_attempt_id = processing_attempt.id
       AND row.processing_audio_object_id = audio_object.id
       AND row.practice_acquisition_receipt_id = acquisition_receipt.id
       AND row.authorization_check_id = recovery.authorization_check_id
       AND row.exact_audio_sha256 = audio_object.exact_bytes_sha256
       AND row.status = 'finalized'
       AND row.run_sha256 IS NOT NULL
       AND NOT row.serves_user AND NOT row.dataset_eligible;
    transcript_sha256 := transcription_run.transcript_sha256;
    derived_attempt_sha256 := public.exercise_json_sha256_v1(
        jsonb_build_object(
            'operation_mode', 'allowlisted_service',
            'service_contract_version', 'mlc3-first-client-service-v1',
            'session_id', practice.id,
            'acquisition_principal_id', practice.acquisition_principal_id,
            'processing_recording_attempt_id', processing_attempt.id,
            'processing_audio_object_id', audio_object.id,
            'practice_acquisition_receipt_id', acquisition_receipt.id,
            'upload_recovery_id', recovery.id,
            'attempt_index', recovery.attempt_index,
            'exact_passage', p_exact_passage,
            'transcription_run_id', transcription_run.id,
            'transcription_run_sha256', transcription_run.run_sha256,
            'transcription_request_sha256', transcription_run.request_sha256,
            'transcription_response_sha256', transcription_run.response_sha256,
            'transcript_state', transcription_run.transcript_state,
            'transcript_text', transcription_run.transcript_text,
            'transcript_sha256', transcript_sha256,
            'transcript_missing_reason', CASE
                WHEN transcription_run.transcript_state = 'missing'
                THEN 'provider_returned_no_transcript' ELSE NULL END,
            'exact_audio_sha256', audio_object.exact_bytes_sha256,
            'duration_ms', p_duration_ms,
            'capture_started_at', p_capture_started_at,
            'capture_completed_at', p_capture_completed_at,
            'recording_conditions', p_recording_conditions
        )
    );
    IF recovery.status NOT IN ('write_acknowledged', 'attached')
       OR p_exact_passage IS DISTINCT FROM practice.exact_passage
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_ATTEMPT_HASH_MISMATCH';
    END IF;
    SELECT * INTO result
      FROM public.exercise_practice_attempts row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.upload_recovery_id <> recovery.id
           OR result.processing_audio_object_id <> audio_object.id
           OR result.practice_acquisition_receipt_id <>
              acquisition_receipt.id
           OR result.transcription_run_id <> transcription_run.id
           OR result.attempt_sha256 <> derived_attempt_sha256
           OR result.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_ATTEMPT_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    IF practice.state <> 'open' THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_SESSION_NOT_OPEN';
    END IF;
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.exercise_practice_attempts (
        session_id, acquisition_principal_id,
        processing_recording_attempt_id, processing_audio_object_id,
        upload_recovery_id, attempt_index, exact_passage,
        transcript_state, transcript_text, transcript_sha256,
        transcript_missing_reason, exact_audio_sha256, duration_ms,
        capture_started_at, capture_completed_at, recording_conditions,
        state, attempt_sha256, idempotency_key,
        practice_acquisition_receipt_id, transcription_run_id
    ) VALUES (
        practice.id, practice.acquisition_principal_id,
        processing_attempt.id, audio_object.id, recovery.id,
        recovery.attempt_index, p_exact_passage,
        transcription_run.transcript_state,
        transcription_run.transcript_text, transcript_sha256,
        CASE WHEN transcription_run.transcript_state = 'missing'
             THEN 'provider_returned_no_transcript' ELSE NULL END,
        audio_object.exact_bytes_sha256, p_duration_ms,
        p_capture_started_at, p_capture_completed_at,
        p_recording_conditions,
        CASE WHEN transcription_run.transcript_state = 'missing' THEN 'invalid'
             ELSE 'captured' END,
        derived_attempt_sha256, p_idempotency_key, acquisition_receipt.id,
        transcription_run.id
    ) RETURNING * INTO result;
    UPDATE public.exercise_practice_upload_recoveries
       SET status = 'attached', processing_audio_object_id = audio_object.id
     WHERE id = recovery.id;
    PERFORM public.require_exercise_practice_service_live_v1(
        practice.id, practice.acquisition_principal_id
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_exercise_practice_service_measurement_v1(
    p_attempt_id UUID,
    p_measurement_revision INTEGER,
    p_extractor_version TEXT,
    p_feature_schema_version TEXT,
    p_raw_measurements JSONB,
    p_safeguards JSONB,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_measurement_revisions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    attempt public.exercise_practice_attempts;
    practice public.exercise_practice_sessions;
    transcription_run public.exercise_practice_transcription_runs;
    result public.exercise_practice_measurement_revisions;
    derived_input_sha256 TEXT;
    derived_output_sha256 TEXT;
BEGIN
    SELECT * INTO STRICT attempt
      FROM public.exercise_practice_attempts row
     WHERE row.id = p_attempt_id
       AND row.operation_mode = 'allowlisted_service';
    practice := public.require_exercise_practice_service_live_v1(
        attempt.session_id, attempt.acquisition_principal_id
    );
    SELECT * INTO STRICT transcription_run
      FROM public.exercise_practice_transcription_runs row
     WHERE row.id = attempt.transcription_run_id
       AND row.session_id = attempt.session_id
       AND row.acquisition_principal_id = attempt.acquisition_principal_id
       AND row.processing_audio_object_id = attempt.processing_audio_object_id
       AND row.exact_audio_sha256 = attempt.exact_audio_sha256
       AND row.status = 'finalized'
       AND row.transcript_state = attempt.transcript_state
       AND row.transcript_sha256 IS NOT DISTINCT FROM attempt.transcript_sha256
       AND row.run_sha256 IS NOT NULL
       AND NOT row.serves_user AND NOT row.dataset_eligible;
    derived_input_sha256 := public.exercise_json_sha256_v1(
        jsonb_build_object(
            'operation_mode', 'allowlisted_service',
            'attempt_id', attempt.id,
            'attempt_sha256', attempt.attempt_sha256,
            'transcription_run_id', transcription_run.id,
            'transcription_run_sha256', transcription_run.run_sha256,
            'transcription_response_sha256',
                transcription_run.response_sha256,
            'measurement_revision', p_measurement_revision,
            'extractor_version', p_extractor_version,
            'feature_schema_version', p_feature_schema_version
        )
    );
    derived_output_sha256 := public.exercise_json_sha256_v1(
        jsonb_build_object(
            'input_sha256', derived_input_sha256,
            'raw_measurements', p_raw_measurements,
            'safeguards', p_safeguards
        )
    );
    IF attempt.state IN ('cancelled', 'quarantined')
       OR p_measurement_revision < 1
       OR p_extractor_version IS DISTINCT FROM
          practice.measurement_extractor_version
       OR p_feature_schema_version IS DISTINCT FROM
          practice.measurement_feature_schema_version
       OR jsonb_typeof(p_raw_measurements) <> 'object'
       OR jsonb_typeof(p_safeguards) <> 'object'
       OR NOT (p_raw_measurements ? 'phrase_span')
       OR NOT (p_raw_measurements ? 'ending_span')
       OR NOT (p_raw_measurements ? 'prefix_span')
       OR NOT (p_raw_measurements ? 'measurement_status')
       OR NOT (p_safeguards ? 'missingness_reasons')
       OR NOT (p_safeguards ? 'uncertainty')
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_MEASUREMENT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-measurement:' || p_idempotency_key, 0
    ));
    practice := public.require_exercise_practice_service_live_v1(
        attempt.session_id, attempt.acquisition_principal_id
    );
    SELECT * INTO result
      FROM public.exercise_practice_measurement_revisions row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.attempt_id <> attempt.id
           OR result.measurement_revision <> p_measurement_revision
           OR result.input_sha256 <> derived_input_sha256
           OR result.output_sha256 <> derived_output_sha256
           OR result.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_MEASUREMENT_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.exercise_practice_measurement_revisions (
        attempt_id, acquisition_principal_id, measurement_revision,
        extractor_version, feature_schema_version, raw_measurements,
        safeguards, input_sha256, output_sha256, idempotency_key
    ) VALUES (
        attempt.id, attempt.acquisition_principal_id,
        p_measurement_revision, p_extractor_version,
        p_feature_schema_version, p_raw_measurements, p_safeguards,
        derived_input_sha256, derived_output_sha256, p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_exercise_practice_service_validity_v1(
    p_attempt_id UUID,
    p_measurement_revision_id UUID,
    p_baseline_revision INTEGER,
    p_validity TEXT,
    p_reason_codes TEXT[],
    p_validity_contract_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_validity_assessments
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    attempt public.exercise_practice_attempts;
    measurement public.exercise_practice_measurement_revisions;
    practice public.exercise_practice_sessions;
    result public.exercise_practice_validity_assessments;
    derived_hash TEXT;
BEGIN
    SELECT * INTO STRICT attempt
      FROM public.exercise_practice_attempts row
     WHERE row.id = p_attempt_id
       AND row.operation_mode = 'allowlisted_service';
    practice := public.require_exercise_practice_service_live_v1(
        attempt.session_id, attempt.acquisition_principal_id
    );
    SELECT * INTO STRICT measurement
      FROM public.exercise_practice_measurement_revisions row
     WHERE row.id = p_measurement_revision_id
       AND row.attempt_id = attempt.id
       AND row.acquisition_principal_id = attempt.acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service';
    derived_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'attempt_id', attempt.id,
        'attempt_sha256', attempt.attempt_sha256,
        'measurement_revision_id', measurement.id,
        'measurement_output_sha256', measurement.output_sha256,
        'baseline_revision', p_baseline_revision,
        'validity', p_validity,
        'reason_codes', to_jsonb(p_reason_codes),
        'validity_contract_version', p_validity_contract_version
    ));
    IF p_baseline_revision <> practice.baseline_revision
       OR p_validity_contract_version IS DISTINCT FROM
          practice.validity_contract_version
       OR measurement.extractor_version IS DISTINCT FROM
          practice.measurement_extractor_version
       OR measurement.feature_schema_version IS DISTINCT FROM
          practice.measurement_feature_schema_version
       OR p_validity NOT IN ('valid', 'invalid', 'pending')
       OR (p_validity = 'valid' AND cardinality(p_reason_codes) <> 0)
       OR (p_validity <> 'valid' AND cardinality(p_reason_codes) = 0)
       OR (attempt.transcript_state = 'missing' AND p_validity = 'valid')
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_VALIDITY_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-validity:' || p_idempotency_key, 0
    ));
    practice := public.require_exercise_practice_service_live_v1(
        attempt.session_id, attempt.acquisition_principal_id
    );
    SELECT * INTO result
      FROM public.exercise_practice_validity_assessments row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.assessment_sha256 <> derived_hash
           OR result.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_VALIDITY_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.exercise_practice_validity_assessments (
        attempt_id, measurement_revision_id, acquisition_principal_id,
        baseline_revision, validity, reason_codes,
        validity_contract_version, assessment_sha256, idempotency_key
    ) VALUES (
        attempt.id, measurement.id, attempt.acquisition_principal_id,
        p_baseline_revision, p_validity, p_reason_codes,
        p_validity_contract_version, derived_hash, p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.freeze_exercise_practice_service_selection_v1(
    p_session_id UUID,
    p_acquisition_principal_id UUID,
    p_baseline_revision INTEGER,
    p_revision INTEGER,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_selection_revisions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    practice public.exercise_practice_sessions;
    result public.exercise_practice_selection_revisions;
    inventory JSONB;
    first_valid UUID;
    first_valid_index INTEGER;
    unresolved_earlier BOOLEAN;
    selection_state TEXT;
BEGIN
    practice := public.require_exercise_practice_service_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    IF p_baseline_revision <> practice.baseline_revision OR p_revision < 1
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_SELECTION_BASELINE_STALE';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-service-selection:' || p_session_id::TEXT, 0
    ));
    practice := public.require_exercise_practice_service_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    IF p_baseline_revision <> practice.baseline_revision THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_SELECTION_BASELINE_STALE';
    END IF;
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'attempt_id', attempt.id,
        'attempt_index', attempt.attempt_index,
        'assessment_id', assessment.id,
        'validity', COALESCE(assessment.validity, 'pending'),
        'reason_codes', COALESCE(
            to_jsonb(assessment.reason_codes),
            '["assessment_missing"]'::JSONB
        )
    ) ORDER BY attempt.attempt_index), '[]'::JSONB)
      INTO inventory
      FROM public.exercise_practice_attempts attempt
      LEFT JOIN public.exercise_practice_validity_assessments assessment
        ON assessment.attempt_id = attempt.id
       AND assessment.baseline_revision = p_baseline_revision
       AND assessment.validity_contract_version =
           practice.validity_contract_version
       AND assessment.operation_mode = 'allowlisted_service'
     WHERE attempt.session_id = practice.id
       AND attempt.operation_mode = 'allowlisted_service';
    SELECT attempt.id, attempt.attempt_index
      INTO first_valid, first_valid_index
      FROM public.exercise_practice_attempts attempt
      JOIN public.exercise_practice_validity_assessments assessment
        ON assessment.attempt_id = attempt.id
       AND assessment.baseline_revision = p_baseline_revision
       AND assessment.validity_contract_version =
           practice.validity_contract_version
       AND assessment.validity = 'valid'
       AND assessment.operation_mode = 'allowlisted_service'
     WHERE attempt.session_id = practice.id
       AND attempt.operation_mode = 'allowlisted_service'
     ORDER BY attempt.attempt_index LIMIT 1;
    SELECT EXISTS (
        SELECT 1
          FROM public.exercise_practice_attempts attempt
          LEFT JOIN public.exercise_practice_validity_assessments assessment
            ON assessment.attempt_id = attempt.id
           AND assessment.baseline_revision = p_baseline_revision
           AND assessment.validity_contract_version =
               practice.validity_contract_version
           AND assessment.operation_mode = 'allowlisted_service'
         WHERE attempt.session_id = practice.id
           AND attempt.operation_mode = 'allowlisted_service'
           AND (first_valid_index IS NULL
                OR attempt.attempt_index < first_valid_index)
           AND (assessment.id IS NULL OR assessment.validity = 'pending')
    ) INTO unresolved_earlier;
    IF jsonb_array_length(inventory) = 0 THEN
        selection_state := 'no_attempt';
        first_valid := NULL;
    ELSIF unresolved_earlier THEN
        selection_state := 'pending_earlier_attempt';
        first_valid := NULL;
    ELSIF first_valid IS NOT NULL THEN
        selection_state := 'selected_first_valid';
    ELSE
        selection_state := 'no_valid_attempt';
    END IF;
    SELECT * INTO result
      FROM public.exercise_practice_selection_revisions row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.session_id <> practice.id
           OR result.baseline_revision <> p_baseline_revision
           OR result.inventory IS DISTINCT FROM inventory
           OR result.selected_attempt_id IS DISTINCT FROM first_valid
           OR result.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_SELECTION_REPLAY_CONFLICT';
        END IF;
        RETURN result;
    END IF;
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.exercise_practice_selection_revisions (
        session_id, acquisition_principal_id, baseline_revision, revision,
        inventory, selected_attempt_id, selection_state,
        selection_policy_version, inventory_sha256, idempotency_key
    ) VALUES (
        practice.id, practice.acquisition_principal_id,
        p_baseline_revision, p_revision, inventory, first_valid,
        selection_state, 'first-valid-attempt-v1',
        public.exercise_json_sha256_v1(inventory), p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_exercise_offer_service_event_v1(
    p_offer_id UUID,
    p_acquisition_principal_id UUID,
    p_recipient_user_id UUID,
    p_event_kind TEXT,
    p_render_instance_id UUID,
    p_content_identity_sha256 TEXT,
    p_event_payload JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_offer_events
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    offer public.exercise_service_offers;
    existing public.exercise_service_offer_events;
    prior_kind TEXT;
    derived_hash TEXT;
BEGIN
    IF p_event_kind NOT IN (
        'delivery_prepared', 'render_confirmed',
        'playback_started', 'playback_completed'
    ) OR p_content_identity_sha256 !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_event_payload) <> 'object'
       OR COALESCE(btrim(p_idempotency_key), '') = ''
       OR p_occurred_at > clock_timestamp() + INTERVAL '5 minutes'
       OR (p_event_kind = 'delivery_prepared'
           AND p_render_instance_id IS NOT NULL)
       OR (p_event_kind <> 'delivery_prepared'
           AND p_render_instance_id IS NULL)
    THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_EVENT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-offer-event:' || p_idempotency_key, 0
    ));
    offer := public.require_exercise_service_offer_live_v1(
        p_offer_id, p_acquisition_principal_id
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.owner_principals principal
         WHERE principal.id = offer.acquisition_principal_id
           AND principal.user_id = p_recipient_user_id
    ) THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_EVENT_RECIPIENT_INVALID';
    END IF;
    SELECT * INTO existing
      FROM public.exercise_service_offer_events row
     WHERE row.idempotency_key = p_idempotency_key;
    derived_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'offer_id', offer.id,
        'offer_sha256', offer.offer_sha256,
        'acquisition_principal_id', offer.acquisition_principal_id,
        'recipient_user_id', p_recipient_user_id,
        'event_kind', p_event_kind,
        'render_instance_id', p_render_instance_id,
        'content_identity_sha256', p_content_identity_sha256,
        'event_payload', p_event_payload,
        'occurred_at', p_occurred_at,
        'operation_mode', 'allowlisted_service'
    ));
    IF existing.id IS NOT NULL THEN
        IF existing.offer_id <> offer.id
           OR existing.acquisition_principal_id <>
              offer.acquisition_principal_id
           OR existing.recipient_user_id <> p_recipient_user_id
           OR existing.event_kind <> p_event_kind
           OR existing.render_instance_id IS DISTINCT FROM
              p_render_instance_id
           OR existing.content_identity_sha256 <>
              p_content_identity_sha256
           OR existing.event_payload IS DISTINCT FROM p_event_payload
           OR existing.occurred_at <> p_occurred_at
           OR existing.event_sha256 <> derived_hash
           OR existing.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'EXERCISE_SERVICE_EVENT_REPLAY_CONFLICT';
        END IF;
        offer := public.require_exercise_service_offer_live_v1(
            offer.id, offer.acquisition_principal_id
        );
        RETURN existing;
    END IF;
    prior_kind := CASE p_event_kind
        WHEN 'delivery_prepared' THEN 'assignment_prepared'
        WHEN 'render_confirmed' THEN 'delivery_prepared'
        WHEN 'playback_started' THEN 'render_confirmed'
        WHEN 'playback_completed' THEN 'playback_started'
    END;
    IF NOT EXISTS (
        SELECT 1 FROM public.exercise_service_offer_events prior
         WHERE prior.offer_id = offer.id
           AND prior.acquisition_principal_id = offer.acquisition_principal_id
           AND prior.event_kind = prior_kind
           AND (p_event_kind = 'delivery_prepared'
                OR (prior.recipient_user_id = p_recipient_user_id
                    AND prior.content_identity_sha256 =
                        p_content_identity_sha256))
           AND (p_event_kind IN ('delivery_prepared', 'render_confirmed')
                OR prior.render_instance_id = p_render_instance_id)
    ) THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_EVENT_SEQUENCE_INVALID';
    END IF;
    offer := public.require_exercise_service_offer_live_v1(
        offer.id, offer.acquisition_principal_id
    );
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.exercise_service_offer_events (
        offer_id, acquisition_principal_id, event_kind, event_payload,
        event_sha256, idempotency_key, occurred_at, recipient_user_id,
        render_instance_id, content_identity_sha256
    ) VALUES (
        offer.id, offer.acquisition_principal_id, p_event_kind,
        p_event_payload, derived_hash, p_idempotency_key, p_occurred_at,
        p_recipient_user_id, p_render_instance_id,
        p_content_identity_sha256
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_exercise_practice_service_event_v1(
    p_session_id UUID,
    p_acquisition_principal_id UUID,
    p_recipient_user_id UUID,
    p_attempt_id UUID,
    p_event_kind TEXT,
    p_render_instance_id UUID,
    p_content_identity_sha256 TEXT,
    p_event_payload JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_events
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    practice public.exercise_practice_sessions;
    existing public.exercise_practice_events;
    prior_kind TEXT;
    derived_hash TEXT;
BEGIN
    IF p_event_kind NOT IN (
        'delivery_prepared', 'render_confirmed',
        'playback_started', 'playback_completed',
        'capture_reserved', 'capture_started', 'capture_completed',
        'attempt_processed'
    ) OR p_content_identity_sha256 !~ '^[0-9a-f]{64}$'
       OR jsonb_typeof(p_event_payload) <> 'object'
       OR COALESCE(btrim(p_idempotency_key), '') = ''
       OR p_occurred_at > clock_timestamp() + INTERVAL '5 minutes'
       OR (p_event_kind = 'delivery_prepared'
           AND p_render_instance_id IS NOT NULL)
       OR (p_event_kind <> 'delivery_prepared'
           AND p_render_instance_id IS NULL)
       OR (p_event_kind = 'attempt_processed' AND p_attempt_id IS NULL)
       OR (p_event_kind <> 'attempt_processed' AND p_attempt_id IS NOT NULL)
    THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_EVENT_INVALID';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-practice-service-event:' || p_idempotency_key, 0
    ));
    practice := public.require_exercise_practice_service_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.owner_principals principal
         WHERE principal.id = practice.acquisition_principal_id
           AND principal.user_id = p_recipient_user_id
    ) THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_EVENT_RECIPIENT_INVALID';
    END IF;
    derived_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'session_id', practice.id,
        'session_sha256', practice.session_sha256,
        'acquisition_principal_id', practice.acquisition_principal_id,
        'recipient_user_id', p_recipient_user_id,
        'attempt_id', p_attempt_id,
        'event_kind', p_event_kind,
        'render_instance_id', p_render_instance_id,
        'content_identity_sha256', p_content_identity_sha256,
        'event_payload', p_event_payload,
        'occurred_at', p_occurred_at,
        'operation_mode', 'allowlisted_service'
    ));
    SELECT * INTO existing
      FROM public.exercise_practice_events row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.session_id <> practice.id
           OR existing.acquisition_principal_id <>
              practice.acquisition_principal_id
           OR existing.recipient_user_id <> p_recipient_user_id
           OR existing.attempt_id IS DISTINCT FROM p_attempt_id
           OR existing.event_kind <> p_event_kind
           OR existing.render_instance_id IS DISTINCT FROM
              p_render_instance_id
           OR existing.content_identity_sha256 <>
              p_content_identity_sha256
           OR existing.event_payload IS DISTINCT FROM p_event_payload
           OR existing.occurred_at <> p_occurred_at
           OR existing.event_sha256 <> derived_hash
           OR existing.operation_mode <> 'allowlisted_service'
        THEN
            RAISE EXCEPTION 'PRACTICE_SERVICE_EVENT_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    prior_kind := CASE p_event_kind
        WHEN 'delivery_prepared' THEN 'assignment_prepared'
        WHEN 'render_confirmed' THEN 'delivery_prepared'
        WHEN 'playback_started' THEN 'render_confirmed'
        WHEN 'playback_completed' THEN 'playback_started'
        WHEN 'capture_reserved' THEN 'render_confirmed'
        WHEN 'capture_started' THEN 'capture_reserved'
        WHEN 'capture_completed' THEN 'capture_started'
        WHEN 'attempt_processed' THEN 'capture_completed'
    END;
    IF NOT EXISTS (
        SELECT 1 FROM public.exercise_practice_events prior
         WHERE prior.session_id = practice.id
           AND prior.acquisition_principal_id =
               practice.acquisition_principal_id
           AND prior.event_kind = prior_kind
           AND (p_event_kind = 'delivery_prepared'
                OR (prior.recipient_user_id = p_recipient_user_id
                    AND prior.content_identity_sha256 =
                        p_content_identity_sha256))
           AND (p_event_kind IN ('delivery_prepared', 'render_confirmed')
                OR prior.render_instance_id = p_render_instance_id)
    ) THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_EVENT_SEQUENCE_INVALID';
    END IF;
    practice := public.require_exercise_practice_service_live_v1(
        practice.id, practice.acquisition_principal_id
    );
    IF p_attempt_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.exercise_practice_attempts attempt
         WHERE attempt.id = p_attempt_id
           AND attempt.session_id = practice.id
           AND attempt.acquisition_principal_id =
               practice.acquisition_principal_id
           AND attempt.operation_mode = 'allowlisted_service'
    ) THEN
        RAISE EXCEPTION 'PRACTICE_SERVICE_EVENT_ATTEMPT_INVALID';
    END IF;
    PERFORM set_config(
        'willab.mlc3_operation_mode', 'allowlisted_service', true
    );
    INSERT INTO public.exercise_practice_events (
        session_id, acquisition_principal_id, attempt_id, event_kind,
        event_payload, occurred_at, event_sha256, idempotency_key,
        recipient_user_id, render_instance_id, content_identity_sha256
    ) VALUES (
        practice.id, practice.acquisition_principal_id, p_attempt_id,
        p_event_kind, p_event_payload, p_occurred_at, derived_hash,
        p_idempotency_key, p_recipient_user_id, p_render_instance_id,
        p_content_identity_sha256
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

-- ── Separate blind confidence review for source and practice audio ────────
CREATE OR REPLACE FUNCTION public.require_exercise_service_confidence_live_v1(
    p_assignment_id UUID,
    p_reviewer_principal_id UUID
) RETURNS public.exercise_service_confidence_assignments
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    assignment public.exercise_service_confidence_assignments;
    practice public.exercise_practice_sessions;
BEGIN
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    SELECT * INTO STRICT assignment
     FROM public.exercise_service_confidence_assignments row
     WHERE row.id = p_assignment_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND (
           row.expires_at > clock_timestamp()
           OR EXISTS (
               SELECT 1
                 FROM public.exercise_service_confidence_judgments judgment
                WHERE judgment.assignment_id = row.id
                  AND judgment.reviewer_principal_id =
                      row.reviewer_principal_id
                  AND judgment.actor_provenance = 'blind_coach'
           )
       )
       AND NOT EXISTS (
           SELECT 1
             FROM public.exercise_service_confidence_assignments newer
            WHERE newer.practice_session_id = row.practice_session_id
              AND newer.reviewer_principal_id = row.reviewer_principal_id
              AND newer.evidence_kind = row.evidence_kind
              AND newer.assignment_revision > row.assignment_revision
       )
       AND NOT row.serves_user AND NOT row.dataset_eligible;
    practice := public.require_exercise_practice_service_live_v1(
        assignment.practice_session_id,
        assignment.acquisition_principal_id
    );
    IF practice.project_id <> assignment.project_id
       OR (
           assignment.evidence_kind = 'original_source'
           AND NOT EXISTS (
               SELECT 1
                 FROM public.exercise_audio_lineages lineage
                 JOIN public.processing_audio_objects object_row
                   ON object_row.id = lineage.processing_audio_object_id
                  AND object_row.acquisition_principal_id =
                      lineage.acquisition_principal_id
                  AND object_row.deleted_at IS NULL
                WHERE lineage.id = assignment.source_audio_lineage_id
                  AND lineage.id = practice.source_audio_lineage_id
                  AND lineage.acquisition_principal_id =
                      assignment.acquisition_principal_id
                  AND lineage.processing_audio_object_id =
                      assignment.processing_audio_object_id
                  AND lineage.exact_audio_sha256 =
                      assignment.exact_audio_sha256
                  AND lineage.start_offset_ms = assignment.start_offset_ms
                  AND lineage.duration_ms = assignment.duration_ms
           )
       ) OR (
           assignment.evidence_kind = 'first_valid_practice'
           AND NOT EXISTS (
               SELECT 1
                 FROM public.exercise_practice_attempts attempt
                 JOIN public.processing_audio_objects object_row
                   ON object_row.id = attempt.processing_audio_object_id
                  AND object_row.acquisition_principal_id =
                      attempt.acquisition_principal_id
                  AND object_row.deleted_at IS NULL
                 JOIN public.exercise_practice_selection_revisions selection
                   ON selection.selected_attempt_id = attempt.id
                  AND selection.session_id = attempt.session_id
                  AND selection.baseline_revision = practice.baseline_revision
                  AND selection.selection_state = 'selected_first_valid'
                WHERE attempt.id = assignment.practice_attempt_id
                  AND attempt.session_id = practice.id
                  AND attempt.acquisition_principal_id =
                      assignment.acquisition_principal_id
                  AND attempt.processing_audio_object_id =
                      assignment.processing_audio_object_id
                  AND attempt.exact_audio_sha256 =
                      assignment.exact_audio_sha256
                  AND attempt.duration_ms = assignment.duration_ms
                  AND attempt.state NOT IN ('cancelled', 'quarantined')
           )
       )
    THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_CONFIDENCE_SOURCE_NOT_LIVE';
    END IF;
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    RETURN assignment;
END;
$$;

CREATE OR REPLACE FUNCTION public.freeze_exercise_service_blind_review_set_v1(
    p_practice_session_id UUID,
    p_reviewer_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_blind_review_sets
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    practice public.exercise_practice_sessions;
    selection public.exercise_practice_selection_revisions;
    attempt public.exercise_practice_attempts;
    practice_object public.processing_audio_objects;
    lineage public.exercise_audio_lineages;
    source_object public.processing_audio_objects;
    source_snippet public.snippets;
    source_assignment public.exercise_service_confidence_assignments;
    practice_assignment public.exercise_service_confidence_assignments;
    prior_source public.exercise_service_confidence_assignments;
    prior_practice public.exercise_service_confidence_assignments;
    prior_set public.exercise_service_blind_review_sets;
    existing public.exercise_service_blind_review_sets;
    source_transcript_hash TEXT;
    practice_transcript_hash TEXT;
    source_hash TEXT;
    practice_hash TEXT;
    set_hash TEXT;
    next_source_revision INTEGER;
    next_practice_revision INTEGER;
    next_set_revision INTEGER;
    source_judged BOOLEAN;
    practice_judged BOOLEAN;
    renew_source BOOLEAN;
    renew_practice BOOLEAN;
    persisted_key TEXT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_REVIEW_KEY_REQUIRED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-review:' || p_practice_session_id::TEXT || ':' ||
        p_reviewer_principal_id::TEXT, 0
    ));
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    SELECT * INTO STRICT practice
      FROM public.require_exercise_practice_service_live_v1(
          p_practice_session_id,
          (SELECT acquisition_principal_id
             FROM public.exercise_practice_sessions
            WHERE id = p_practice_session_id)
      );
    SELECT * INTO STRICT selection
      FROM public.exercise_practice_selection_revisions row
     WHERE row.session_id = practice.id
       AND row.acquisition_principal_id = practice.acquisition_principal_id
       AND row.baseline_revision = practice.baseline_revision
       AND row.selection_state = 'selected_first_valid'
       AND row.operation_mode = 'allowlisted_service'
     ORDER BY row.revision DESC, row.id DESC
     LIMIT 1;
    SELECT * INTO STRICT attempt
      FROM public.exercise_practice_attempts row
     WHERE row.id = selection.selected_attempt_id
       AND row.session_id = practice.id
       AND row.acquisition_principal_id = practice.acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.state NOT IN ('cancelled', 'quarantined');
    SELECT * INTO STRICT practice_object
      FROM public.processing_audio_objects row
     WHERE row.id = attempt.processing_audio_object_id
       AND row.acquisition_principal_id = practice.acquisition_principal_id
       AND row.exact_bytes_sha256 = attempt.exact_audio_sha256
       AND row.deleted_at IS NULL;
    SELECT * INTO STRICT lineage
      FROM public.exercise_audio_lineages row
     WHERE row.id = practice.source_audio_lineage_id
       AND row.acquisition_principal_id = practice.acquisition_principal_id;
    SELECT * INTO STRICT source_object
      FROM public.processing_audio_objects row
     WHERE row.id = lineage.processing_audio_object_id
       AND row.acquisition_principal_id = practice.acquisition_principal_id
       AND row.exact_bytes_sha256 = lineage.exact_audio_sha256
       AND row.deleted_at IS NULL;
    SELECT * INTO STRICT source_snippet
      FROM public.snippets row
     WHERE row.id = lineage.snippet_id
       AND row.session_id = lineage.take_id
       AND row.recording_id = lineage.recording_id
       AND row.start_offset_ms = lineage.start_offset_ms
       AND row.duration_ms = lineage.duration_ms;
    source_transcript_hash := CASE
        WHEN NULLIF(btrim(source_snippet.transcript), '') IS NULL THEN NULL
        ELSE public.exercise_json_sha256_v1(to_jsonb(source_snippet.transcript))
    END;
    practice_transcript_hash := CASE
        WHEN NULLIF(btrim(attempt.transcript_text), '') IS NULL THEN NULL
        ELSE public.exercise_json_sha256_v1(to_jsonb(attempt.transcript_text))
    END;
    source_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'practice_session_id', practice.id,
        'acquisition_principal_id', practice.acquisition_principal_id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'evidence_kind', 'original_source',
        'source_audio_lineage_id', lineage.id,
        'processing_audio_object_id', source_object.id,
        'exact_audio_sha256', lineage.exact_audio_sha256,
        'start_offset_ms', lineage.start_offset_ms,
        'duration_ms', lineage.duration_ms,
        'transcript_sha256', source_transcript_hash,
        'taxonomy_version', 'confidence-five-state-v1',
        'blindness_policy_version', 'first-client-confidence-blind-v1'
    ));
    practice_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'practice_session_id', practice.id,
        'acquisition_principal_id', practice.acquisition_principal_id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'evidence_kind', 'first_valid_practice',
        'practice_attempt_id', attempt.id,
        'processing_audio_object_id', practice_object.id,
        'exact_audio_sha256', attempt.exact_audio_sha256,
        'start_offset_ms', 0,
        'duration_ms', attempt.duration_ms,
        'transcript_sha256', practice_transcript_hash,
        'taxonomy_version', 'confidence-five-state-v1',
        'blindness_policy_version', 'first-client-confidence-blind-v1'
    ));
    SELECT * INTO prior_source
      FROM public.exercise_service_confidence_assignments row
     WHERE row.practice_session_id = practice.id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.evidence_kind = 'original_source'
     ORDER BY row.assignment_revision DESC, row.id DESC LIMIT 1;
    SELECT * INTO prior_practice
      FROM public.exercise_service_confidence_assignments row
     WHERE row.practice_session_id = practice.id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.evidence_kind = 'first_valid_practice'
     ORDER BY row.assignment_revision DESC, row.id DESC LIMIT 1;
    IF (prior_source.id IS NOT NULL AND
        prior_source.packet_sha256 <> source_hash)
       OR (prior_practice.id IS NOT NULL AND (
           prior_practice.packet_sha256 <> practice_hash
           OR prior_practice.practice_attempt_id <> attempt.id
       ))
    THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_REVIEW_REPLAY_CONFLICT';
    END IF;
    source_judged := prior_source.id IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.exercise_service_confidence_judgments judgment
         WHERE judgment.assignment_id = prior_source.id
           AND judgment.reviewer_principal_id = p_reviewer_principal_id
           AND judgment.actor_provenance = 'blind_coach'
    );
    practice_judged := prior_practice.id IS NOT NULL AND EXISTS (
        SELECT 1 FROM public.exercise_service_confidence_judgments judgment
         WHERE judgment.assignment_id = prior_practice.id
           AND judgment.reviewer_principal_id = p_reviewer_principal_id
           AND judgment.actor_provenance = 'blind_coach'
    );
    renew_source := prior_source.id IS NULL OR (
        prior_source.expires_at <= clock_timestamp() AND NOT source_judged
    );
    renew_practice := prior_practice.id IS NULL OR (
        prior_practice.expires_at <= clock_timestamp() AND NOT practice_judged
    );
    SELECT * INTO prior_set
      FROM public.exercise_service_blind_review_sets row
     WHERE row.practice_session_id = practice.id
       AND row.reviewer_principal_id = p_reviewer_principal_id
     ORDER BY row.review_revision DESC, row.id DESC LIMIT 1;
    IF NOT renew_source AND NOT renew_practice THEN
        SELECT * INTO existing
          FROM public.exercise_service_blind_review_sets row
         WHERE row.source_confidence_assignment_id = prior_source.id
           AND row.practice_confidence_assignment_id = prior_practice.id;
        IF existing.id IS NOT NULL THEN RETURN existing; END IF;
    END IF;
    next_source_revision := COALESCE(prior_source.assignment_revision, 0) + 1;
    next_practice_revision := COALESCE(prior_practice.assignment_revision, 0) + 1;
    next_set_revision := COALESCE(prior_set.review_revision, 0) + 1;
    persisted_key := CASE WHEN next_set_revision = 1 THEN p_idempotency_key
        ELSE p_idempotency_key || ':revision:' || next_set_revision::TEXT END;
    IF renew_source THEN
        INSERT INTO public.exercise_service_confidence_assignments (
            acquisition_principal_id, reviewer_principal_id, project_id,
            practice_session_id, evidence_kind, source_audio_lineage_id,
            processing_audio_object_id, exact_audio_sha256, start_offset_ms,
            duration_ms, transcript_text, transcript_sha256, taxonomy_version,
            blindness_policy_version, playback_reference_id, packet_sha256,
            idempotency_key, expires_at, assignment_revision,
            supersedes_assignment_id, renewal_reason
        ) VALUES (
            practice.acquisition_principal_id, p_reviewer_principal_id,
            practice.project_id, practice.id, 'original_source', lineage.id,
            source_object.id, lineage.exact_audio_sha256,
            lineage.start_offset_ms, lineage.duration_ms,
            NULLIF(btrim(source_snippet.transcript), ''), source_transcript_hash,
            'confidence-five-state-v1', 'first-client-confidence-blind-v1',
            gen_random_uuid(), source_hash,
            p_idempotency_key || ':source:revision:' ||
                next_source_revision::TEXT,
            clock_timestamp() + INTERVAL '7 days', next_source_revision,
            prior_source.id, CASE WHEN prior_source.id IS NULL THEN NULL
                ELSE 'expired_unanswered_successor' END
        ) RETURNING * INTO source_assignment;
    ELSE
        source_assignment := prior_source;
    END IF;
    IF renew_practice THEN
        INSERT INTO public.exercise_service_confidence_assignments (
            acquisition_principal_id, reviewer_principal_id, project_id,
            practice_session_id, evidence_kind, practice_attempt_id,
            processing_audio_object_id, exact_audio_sha256, start_offset_ms,
            duration_ms, transcript_text, transcript_sha256, taxonomy_version,
            blindness_policy_version, playback_reference_id, packet_sha256,
            idempotency_key, expires_at, assignment_revision,
            supersedes_assignment_id, renewal_reason
        ) VALUES (
            practice.acquisition_principal_id, p_reviewer_principal_id,
            practice.project_id, practice.id, 'first_valid_practice', attempt.id,
            practice_object.id, attempt.exact_audio_sha256, 0,
            attempt.duration_ms, NULLIF(btrim(attempt.transcript_text), ''),
            practice_transcript_hash, 'confidence-five-state-v1',
            'first-client-confidence-blind-v1', gen_random_uuid(), practice_hash,
            p_idempotency_key || ':practice:revision:' ||
                next_practice_revision::TEXT,
            clock_timestamp() + INTERVAL '7 days', next_practice_revision,
            prior_practice.id, CASE WHEN prior_practice.id IS NULL THEN NULL
                ELSE 'expired_unanswered_successor' END
        ) RETURNING * INTO practice_assignment;
    ELSE
        practice_assignment := prior_practice;
    END IF;
    IF source_assignment.packet_sha256 <> source_hash
       OR practice_assignment.packet_sha256 <> practice_hash
       OR practice_assignment.practice_attempt_id <> attempt.id
    THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_REVIEW_REPLAY_CONFLICT';
    END IF;
    set_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'practice_session_id', practice.id,
        'acquisition_principal_id', practice.acquisition_principal_id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'source_assignment_id', source_assignment.id,
        'source_packet_sha256', source_assignment.packet_sha256,
        'practice_assignment_id', practice_assignment.id,
        'practice_packet_sha256', practice_assignment.packet_sha256,
        'review_revision', next_set_revision,
        'selection_revision_id', selection.id,
        'selection_inventory_sha256', selection.inventory_sha256
    ));
    INSERT INTO public.exercise_service_blind_review_sets (
        acquisition_principal_id, reviewer_principal_id,
        practice_session_id, source_audio_lineage_id, practice_attempt_id,
        source_confidence_assignment_id, practice_confidence_assignment_id,
        review_set_sha256, idempotency_key, review_revision,
        supersedes_review_set_id
    ) VALUES (
        practice.acquisition_principal_id, p_reviewer_principal_id,
        practice.id, lineage.id, attempt.id, source_assignment.id,
        practice_assignment.id, set_hash, persisted_key, next_set_revision,
        prior_set.id
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.ack_exercise_service_confidence_render_v1(
    p_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_render_instance_id UUID,
    p_packet_sha256 TEXT,
    p_rendered_at TIMESTAMPTZ,
    p_client_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_confidence_render_receipts
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    assignment public.exercise_service_confidence_assignments;
    existing public.exercise_service_confidence_render_receipts;
    receipt_hash TEXT;
BEGIN
    IF p_packet_sha256 !~ '^[0-9a-f]{64}$'
       OR COALESCE(btrim(p_client_version), '') = ''
       OR COALESCE(btrim(p_idempotency_key), '') = ''
       OR p_rendered_at > clock_timestamp() + INTERVAL '5 minutes'
    THEN RAISE EXCEPTION 'EXERCISE_SERVICE_REVIEW_RENDER_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-review-render:' || p_idempotency_key, 0
    ));
    assignment := public.require_exercise_service_confidence_live_v1(
        p_assignment_id, p_reviewer_principal_id
    );
    IF assignment.packet_sha256 <> p_packet_sha256 THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_REVIEW_RENDER_MISMATCH';
    END IF;
    receipt_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'assignment_id', assignment.id,
        'packet_sha256', assignment.packet_sha256,
        'reviewer_principal_id', p_reviewer_principal_id,
        'render_instance_id', p_render_instance_id,
        'rendered_at', p_rendered_at,
        'client_version', p_client_version
    ));
    SELECT * INTO existing
      FROM public.exercise_service_confidence_render_receipts row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.receipt_sha256 <> receipt_hash THEN
            RAISE EXCEPTION 'EXERCISE_SERVICE_REVIEW_RENDER_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_service_confidence_render_receipts (
        assignment_id, acquisition_principal_id, reviewer_principal_id,
        render_instance_id, packet_sha256, rendered_at, client_version,
        receipt_sha256, idempotency_key
    ) VALUES (
        assignment.id, assignment.acquisition_principal_id,
        p_reviewer_principal_id, p_render_instance_id,
        assignment.packet_sha256, p_rendered_at, p_client_version,
        receipt_hash, p_idempotency_key
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.submit_exercise_service_confidence_judgment_v1(
    p_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_render_receipt_id UUID,
    p_decision TEXT,
    p_decided_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_confidence_judgments
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    assignment public.exercise_service_confidence_assignments;
    receipt public.exercise_service_confidence_render_receipts;
    existing public.exercise_service_confidence_judgments;
    judgment_hash TEXT;
BEGIN
    IF p_decision NOT IN (
        'rating_yes', 'rating_in_between', 'rating_no',
        'rating_not_sure', 'rating_audio_unclear'
    ) OR COALESCE(btrim(p_idempotency_key), '') = ''
      OR p_decided_at > clock_timestamp() + INTERVAL '5 minutes'
    THEN RAISE EXCEPTION 'EXERCISE_SERVICE_REVIEW_JUDGMENT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-review-judgment:' || p_assignment_id::TEXT, 0
    ));
    assignment := public.require_exercise_service_confidence_live_v1(
        p_assignment_id, p_reviewer_principal_id
    );
    SELECT * INTO STRICT receipt
      FROM public.exercise_service_confidence_render_receipts row
     WHERE row.id = p_render_receipt_id
       AND row.assignment_id = assignment.id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.packet_sha256 = assignment.packet_sha256;
    judgment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'assignment_id', assignment.id,
        'packet_sha256', assignment.packet_sha256,
        'render_receipt_id', receipt.id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'decision', p_decision,
        'taxonomy_version', 'confidence-five-state-v1',
        'actor_provenance', 'blind_coach'
    ));
    SELECT * INTO existing
      FROM public.exercise_service_confidence_judgments row
     WHERE row.assignment_id = assignment.id
        OR row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.assignment_id <> assignment.id
           OR existing.render_receipt_id <> receipt.id
           OR existing.decision <> p_decision
           OR existing.judgment_sha256 <> judgment_hash
        THEN
            RAISE EXCEPTION 'EXERCISE_SERVICE_REVIEW_JUDGMENT_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    assignment := public.require_exercise_service_confidence_live_v1(
        assignment.id, p_reviewer_principal_id
    );
    INSERT INTO public.exercise_service_confidence_judgments (
        assignment_id, acquisition_principal_id, reviewer_principal_id,
        render_receipt_id, decision, actor_provenance, taxonomy_version,
        judgment_sha256, idempotency_key, decided_at
    ) VALUES (
        assignment.id, assignment.acquisition_principal_id,
        p_reviewer_principal_id, receipt.id, p_decision, 'blind_coach',
        'confidence-five-state-v1', judgment_hash, p_idempotency_key,
        p_decided_at
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.complete_exercise_service_blind_review_v1(
    p_review_set_id UUID,
    p_reviewer_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_blind_reveal_grants
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    review_set public.exercise_service_blind_review_sets;
    source_judgment public.exercise_service_confidence_judgments;
    practice_judgment public.exercise_service_confidence_judgments;
    existing public.exercise_service_blind_reveal_grants;
    inventory_hash TEXT;
    grant_hash TEXT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_REVEAL_KEY_REQUIRED';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-review-complete:' || p_review_set_id::TEXT, 0
    ));
    SELECT * INTO STRICT review_set
      FROM public.exercise_service_blind_review_sets row
     WHERE row.id = p_review_set_id
       AND row.reviewer_principal_id = p_reviewer_principal_id;
    PERFORM public.require_exercise_service_confidence_live_v1(
        review_set.source_confidence_assignment_id, p_reviewer_principal_id
    );
    PERFORM public.require_exercise_service_confidence_live_v1(
        review_set.practice_confidence_assignment_id, p_reviewer_principal_id
    );
    SELECT * INTO STRICT source_judgment
      FROM public.exercise_service_confidence_judgments row
     WHERE row.assignment_id = review_set.source_confidence_assignment_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.actor_provenance = 'blind_coach';
    SELECT * INTO STRICT practice_judgment
      FROM public.exercise_service_confidence_judgments row
     WHERE row.assignment_id = review_set.practice_confidence_assignment_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.actor_provenance = 'blind_coach';
    inventory_hash := public.exercise_json_sha256_v1(jsonb_build_array(
        jsonb_build_object('kind', 'original_source',
                           'judgment_id', source_judgment.id,
                           'judgment_sha256', source_judgment.judgment_sha256),
        jsonb_build_object('kind', 'first_valid_practice',
                           'judgment_id', practice_judgment.id,
                           'judgment_sha256', practice_judgment.judgment_sha256)
    ));
    grant_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'review_set_id', review_set.id,
        'review_set_sha256', review_set.review_set_sha256,
        'reviewer_principal_id', p_reviewer_principal_id,
        'judgment_inventory_sha256', inventory_hash
    ));
    SELECT * INTO existing
      FROM public.exercise_service_blind_reveal_grants row
     WHERE row.review_set_id = review_set.id
        OR row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.grant_sha256 <> grant_hash THEN
            RAISE EXCEPTION 'EXERCISE_SERVICE_REVEAL_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_service_blind_reveal_grants (
        review_set_id, acquisition_principal_id, reviewer_principal_id,
        source_judgment_id, practice_judgment_id,
        judgment_inventory_sha256, grant_sha256, idempotency_key
    ) VALUES (
        review_set.id, review_set.acquisition_principal_id,
        p_reviewer_principal_id, source_judgment.id, practice_judgment.id,
        inventory_hash, grant_hash, p_idempotency_key
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.access_exercise_service_blind_reveal_v1(
    p_reveal_grant_id UUID,
    p_reviewer_principal_id UUID,
    p_assignment_id UUID,
    p_access_purpose TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_service_blind_reveal_accesses
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    grant_row public.exercise_service_blind_reveal_grants;
    review_set public.exercise_service_blind_review_sets;
    judgment public.exercise_service_confidence_judgments;
    existing public.exercise_service_blind_reveal_accesses;
    access_hash TEXT;
BEGIN
    IF p_access_purpose NOT IN ('acoustic_reference', 'guidance_authoring')
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN RAISE EXCEPTION 'EXERCISE_SERVICE_REVEAL_ACCESS_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-reveal-access:' || p_idempotency_key, 0
    ));
    SELECT * INTO STRICT grant_row
      FROM public.exercise_service_blind_reveal_grants row
     WHERE row.id = p_reveal_grant_id
       AND row.reviewer_principal_id = p_reviewer_principal_id;
    SELECT * INTO STRICT review_set
      FROM public.exercise_service_blind_review_sets row
     WHERE row.id = grant_row.review_set_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND p_assignment_id IN (
           row.source_confidence_assignment_id,
           row.practice_confidence_assignment_id
       );
    SELECT * INTO STRICT judgment
      FROM public.exercise_service_confidence_judgments row
     WHERE row.assignment_id = p_assignment_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.id IN (grant_row.source_judgment_id,
                      grant_row.practice_judgment_id);
    PERFORM public.require_exercise_service_confidence_live_v1(
        p_assignment_id, p_reviewer_principal_id
    );
    access_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'reveal_grant_id', grant_row.id,
        'review_set_id', review_set.id,
        'assignment_id', p_assignment_id,
        'judgment_id', judgment.id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'access_purpose', p_access_purpose
    ));
    SELECT * INTO existing
      FROM public.exercise_service_blind_reveal_accesses row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.access_sha256 <> access_hash THEN
            RAISE EXCEPTION 'EXERCISE_SERVICE_REVEAL_ACCESS_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_service_blind_reveal_accesses (
        reveal_grant_id, acquisition_principal_id, reviewer_principal_id,
        assignment_id, judgment_id, access_purpose, access_sha256,
        idempotency_key
    ) VALUES (
        grant_row.id, grant_row.acquisition_principal_id,
        p_reviewer_principal_id, p_assignment_id, judgment.id,
        p_access_purpose, access_hash, p_idempotency_key
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

-- ── Owner before/after preference on the canonical pair tables ────────────
-- Pair preference is a subjective product-routing answer.  It is never a
-- confidence judgment, an improvement label, or dataset eligibility.  The
-- service path extends the released canonical pair records in place and does
-- not call any synthetic writer.
ALTER TABLE public.exercise_pair_revisions
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_pair_assignments
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;
ALTER TABLE public.exercise_pair_judgments
    ADD COLUMN IF NOT EXISTS operation_mode TEXT NOT NULL
        DEFAULT 'synthetic_dark',
    ADD COLUMN IF NOT EXISTS service_contract_version TEXT NULL,
    ADD COLUMN IF NOT EXISTS service_identity_sha256 TEXT NULL;

ALTER TABLE public.exercise_pair_revisions
    DROP CONSTRAINT IF EXISTS exercise_pair_revisions_operation_mode_check;
ALTER TABLE public.exercise_pair_revisions
    ADD CONSTRAINT exercise_pair_revisions_operation_mode_check CHECK (
        operation_mode IN ('synthetic_dark', 'allowlisted_service')
        AND ((operation_mode = 'synthetic_dark'
              AND service_contract_version IS NULL
              AND service_identity_sha256 IS NULL)
             OR (operation_mode = 'allowlisted_service'
                 AND service_contract_version = 'mlc3-first-client-service-v1'
                 AND service_identity_sha256 ~ '^[0-9a-f]{64}$'))
        AND NOT serves_user AND NOT dataset_eligible
    );
ALTER TABLE public.exercise_pair_assignments
    DROP CONSTRAINT IF EXISTS exercise_pair_assignments_operation_mode_check;
ALTER TABLE public.exercise_pair_assignments
    ADD CONSTRAINT exercise_pair_assignments_operation_mode_check CHECK (
        operation_mode IN ('synthetic_dark', 'allowlisted_service')
        AND ((operation_mode = 'synthetic_dark'
              AND service_contract_version IS NULL
              AND service_identity_sha256 IS NULL)
             OR (operation_mode = 'allowlisted_service'
                 AND service_contract_version = 'mlc3-first-client-service-v1'
                 AND service_identity_sha256 ~ '^[0-9a-f]{64}$'))
        AND NOT serves_user AND NOT dataset_eligible
    );
ALTER TABLE public.exercise_pair_judgments
    DROP CONSTRAINT IF EXISTS exercise_pair_judgments_operation_mode_check;
ALTER TABLE public.exercise_pair_judgments
    ADD CONSTRAINT exercise_pair_judgments_operation_mode_check CHECK (
        operation_mode IN ('synthetic_dark', 'allowlisted_service')
        AND ((operation_mode = 'synthetic_dark'
              AND service_contract_version IS NULL
              AND service_identity_sha256 IS NULL)
             OR (operation_mode = 'allowlisted_service'
                 AND service_contract_version = 'mlc3-first-client-service-v1'
                 AND service_identity_sha256 ~ '^[0-9a-f]{64}$'))
        AND NOT serves_user AND NOT dataset_eligible
    );

CREATE OR REPLACE FUNCTION public.freeze_exercise_service_pair_v1(
    p_practice_session_id UUID,
    p_acquisition_principal_id UUID,
    p_selection_revision_id UUID,
    p_comparison_revision INTEGER,
    p_idempotency_key TEXT
) RETURNS public.exercise_pair_revisions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    practice public.exercise_practice_sessions;
    selection public.exercise_practice_selection_revisions;
    attempt public.exercise_practice_attempts;
    existing public.exercise_pair_revisions;
    pair_hash TEXT;
BEGIN
    IF p_comparison_revision < 1
       OR COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_PAIR_INVALID';
    END IF;
    practice := public.require_exercise_practice_service_live_v1(
        p_practice_session_id, p_acquisition_principal_id
    );
    SELECT * INTO STRICT selection
      FROM public.exercise_practice_selection_revisions row
     WHERE row.id = p_selection_revision_id
       AND row.session_id = practice.id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.baseline_revision = practice.baseline_revision
       AND row.selection_state = 'selected_first_valid';
    SELECT * INTO STRICT attempt
      FROM public.exercise_practice_attempts row
     WHERE row.id = selection.selected_attempt_id
       AND row.session_id = practice.id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service';
    pair_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'acquisition_principal_id', p_acquisition_principal_id,
        'practice_session_id', practice.id,
        'source_audio_lineage_id', practice.source_audio_lineage_id,
        'selection_revision_id', selection.id,
        'selection_inventory_sha256', selection.inventory_sha256,
        'practice_attempt_id', attempt.id,
        'practice_audio_sha256', attempt.exact_audio_sha256,
        'comparison_revision', p_comparison_revision,
        'operation_mode', 'allowlisted_service',
        'service_contract_version', 'mlc3-first-client-service-v1'
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'exercise-service-pair:' || p_idempotency_key, 0
    ));
    practice := public.require_exercise_practice_service_live_v1(
        p_practice_session_id, p_acquisition_principal_id
    );
    SELECT * INTO existing FROM public.exercise_pair_revisions row
     WHERE row.idempotency_key = p_idempotency_key;
    IF existing.id IS NOT NULL THEN
        IF existing.operation_mode <> 'allowlisted_service'
           OR existing.acquisition_principal_id <> p_acquisition_principal_id
           OR existing.practice_session_id <> practice.id
           OR existing.selection_revision_id <> selection.id
           OR existing.practice_attempt_id <> attempt.id
           OR existing.pair_sha256 <> pair_hash
           OR existing.service_identity_sha256 <> pair_hash THEN
            RAISE EXCEPTION 'EXERCISE_PAIR_REPLAY_CONFLICT';
        END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_pair_revisions (
        acquisition_principal_id, practice_session_id,
        source_audio_lineage_id, selection_revision_id,
        practice_attempt_id, comparison_revision, pair_sha256,
        idempotency_key, operation_mode, service_contract_version,
        service_identity_sha256
    ) VALUES (
        p_acquisition_principal_id, practice.id,
        practice.source_audio_lineage_id, selection.id, attempt.id,
        p_comparison_revision, pair_hash, p_idempotency_key,
        'allowlisted_service', 'mlc3-first-client-service-v1', pair_hash
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.assign_exercise_service_owner_pair_v1(
    p_pair_revision_id UUID,
    p_acquisition_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.exercise_pair_assignments
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    pair_row public.exercise_pair_revisions;
    practice public.exercise_practice_sessions;
    existing public.exercise_pair_assignments;
    assignment_hash TEXT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key), '') = '' THEN
        RAISE EXCEPTION 'EXERCISE_PAIR_ASSIGNMENT_INVALID';
    END IF;
    SELECT * INTO STRICT pair_row FROM public.exercise_pair_revisions row
     WHERE row.id = p_pair_revision_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service';
    practice := public.require_exercise_practice_service_live_v1(
        pair_row.practice_session_id, p_acquisition_principal_id
    );
    assignment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'pair_revision_id', pair_row.id,
        'pair_sha256', pair_row.pair_sha256,
        'reviewer_principal_id', p_acquisition_principal_id,
        'reviewer_role', 'owner',
        'left_clip', 'before',
        'right_clip', 'after',
        'context_state', 'owner_nonblind',
        'order_policy_version', 'paired-preference-order-v1',
        'operation_mode', 'allowlisted_service',
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
        IF existing.operation_mode <> 'allowlisted_service'
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
        p_idempotency_key, 'allowlisted_service',
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
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    assignment public.exercise_pair_assignments;
    pair_row public.exercise_pair_revisions;
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
       AND row.reviewer_role = 'owner'
       AND row.operation_mode = 'allowlisted_service';
    SELECT * INTO STRICT pair_row FROM public.exercise_pair_revisions row
     WHERE row.id = assignment.pair_revision_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service';
    PERFORM public.require_exercise_practice_service_live_v1(
        pair_row.practice_session_id, p_acquisition_principal_id
    );
    judgment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'pair_assignment_id', assignment.id,
        'assignment_sha256', assignment.assignment_sha256,
        'reviewer_principal_id', p_acquisition_principal_id,
        'answer', p_answer,
        'answer_taxonomy_version',
            'paired-listening-preference-five-state-v1',
        'operation_mode', 'allowlisted_service',
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
        IF existing.operation_mode <> 'allowlisted_service'
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
        'allowlisted_service', 'mlc3-first-client-service-v1', judgment_hash
    ) RETURNING * INTO existing;
    RETURN existing;
END;
$$;

-- Resolve one post-blind service authoring context from authoritative rows.
-- The historical service snapshot is acquisition evidence; its receipt is
-- revalidated for the operation-specific live purpose on every call.
CREATE OR REPLACE FUNCTION public.require_coach_guidance_service_access_v1(
    p_reveal_access_id UUID,
    p_reviewer_principal_id UUID,
    p_purpose_id TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    access_row public.exercise_service_blind_reveal_accesses;
    grant_row public.exercise_service_blind_reveal_grants;
    review_set public.exercise_service_blind_review_sets;
    assignment public.exercise_service_confidence_assignments;
    judgment public.exercise_service_confidence_judgments;
    practice public.exercise_practice_sessions;
    offer public.exercise_service_offers;
    receipt public.exercise_service_acquisition_receipts;
    snapshot public.processing_authorization_snapshots;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_REQUIRES_READ_COMMITTED';
    END IF;
    IF p_purpose_id NOT IN (
        'coach_review', 'personalized_exercise_recommendation'
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_PURPOSE_INVALID'; END IF;
    PERFORM public.require_coach_guidance_reviewer_access_v1(
        p_reviewer_principal_id
    );
    SELECT * INTO STRICT access_row
      FROM public.exercise_service_blind_reveal_accesses row
     WHERE row.id = p_reveal_access_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.access_purpose = 'guidance_authoring';
    SELECT * INTO STRICT grant_row
      FROM public.exercise_service_blind_reveal_grants row
     WHERE row.id = access_row.reveal_grant_id
       AND row.acquisition_principal_id = access_row.acquisition_principal_id
       AND row.reviewer_principal_id = p_reviewer_principal_id;
    SELECT * INTO STRICT review_set
      FROM public.exercise_service_blind_review_sets row
     WHERE row.id = grant_row.review_set_id
       AND row.acquisition_principal_id = grant_row.acquisition_principal_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.source_confidence_assignment_id = access_row.assignment_id;
    SELECT * INTO STRICT assignment
      FROM public.exercise_service_confidence_assignments row
     WHERE row.id = access_row.assignment_id
       AND row.evidence_kind = 'original_source'
       AND row.source_audio_lineage_id = review_set.source_audio_lineage_id
       AND row.acquisition_principal_id = grant_row.acquisition_principal_id
       AND row.reviewer_principal_id = p_reviewer_principal_id;
    SELECT * INTO STRICT judgment
      FROM public.exercise_service_confidence_judgments row
     WHERE row.id = access_row.judgment_id
       AND row.assignment_id = assignment.id
       AND row.id = grant_row.source_judgment_id
       AND row.actor_provenance = 'blind_coach';
    assignment := public.require_exercise_service_confidence_live_v1(
        assignment.id, p_reviewer_principal_id
    );
    practice := public.require_exercise_practice_service_live_v1(
        review_set.practice_session_id, grant_row.acquisition_principal_id
    );
    SELECT * INTO STRICT offer
      FROM public.exercise_service_offers row
     WHERE row.id = practice.source_offer_id
       AND row.acquisition_principal_id = grant_row.acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.serves_user AND NOT row.dataset_eligible;
    SELECT * INTO STRICT receipt
      FROM public.exercise_service_acquisition_receipts row
     WHERE row.id = practice.source_acquisition_receipt_id
       AND row.acquisition_principal_id = grant_row.acquisition_principal_id
       AND row.acquisition_kind = 'source_recording';
    SELECT * INTO STRICT snapshot
      FROM public.processing_authorization_snapshots row
     WHERE row.id = receipt.service_authorization_snapshot_id
       AND row.acquisition_principal_id = grant_row.acquisition_principal_id;
    PERFORM public.require_coach_guidance_receipt_authority_v1(
        snapshot.receipt_id, grant_row.acquisition_principal_id, p_purpose_id
    );
    PERFORM public.require_mlc3_service_principal_v1(
        grant_row.acquisition_principal_id
    );
    RETURN jsonb_build_object(
        'acquisition_principal_id', grant_row.acquisition_principal_id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'review_set_id', review_set.id,
        'reveal_grant_id', grant_row.id,
        'reveal_access_id', access_row.id,
        'source_assignment_id', assignment.id,
        'source_judgment_id', judgment.id,
        'practice_session_id', practice.id,
        'offer_id', offer.id,
        'feedback_membership_id', offer.feedback_membership_id,
        'feedback_candidate_id', offer.feedback_candidate_id,
        'need_contract_id', (
            SELECT candidate_set.need_contract_id
              FROM public.exercise_candidate_sets candidate_set
             WHERE candidate_set.id = offer.n1_candidate_set_id
        ),
        'authorization_snapshot_id', snapshot.id,
        'authorization_receipt_id', snapshot.receipt_id
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.reserve_coach_guidance_service_upload_v1(
    p_reveal_access_id UUID,
    p_reviewer_principal_id UUID,
    p_purpose_id TEXT,
    p_bucket TEXT,
    p_object_key TEXT,
    p_intended_exact_bytes_sha256 TEXT,
    p_intended_byte_size BIGINT,
    p_content_type TEXT,
    p_expires_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_upload_permits
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    context JSONB;
    permit_hash TEXT;
    recovery_hash TEXT;
    result public.coach_guidance_upload_permits;
    recovery public.coach_guidance_upload_recoveries;
BEGIN
    IF p_purpose_id NOT IN (
        'coach_review', 'personalized_exercise_recommendation'
    ) OR COALESCE(btrim(p_bucket), '') = ''
       OR COALESCE(btrim(p_object_key), '') = ''
       OR p_intended_exact_bytes_sha256 !~ '^[0-9a-f]{64}$'
       OR p_intended_byte_size <= 0 OR p_content_type NOT LIKE 'video/%'
       OR p_expires_at <= clock_timestamp()
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 170
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-service-upload:' || p_idempotency_key, 0
    ));
    context := public.require_coach_guidance_service_access_v1(
        p_reveal_access_id, p_reviewer_principal_id, p_purpose_id
    );
    permit_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'service_contract_version', 'mlc3-first-client-service-v1',
        'reveal_access_id', p_reveal_access_id,
        'reviewer_principal_id', p_reviewer_principal_id,
        'acquisition_principal_id', context->>'acquisition_principal_id',
        'authorization_snapshot_id', context->>'authorization_snapshot_id',
        'purpose_id', p_purpose_id, 'storage_provider', 'r2',
        'bucket', p_bucket, 'object_key', p_object_key,
        'intended_exact_bytes_sha256', p_intended_exact_bytes_sha256,
        'intended_byte_size', p_intended_byte_size,
        'content_type', p_content_type, 'expires_at', p_expires_at
    ));
    SELECT * INTO result FROM public.coach_guidance_upload_permits row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.operation_mode <> 'allowlisted_service'
           OR result.service_reveal_access_id <> p_reveal_access_id
           OR result.permit_sha256 <> permit_hash
           OR NOT EXISTS (
               SELECT 1 FROM public.coach_guidance_upload_recoveries row
                WHERE row.upload_permit_id = result.id
                  AND row.operation_mode = 'allowlisted_service'
           )
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_upload_permits (
        acquisition_principal_id, reviewer_principal_id, reveal_access_id,
        service_reveal_access_id, authorization_snapshot_id, purpose_id,
        storage_provider, bucket, object_key,
        intended_exact_bytes_sha256, intended_byte_size, content_type,
        expires_at, permit_sha256, idempotency_key, synthetic_only,
        operation_mode, service_contract_version
    ) VALUES (
        (context->>'acquisition_principal_id')::UUID,
        p_reviewer_principal_id, NULL, p_reveal_access_id,
        (context->>'authorization_snapshot_id')::UUID, p_purpose_id,
        'r2', p_bucket, p_object_key, p_intended_exact_bytes_sha256,
        p_intended_byte_size, p_content_type, p_expires_at, permit_hash,
        p_idempotency_key, false, 'allowlisted_service',
        'mlc3-first-client-service-v1'
    ) RETURNING * INTO result;
    recovery_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'upload_permit_id', result.id,
        'acquisition_principal_id', result.acquisition_principal_id,
        'bucket', result.bucket, 'object_key', result.object_key,
        'intended_exact_bytes_sha256', result.intended_exact_bytes_sha256
    ));
    INSERT INTO public.coach_guidance_upload_recoveries (
        upload_permit_id, acquisition_principal_id, storage_provider, bucket,
        object_key, intended_exact_bytes_sha256, recovery_sha256,
        synthetic_only, operation_mode, service_contract_version
    ) VALUES (
        result.id, result.acquisition_principal_id, 'r2', result.bucket,
        result.object_key, result.intended_exact_bytes_sha256, recovery_hash,
        false, 'allowlisted_service', 'mlc3-first-client-service-v1'
    ) RETURNING * INTO recovery;
    INSERT INTO public.coach_guidance_upload_events (
        upload_recovery_id, upload_permit_id, acquisition_principal_id,
        event_kind, event_sha256, idempotency_key, synthetic_only,
        operation_mode, service_contract_version
    ) VALUES (
        recovery.id, result.id, result.acquisition_principal_id, 'reserved',
        public.exercise_json_sha256_v1(jsonb_build_object(
            'operation_mode', 'allowlisted_service',
            'upload_recovery_id', recovery.id, 'event_kind', 'reserved',
            'recovery_sha256', recovery.recovery_sha256
        )), 'event:reserved:' || p_idempotency_key, false,
        'allowlisted_service', 'mlc3-first-client-service-v1'
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_coach_guidance_service_upload_event_v1(
    p_upload_permit_id UUID,
    p_reviewer_principal_id UUID,
    p_event_kind TEXT,
    p_exact_bytes_sha256 TEXT,
    p_byte_size BIGINT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_upload_events
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    permit public.coach_guidance_upload_permits;
    recovery public.coach_guidance_upload_recoveries;
    context JSONB;
    required_previous TEXT;
    event_hash TEXT;
    result public.coach_guidance_upload_events;
BEGIN
    IF p_event_kind NOT IN ('write_started', 'write_acknowledged')
       OR p_exact_bytes_sha256 !~ '^[0-9a-f]{64}$' OR p_byte_size <= 0
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_EVENT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-upload-permit:' || p_upload_permit_id::TEXT, 0
    ));
    SELECT * INTO STRICT permit FROM public.coach_guidance_upload_permits row
     WHERE row.id = p_upload_permit_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.intended_exact_bytes_sha256 = p_exact_bytes_sha256
       AND row.intended_byte_size = p_byte_size
       AND row.expires_at > clock_timestamp();
    SELECT * INTO STRICT recovery
      FROM public.coach_guidance_upload_recoveries row
     WHERE row.upload_permit_id = permit.id
       AND row.acquisition_principal_id = permit.acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service';
    context := public.require_coach_guidance_service_access_v1(
        permit.service_reveal_access_id, p_reviewer_principal_id,
        permit.purpose_id
    );
    required_previous := CASE p_event_kind
        WHEN 'write_started' THEN 'reserved'
        ELSE 'write_started' END;
    IF NOT EXISTS (
        SELECT 1 FROM public.coach_guidance_upload_events row
         WHERE row.upload_recovery_id = recovery.id
           AND row.event_kind = required_previous
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_EVENT_OUT_OF_ORDER'; END IF;
    event_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'upload_recovery_id', recovery.id,
        'upload_permit_id', permit.id,
        'event_kind', p_event_kind,
        'exact_bytes_sha256', p_exact_bytes_sha256,
        'byte_size', p_byte_size
    ));
    SELECT * INTO result FROM public.coach_guidance_upload_events row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.event_sha256 <> event_hash
           OR result.operation_mode <> 'allowlisted_service'
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_EVENT_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_upload_events (
        upload_recovery_id, upload_permit_id, acquisition_principal_id,
        event_kind, event_sha256, idempotency_key, synthetic_only,
        operation_mode, service_contract_version
    ) VALUES (
        recovery.id, permit.id, permit.acquisition_principal_id,
        p_event_kind, event_hash, p_idempotency_key, false,
        'allowlisted_service', 'mlc3-first-client-service-v1'
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_coach_guidance_service_media_v1(
    p_upload_permit_id UUID,
    p_reviewer_principal_id UUID,
    p_verification_method TEXT,
    p_independent_clean_media BOOLEAN,
    p_language_policy_version TEXT,
    p_safety_policy_version TEXT,
    p_rights_policy_version TEXT,
    p_content_review_version TEXT,
    p_review_evidence_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    permit public.coach_guidance_upload_permits;
    recovery public.coach_guidance_upload_recoveries;
    media public.exercise_media_objects;
    review_row public.coach_guidance_independent_media_reviews;
    binding public.coach_guidance_media_bindings;
    context JSONB;
    event_hash TEXT;
    binding_hash TEXT;
BEGIN
    IF p_verification_method <> 'read_after_write_sha256'
       OR COALESCE(btrim(p_language_policy_version), '') = ''
       OR COALESCE(btrim(p_safety_policy_version), '') = ''
       OR COALESCE(btrim(p_rights_policy_version), '') = ''
       OR COALESCE(btrim(p_content_review_version), '') = ''
       OR p_review_evidence_sha256 !~ '^[0-9a-f]{64}$'
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 170
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_FINALIZATION_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-upload-permit:' || p_upload_permit_id::TEXT, 0
    ));
    SELECT * INTO STRICT permit FROM public.coach_guidance_upload_permits row
     WHERE row.id = p_upload_permit_id
       AND row.reviewer_principal_id = p_reviewer_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.expires_at > clock_timestamp();
    SELECT * INTO STRICT recovery
      FROM public.coach_guidance_upload_recoveries row
     WHERE row.upload_permit_id = permit.id
       AND row.operation_mode = 'allowlisted_service';
    context := public.require_coach_guidance_service_access_v1(
        permit.service_reveal_access_id, p_reviewer_principal_id,
        permit.purpose_id
    );
    IF NOT EXISTS (
        SELECT 1 FROM public.coach_guidance_upload_events row
         WHERE row.upload_recovery_id = recovery.id
           AND row.event_kind = 'write_acknowledged'
           AND row.operation_mode = 'allowlisted_service'
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_UPLOAD_EVENT_OUT_OF_ORDER'; END IF;
    INSERT INTO public.exercise_media_objects (
        storage_provider, bucket, object_key, exact_bytes_sha256, byte_size,
        content_type, verification_method, verified_at, content_authority,
        created_by
    ) VALUES (
        'r2', permit.bucket, permit.object_key,
        permit.intended_exact_bytes_sha256, permit.intended_byte_size,
        permit.content_type, p_verification_method, clock_timestamp(),
        'coach_guidance_service_upload', p_reviewer_principal_id::TEXT
    ) ON CONFLICT (storage_provider, bucket, object_key) DO NOTHING;
    SELECT * INTO STRICT media FROM public.exercise_media_objects row
     WHERE row.storage_provider = 'r2' AND row.bucket = permit.bucket
       AND row.object_key = permit.object_key
       AND row.exact_bytes_sha256 = permit.intended_exact_bytes_sha256
       AND row.byte_size = permit.intended_byte_size
       AND row.content_type = permit.content_type;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-media-validity:' || media.id::TEXT, 0
    ));
    event_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'upload_recovery_id', recovery.id,
        'upload_permit_id', permit.id,
        'event_kind', 'finalized', 'media_object_id', media.id,
        'exact_bytes_sha256', media.exact_bytes_sha256
    ));
    INSERT INTO public.coach_guidance_upload_events (
        upload_recovery_id, upload_permit_id, acquisition_principal_id,
        event_kind, media_object_id, event_sha256, idempotency_key,
        synthetic_only, operation_mode, service_contract_version
    ) VALUES (
        recovery.id, permit.id, permit.acquisition_principal_id,
        'finalized', media.id, event_hash,
        'event:finalized:' || p_idempotency_key, false,
        'allowlisted_service', 'mlc3-first-client-service-v1'
    ) ON CONFLICT (upload_recovery_id, event_kind) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_upload_events row
         WHERE row.upload_recovery_id = recovery.id
           AND row.upload_permit_id = permit.id
           AND row.event_kind = 'finalized'
           AND row.media_object_id = media.id
           AND row.event_sha256 = event_hash
           AND row.operation_mode = 'allowlisted_service'
    ) THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_FINALIZATION_REPLAY_CONFLICT';
    END IF;
    INSERT INTO public.coach_guidance_media_validity_events (
        media_object_id, acquisition_principal_id, validity_state,
        reason_code, evidence_sha256, event_sha256, idempotency_key,
        synthetic_only, operation_mode, service_contract_version
    ) VALUES (
        media.id, permit.acquisition_principal_id, 'active',
        'upload_finalized', event_hash,
        public.exercise_json_sha256_v1(jsonb_build_object(
            'operation_mode', 'allowlisted_service',
            'media_object_id', media.id, 'state', 'active',
            'evidence_sha256', event_hash
        )), 'media-validity:' || p_idempotency_key, false,
        'allowlisted_service', 'mlc3-first-client-service-v1'
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_media_validity_events row
         WHERE row.idempotency_key = 'media-validity:' || p_idempotency_key
           AND row.media_object_id = media.id
           AND row.acquisition_principal_id = permit.acquisition_principal_id
           AND row.validity_state = 'active'
           AND row.evidence_sha256 = event_hash
           AND row.operation_mode = 'allowlisted_service'
    ) THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_VALIDITY_REPLAY_CONFLICT';
    END IF;
    IF p_independent_clean_media THEN
        INSERT INTO public.coach_guidance_independent_media_reviews (
            media_object_id, upload_permit_id, acquisition_principal_id,
            reviewer_principal_id, contains_user_audio,
            contains_user_transcript, contains_user_identity,
            contains_project_context, contains_unique_user_passage,
            language_policy_version, safety_policy_version,
            rights_policy_version, content_review_version,
            review_evidence_sha256, review_sha256, idempotency_key,
            synthetic_only, operation_mode, service_contract_version
        ) VALUES (
            media.id, permit.id, permit.acquisition_principal_id,
            p_reviewer_principal_id, false, false, false, false, false,
            p_language_policy_version, p_safety_policy_version,
            p_rights_policy_version, p_content_review_version,
            p_review_evidence_sha256,
            public.exercise_json_sha256_v1(jsonb_build_object(
                'operation_mode', 'allowlisted_service',
                'media_object_id', media.id,
                'upload_permit_id', permit.id,
                'reviewer_principal_id', p_reviewer_principal_id,
                'no_user_material', true,
                'review_evidence_sha256', p_review_evidence_sha256
            )), 'media-review:' || p_idempotency_key, false,
            'allowlisted_service', 'mlc3-first-client-service-v1'
        ) ON CONFLICT (media_object_id) DO NOTHING
        RETURNING * INTO review_row;
        IF review_row.id IS NULL THEN
            SELECT * INTO STRICT review_row
              FROM public.coach_guidance_independent_media_reviews row
             WHERE row.media_object_id = media.id
               AND row.reviewer_principal_id = p_reviewer_principal_id
               AND row.operation_mode = 'allowlisted_service';
        END IF;
    END IF;
    binding_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'media_object_id', media.id,
        'acquisition_principal_id', permit.acquisition_principal_id,
        'authorization_snapshot_id', permit.authorization_snapshot_id,
        'purpose_id', permit.purpose_id,
        'provenance_class', CASE WHEN p_independent_clean_media
            THEN 'independent_clean_media' ELSE 'user_scoped' END,
        'source_acquisition_principal_id', CASE WHEN p_independent_clean_media
            THEN NULL ELSE permit.acquisition_principal_id END,
        'independent_media_review_id', review_row.id,
        'upload_authorization_id', permit.id,
        'language_policy_version', p_language_policy_version,
        'safety_policy_version', p_safety_policy_version,
        'rights_policy_version', p_rights_policy_version,
        'content_review_version', p_content_review_version
    ));
    INSERT INTO public.coach_guidance_media_bindings (
        media_object_id, acquisition_principal_id,
        authorization_snapshot_id, purpose_id, provenance_class,
        source_acquisition_principal_id, independent_media_review_id,
        upload_authorization_id, language_policy_version,
        safety_policy_version, rights_policy_version,
        content_review_version, binding_sha256, idempotency_key,
        operation_mode, service_contract_version
    ) VALUES (
        media.id, permit.acquisition_principal_id,
        permit.authorization_snapshot_id, permit.purpose_id,
        CASE WHEN p_independent_clean_media
            THEN 'independent_clean_media' ELSE 'user_scoped' END,
        CASE WHEN p_independent_clean_media
            THEN NULL ELSE permit.acquisition_principal_id END,
        review_row.id, permit.id, p_language_policy_version,
        p_safety_policy_version, p_rights_policy_version,
        p_content_review_version, binding_hash,
        'media-binding:' || p_idempotency_key, 'allowlisted_service',
        'mlc3-first-client-service-v1'
    ) ON CONFLICT (idempotency_key) DO NOTHING RETURNING * INTO binding;
    IF binding.id IS NULL THEN
        SELECT * INTO STRICT binding
          FROM public.coach_guidance_media_bindings row
         WHERE row.idempotency_key = 'media-binding:' || p_idempotency_key
           AND row.binding_sha256 = binding_hash;
    END IF;
    context := public.require_coach_guidance_service_access_v1(
        permit.service_reveal_access_id, p_reviewer_principal_id,
        permit.purpose_id
    );
    RETURN jsonb_build_object(
        'media_object_id', media.id,
        'media_binding_id', binding.id,
        'exact_bytes_sha256', media.exact_bytes_sha256,
        'byte_size', media.byte_size,
        'bucket', media.bucket,
        'object_key', media.object_key,
        'provenance_class', binding.provenance_class
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.require_coach_guidance_service_media_live_v1(
    p_media_binding_id UUID,
    p_acquisition_principal_id UUID
) RETURNS public.coach_guidance_media_bindings
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    binding public.coach_guidance_media_bindings;
    permit public.coach_guidance_upload_permits;
    snapshot public.processing_authorization_snapshots;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'COACH_GUIDANCE_REQUIRES_READ_COMMITTED';
    END IF;
    SELECT * INTO STRICT binding
      FROM public.coach_guidance_media_bindings row
     WHERE row.id = p_media_binding_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.service_contract_version = 'mlc3-first-client-service-v1';
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-media-validity:' || binding.media_object_id::TEXT, 0
    ));
    SELECT * INTO STRICT permit
      FROM public.coach_guidance_upload_permits row
     WHERE row.id = binding.upload_authorization_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.service_reveal_access_id IS NOT NULL;
    SELECT * INTO STRICT snapshot
      FROM public.processing_authorization_snapshots row
     WHERE row.id = binding.authorization_snapshot_id
       AND row.acquisition_principal_id = p_acquisition_principal_id;
    PERFORM public.require_coach_guidance_receipt_authority_v1(
        snapshot.receipt_id, p_acquisition_principal_id, binding.purpose_id
    );
    PERFORM public.require_coach_guidance_service_access_v1(
        permit.service_reveal_access_id, permit.reviewer_principal_id,
        binding.purpose_id
    );
    IF NOT EXISTS (
        SELECT 1
          FROM public.exercise_media_objects media
          JOIN public.coach_guidance_upload_events upload_event
            ON upload_event.media_object_id = media.id
           AND upload_event.upload_permit_id = permit.id
           AND upload_event.event_kind = 'finalized'
           AND upload_event.operation_mode = 'allowlisted_service'
         WHERE media.id = binding.media_object_id
           AND media.exact_bytes_sha256 = permit.intended_exact_bytes_sha256
           AND media.byte_size = permit.intended_byte_size
           AND media.bucket = permit.bucket
           AND media.object_key = permit.object_key
    ) OR NOT EXISTS (
        SELECT 1
          FROM public.coach_guidance_media_validity_events current_event
         WHERE current_event.media_object_id = binding.media_object_id
           AND current_event.acquisition_principal_id =
               p_acquisition_principal_id
           AND current_event.validity_state = 'active'
           AND current_event.operation_mode = 'allowlisted_service'
           AND NOT EXISTS (
               SELECT 1
                 FROM public.coach_guidance_media_validity_events later
                WHERE later.previous_event_id = current_event.id
           )
    ) OR (binding.provenance_class <> 'independent_clean_media'
          AND binding.source_acquisition_principal_id IS DISTINCT FROM
              p_acquisition_principal_id)
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_NOT_LIVE'; END IF;
    RETURN binding;
END;
$$;

CREATE OR REPLACE FUNCTION public.create_coach_guidance_service_attachment_v1(
    p_reveal_access_id UUID,
    p_reviewer_principal_id UUID,
    p_feedback_membership_id UUID,
    p_feedback_candidate_id UUID,
    p_attachment_class TEXT,
    p_product_subcategory TEXT,
    p_written_note TEXT,
    p_media_binding_id UUID,
    p_exercise_offer_id UUID,
    p_exercise_version_id UUID,
    p_need_contract_id UUID,
    p_language_policy_version TEXT,
    p_safety_policy_version TEXT,
    p_rights_policy_version TEXT,
    p_content_review_version TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_attachment_versions
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    context JSONB;
    feedback_item public.feedback_v3_membership_items;
    offer public.exercise_service_offers;
    source_assignment public.exercise_service_confidence_assignments;
    binding public.coach_guidance_media_bindings;
    attachment public.coach_guidance_attachments;
    result public.coach_guidance_attachment_versions;
    authored public.coach_guidance_lifecycle_events;
    attachment_hash TEXT;
    version_hash TEXT;
    purpose_id TEXT;
BEGIN
    purpose_id := CASE WHEN p_attachment_class = 'mlc3_exercise'
        THEN 'personalized_exercise_recommendation' ELSE 'coach_review' END;
    IF p_attachment_class NOT IN (
        'general_product_guidance', 'mlc3_exercise'
    ) OR (p_product_subcategory IS NOT NULL
          AND p_product_subcategory NOT IN ('structure', 'delivery'))
       OR (NULLIF(btrim(COALESCE(p_written_note, '')), '') IS NULL
           AND p_media_binding_id IS NULL)
       OR COALESCE(btrim(p_language_policy_version), '') = ''
       OR COALESCE(btrim(p_safety_policy_version), '') = ''
       OR COALESCE(btrim(p_rights_policy_version), '') = ''
       OR COALESCE(btrim(p_content_review_version), '') = ''
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 170
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_ATTACHMENT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-service-attachment:' || p_idempotency_key, 0
    ));
    context := public.require_coach_guidance_service_access_v1(
        p_reveal_access_id, p_reviewer_principal_id, purpose_id
    );
    IF (context->>'feedback_membership_id')::UUID <>
           p_feedback_membership_id
       OR (p_attachment_class = 'mlc3_exercise'
           AND (context->>'feedback_candidate_id')::UUID <>
               p_feedback_candidate_id)
       OR (p_attachment_class = 'mlc3_exercise'
           AND (context->>'offer_id')::UUID IS DISTINCT FROM
               p_exercise_offer_id)
       OR (p_attachment_class = 'general_product_guidance'
           AND p_exercise_offer_id IS NOT NULL)
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_FEEDBACK_LINEAGE_MISMATCH'; END IF;
    SELECT * INTO STRICT feedback_item
      FROM public.feedback_v3_membership_items row
     WHERE row.membership_id = p_feedback_membership_id
       AND row.candidate_id = p_feedback_candidate_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.selected AND row.eligibility = 'eligible'
       AND row.serves_user AND NOT row.dataset_eligible;
    SELECT * INTO STRICT offer FROM public.exercise_service_offers row
     WHERE row.id = (context->>'offer_id')::UUID
       AND row.acquisition_principal_id =
           (context->>'acquisition_principal_id')::UUID
       AND row.feedback_membership_id = p_feedback_membership_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.serves_user AND NOT row.dataset_eligible;
    SELECT * INTO STRICT source_assignment
      FROM public.exercise_service_confidence_assignments row
     WHERE row.id = (context->>'source_assignment_id')::UUID
       AND (
           p_attachment_class = 'general_product_guidance'
           OR row.source_audio_lineage_id = (
           SELECT lineage.id FROM public.exercise_audio_lineages lineage
            WHERE lineage.id = row.source_audio_lineage_id
              AND lineage.snippet_id = feedback_item.snippet_id
           )
       );
    IF p_attachment_class = 'general_product_guidance' THEN
        IF p_exercise_offer_id IS NOT NULL
           OR p_exercise_version_id IS NOT NULL
           OR p_need_contract_id IS NOT NULL
        THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_GENERAL_EXERCISE_FIELDS_FORBIDDEN';
        END IF;
    ELSE
        IF feedback_item.feedback_family <> 'confident_voice'
           OR offer.feedback_candidate_id <> p_feedback_candidate_id
           OR p_product_subcategory IS NOT NULL
           OR p_need_contract_id IS DISTINCT FROM
               (context->>'need_contract_id')::UUID
           OR NOT EXISTS (
               SELECT 1 FROM public.exercise_need_contracts need
                WHERE need.id = p_need_contract_id
                  AND need.approval_state = 'approved'
           )
           OR NOT EXISTS (
               SELECT 1 FROM public.exercise_service_offer_candidates item
                WHERE item.offer_id = offer.id
                  AND item.operation_mode = 'allowlisted_service'
           )
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_MLC3_EXERCISE_INELIGIBLE'; END IF;
        IF offer.outcome = 'service_matched' AND (
            p_exercise_version_id IS DISTINCT FROM
                offer.selected_exercise_version_id
            OR NOT EXISTS (
                SELECT 1 FROM public.exercise_versions version_row
                 WHERE version_row.id = p_exercise_version_id
                   AND version_row.need_contract_id = p_need_contract_id
                   AND version_row.safety_state = 'approved'
                   AND version_row.catalogue_state = 'active'
            )
        ) OR offer.outcome = 'coach_exercise_requested'
             AND p_exercise_version_id IS NOT NULL
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_MLC3_EXERCISE_INELIGIBLE'; END IF;
    END IF;
    IF p_media_binding_id IS NOT NULL THEN
        binding := public.require_coach_guidance_service_media_live_v1(
            p_media_binding_id,
            (context->>'acquisition_principal_id')::UUID
        );
        IF binding.purpose_id <> purpose_id THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_MEDIA_PURPOSE_MISMATCH';
        END IF;
    END IF;
    attachment_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'service_contract_version', 'mlc3-first-client-service-v1',
        'review_set_id', context->>'review_set_id',
        'reveal_grant_id', context->>'reveal_grant_id',
        'reveal_access_id', p_reveal_access_id,
        'blind_judgment_id', context->>'source_judgment_id',
        'review_assignment_id', context->>'source_assignment_id',
        'feedback_membership_id', p_feedback_membership_id,
        'feedback_candidate_id', p_feedback_candidate_id,
        'attachment_class', p_attachment_class,
        'product_subcategory', p_product_subcategory,
        'exercise_offer_id', p_exercise_offer_id,
        'exercise_version_id', p_exercise_version_id,
        'need_contract_id', p_need_contract_id
    ));
    version_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'attachment_sha256', attachment_hash,
        'written_note', NULLIF(btrim(COALESCE(p_written_note, '')), ''),
        'media_binding_id', p_media_binding_id,
        'language_policy_version', p_language_policy_version,
        'safety_policy_version', p_safety_policy_version,
        'rights_policy_version', p_rights_policy_version,
        'content_review_version', p_content_review_version
    ));
    SELECT version_row.* INTO result
      FROM public.coach_guidance_attachment_versions version_row
      JOIN public.coach_guidance_attachments attachment_row
        ON attachment_row.id = version_row.attachment_id
     WHERE attachment_row.idempotency_key =
           'service-attachment:' || p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.version_sha256 <> version_hash
           OR result.operation_mode <> 'allowlisted_service'
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_ATTACHMENT_REPLAY_CONFLICT'; END IF;
        IF result.media_binding_id IS NOT NULL THEN
            PERFORM public.require_coach_guidance_service_media_live_v1(
                result.media_binding_id,
                (context->>'acquisition_principal_id')::UUID
            );
        END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_attachments (
        acquisition_principal_id, recipient_principal_id,
        author_principal_id, review_batch_id, reveal_grant_id,
        reveal_access_id, blind_judgment_id, review_assignment_id,
        service_review_set_id, service_reveal_grant_id,
        service_reveal_access_id, service_blind_judgment_id,
        service_review_assignment_id, feedback_membership_id,
        feedback_candidate_id, attachment_class, product_subcategory,
        exercise_offer_id, exercise_version_id, need_contract_id,
        authorization_snapshot_id, attachment_sha256, idempotency_key,
        operation_mode, service_contract_version
    ) VALUES (
        (context->>'acquisition_principal_id')::UUID,
        (context->>'acquisition_principal_id')::UUID,
        p_reviewer_principal_id, NULL, NULL, NULL, NULL, NULL,
        (context->>'review_set_id')::UUID,
        (context->>'reveal_grant_id')::UUID, p_reveal_access_id,
        (context->>'source_judgment_id')::UUID,
        (context->>'source_assignment_id')::UUID,
        p_feedback_membership_id, p_feedback_candidate_id,
        p_attachment_class, p_product_subcategory,
        CASE WHEN p_attachment_class = 'mlc3_exercise'
             THEN p_exercise_offer_id ELSE NULL END,
        p_exercise_version_id, p_need_contract_id,
        (context->>'authorization_snapshot_id')::UUID,
        attachment_hash, 'service-attachment:' || p_idempotency_key,
        'allowlisted_service', 'mlc3-first-client-service-v1'
    ) RETURNING * INTO attachment;
    INSERT INTO public.coach_guidance_attachment_versions (
        attachment_id, acquisition_principal_id, version_number,
        written_note, media_binding_id, language_policy_version,
        safety_policy_version, rights_policy_version,
        content_review_version, version_sha256, idempotency_key,
        serves_user, operation_mode, service_contract_version
    ) VALUES (
        attachment.id, attachment.acquisition_principal_id, 1,
        NULLIF(btrim(COALESCE(p_written_note, '')), ''), p_media_binding_id,
        p_language_policy_version, p_safety_policy_version,
        p_rights_policy_version, p_content_review_version, version_hash,
        'service-version:' || p_idempotency_key, true,
        'allowlisted_service', 'mlc3-first-client-service-v1'
    ) RETURNING * INTO result;
    INSERT INTO public.coach_guidance_lifecycle_events (
        attachment_version_id, acquisition_principal_id,
        actor_principal_id, authorization_snapshot_id, event_kind,
        event_payload, event_sha256, idempotency_key,
        synthetic_only, recipient_principal_id, operation_mode,
        service_contract_version
    ) VALUES (
        result.id, attachment.acquisition_principal_id,
        p_reviewer_principal_id, attachment.authorization_snapshot_id,
        'authored', jsonb_build_object(
            'service_review_assignment_id',
            attachment.service_review_assignment_id
        ), public.exercise_json_sha256_v1(jsonb_build_object(
            'operation_mode', 'allowlisted_service',
            'attachment_version_id', result.id,
            'event_kind', 'authored',
            'version_sha256', result.version_sha256
        )), 'service-event:authored:' || p_idempotency_key, false,
        attachment.recipient_principal_id, 'allowlisted_service',
        'mlc3-first-client-service-v1'
    ) RETURNING * INTO authored;
    INSERT INTO public.coach_guidance_lifecycle_events (
        attachment_version_id, acquisition_principal_id,
        actor_principal_id, authorization_snapshot_id, previous_event_id,
        event_kind, event_payload, event_sha256, idempotency_key,
        synthetic_only, recipient_principal_id, operation_mode,
        service_contract_version
    ) VALUES (
        result.id, attachment.acquisition_principal_id,
        p_reviewer_principal_id, attachment.authorization_snapshot_id,
        authored.id, 'assigned', jsonb_build_object(
            'feedback_membership_id', p_feedback_membership_id,
            'feedback_candidate_id', p_feedback_candidate_id
        ), public.exercise_json_sha256_v1(jsonb_build_object(
            'operation_mode', 'allowlisted_service',
            'attachment_version_id', result.id,
            'event_kind', 'assigned', 'previous_event_id', authored.id
        )), 'service-event:assigned:' || p_idempotency_key, false,
        attachment.recipient_principal_id, 'allowlisted_service',
        'mlc3-first-client-service-v1'
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_coach_guidance_service_event_v1(
    p_attachment_version_id UUID,
    p_recipient_principal_id UUID,
    p_event_kind TEXT,
    p_render_instance_id UUID,
    p_event_payload JSONB,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_lifecycle_events
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    attachment public.coach_guidance_attachments;
    version_row public.coach_guidance_attachment_versions;
    binding public.coach_guidance_media_bindings;
    context JSONB;
    required_previous TEXT;
    prior public.coach_guidance_lifecycle_events;
    event_hash TEXT;
    result public.coach_guidance_lifecycle_events;
BEGIN
    IF p_event_kind NOT IN ('delivered', 'rendered', 'played')
       OR (p_event_kind = 'rendered') <> (p_render_instance_id IS NOT NULL)
       OR jsonb_typeof(COALESCE(p_event_payload, '{}'::JSONB)) <> 'object'
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 200
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_EVENT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-event:' || p_attachment_version_id::TEXT, 0
    ));
    SELECT * INTO STRICT version_row
      FROM public.coach_guidance_attachment_versions row
     WHERE row.id = p_attachment_version_id
       AND row.acquisition_principal_id = p_recipient_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.serves_user AND NOT row.dataset_eligible;
    SELECT * INTO STRICT attachment
      FROM public.coach_guidance_attachments row
     WHERE row.id = version_row.attachment_id
       AND row.recipient_principal_id = p_recipient_principal_id
       AND row.operation_mode = 'allowlisted_service';
    context := public.require_coach_guidance_service_access_v1(
        attachment.service_reveal_access_id, attachment.author_principal_id,
        CASE WHEN attachment.attachment_class = 'mlc3_exercise'
            THEN 'personalized_exercise_recommendation'
            ELSE 'coach_review' END
    );
    IF version_row.media_binding_id IS NOT NULL THEN
        binding := public.require_coach_guidance_service_media_live_v1(
            version_row.media_binding_id, p_recipient_principal_id
        );
    END IF;
    required_previous := CASE p_event_kind
        WHEN 'delivered' THEN 'assigned'
        WHEN 'rendered' THEN 'delivered'
        ELSE 'rendered' END;
    SELECT * INTO STRICT prior
      FROM public.coach_guidance_lifecycle_events row
     WHERE row.attachment_version_id = version_row.id
       AND row.event_kind = required_previous
       AND row.operation_mode = 'allowlisted_service';
    event_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'attachment_version_id', version_row.id,
        'recipient_principal_id', p_recipient_principal_id,
        'event_kind', p_event_kind,
        'previous_event_id', prior.id,
        'render_instance_id', p_render_instance_id,
        'event_payload', COALESCE(p_event_payload, '{}'::JSONB)
    ));
    SELECT * INTO result FROM public.coach_guidance_lifecycle_events row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.event_sha256 <> event_hash
           OR result.operation_mode <> 'allowlisted_service'
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_EVENT_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    INSERT INTO public.coach_guidance_lifecycle_events (
        attachment_version_id, acquisition_principal_id,
        actor_principal_id, authorization_snapshot_id, previous_event_id,
        event_kind, event_payload, event_sha256, idempotency_key,
        synthetic_only, serves_user, recipient_principal_id,
        render_instance_id, operation_mode, service_contract_version
    ) VALUES (
        version_row.id, attachment.acquisition_principal_id,
        CASE WHEN p_event_kind = 'delivered'
            THEN attachment.author_principal_id
            ELSE p_recipient_principal_id END,
        attachment.authorization_snapshot_id, prior.id, p_event_kind,
        COALESCE(p_event_payload, '{}'::JSONB), event_hash,
        p_idempotency_key, false, true, p_recipient_principal_id,
        p_render_instance_id, 'allowlisted_service',
        'mlc3-first-client-service-v1'
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.resolve_coach_guidance_service_media_read_v1(
    p_attachment_version_id UUID,
    p_recipient_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    version_row public.coach_guidance_attachment_versions;
    attachment public.coach_guidance_attachments;
    binding public.coach_guidance_media_bindings;
    media public.exercise_media_objects;
BEGIN
    SELECT * INTO STRICT version_row
      FROM public.coach_guidance_attachment_versions row
     WHERE row.id = p_attachment_version_id
       AND row.acquisition_principal_id = p_recipient_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.serves_user AND NOT row.dataset_eligible
       AND row.media_binding_id IS NOT NULL;
    SELECT * INTO STRICT attachment
      FROM public.coach_guidance_attachments row
     WHERE row.id = version_row.attachment_id
       AND row.recipient_principal_id = p_recipient_principal_id
       AND row.operation_mode = 'allowlisted_service';
    binding := public.require_coach_guidance_service_media_live_v1(
        version_row.media_binding_id, p_recipient_principal_id
    );
    SELECT * INTO STRICT media
      FROM public.exercise_media_objects row
     WHERE row.id = binding.media_object_id
       AND row.storage_provider = 'r2'
       AND row.exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
       AND row.byte_size > 0;
    -- Recheck the complete live boundary immediately before returning the
    -- short-lived signed-read inputs. A stored or historical attachment alone
    -- never authorizes a provider read.
    PERFORM public.require_coach_guidance_service_media_live_v1(
        version_row.media_binding_id, p_recipient_principal_id
    );
    RETURN jsonb_build_object(
        'attachment_version_id', version_row.id,
        'recipient_principal_id', p_recipient_principal_id,
        'media_binding_id', binding.id,
        'media_object_id', media.id,
        'bucket', media.bucket,
        'object_key', media.object_key,
        'exact_bytes_sha256', media.exact_bytes_sha256,
        'byte_size', media.byte_size,
        'content_type', media.content_type
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.publish_coach_guidance_service_exercise_v1(
    p_source_attachment_version_id UUID,
    p_reviewer_principal_id UUID,
    p_exercise_key TEXT,
    p_language_code TEXT,
    p_instruction_text TEXT,
    p_idempotency_key TEXT
) RETURNS public.coach_guidance_publications
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    version_row public.coach_guidance_attachment_versions;
    attachment public.coach_guidance_attachments;
    binding public.coach_guidance_media_bindings;
    media_review public.coach_guidance_independent_media_reviews;
    definition public.exercise_definitions;
    exercise_version public.exercise_versions;
    snapshot public.exercise_catalog_snapshots;
    result public.coach_guidance_publications;
    context JSONB;
    next_version INTEGER;
    version_manifest JSONB;
    definition_hash TEXT;
    version_hash TEXT;
    snapshot_hash TEXT;
    publication_hash TEXT;
BEGIN
    IF p_exercise_key !~ '^[a-z0-9][a-z0-9_-]{2,119}$'
       OR p_language_code !~ '^[a-z]{2}(-[A-Z]{2})?$'
       OR COALESCE(btrim(p_instruction_text), '') = ''
       OR length(COALESCE(p_idempotency_key, '')) NOT BETWEEN 1 AND 160
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_PUBLICATION_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-service-publication:' || p_exercise_key, 0
    ));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'coach-guidance-service-publication-key:' || p_idempotency_key, 0
    ));
    SELECT * INTO result FROM public.coach_guidance_publications row
     WHERE row.idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.operation_mode <> 'allowlisted_service'
           OR result.source_attachment_version_id <>
              p_source_attachment_version_id
        THEN RAISE EXCEPTION 'COACH_GUIDANCE_PUBLICATION_REPLAY_CONFLICT'; END IF;
        SELECT * INTO STRICT version_row
          FROM public.coach_guidance_attachment_versions row
         WHERE row.id = result.source_attachment_version_id;
        SELECT * INTO STRICT attachment
          FROM public.coach_guidance_attachments row
         WHERE row.id = version_row.attachment_id;
        IF NOT EXISTS (
            SELECT 1
              FROM public.exercise_versions published_version
              JOIN public.exercise_definitions published_definition
                ON published_definition.id =
                   published_version.exercise_definition_id
             WHERE published_version.id = result.published_exercise_version_id
               AND published_definition.exercise_key = p_exercise_key
               AND published_definition.language_code = p_language_code
               AND published_version.instruction_text =
                   btrim(p_instruction_text)
        ) THEN
            RAISE EXCEPTION 'COACH_GUIDANCE_PUBLICATION_REPLAY_CONFLICT';
        END IF;
        context := public.require_coach_guidance_service_access_v1(
            attachment.service_reveal_access_id,
            p_reviewer_principal_id,
            'personalized_exercise_recommendation'
        );
        RETURN result;
    END IF;
    SELECT * INTO STRICT version_row
      FROM public.coach_guidance_attachment_versions row
     WHERE row.id = p_source_attachment_version_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.serves_user AND NOT row.dataset_eligible
       AND row.media_binding_id IS NOT NULL;
    SELECT * INTO STRICT attachment
      FROM public.coach_guidance_attachments row
     WHERE row.id = version_row.attachment_id
       AND row.author_principal_id = p_reviewer_principal_id
       AND row.attachment_class = 'mlc3_exercise'
       AND row.operation_mode = 'allowlisted_service';
    context := public.require_coach_guidance_service_access_v1(
        attachment.service_reveal_access_id, p_reviewer_principal_id,
        'personalized_exercise_recommendation'
    );
    binding := public.require_coach_guidance_service_media_live_v1(
        version_row.media_binding_id, attachment.acquisition_principal_id
    );
    IF binding.provenance_class <> 'independent_clean_media'
       OR binding.source_acquisition_principal_id IS NOT NULL
    THEN RAISE EXCEPTION 'COACH_GUIDANCE_PUBLICATION_CLEAN_MEDIA_REQUIRED'; END IF;
    SELECT * INTO STRICT media_review
      FROM public.coach_guidance_independent_media_reviews row
     WHERE row.id = binding.independent_media_review_id
       AND row.media_object_id = binding.media_object_id
       AND row.operation_mode = 'allowlisted_service'
       AND NOT row.contains_user_audio
       AND NOT row.contains_user_transcript
       AND NOT row.contains_user_identity
       AND NOT row.contains_project_context
       AND NOT row.contains_unique_user_passage;
    IF NOT EXISTS (
        SELECT 1 FROM public.exercise_need_contracts need
         WHERE need.id = attachment.need_contract_id
           AND need.approval_state = 'approved'
    ) THEN RAISE EXCEPTION 'COACH_GUIDANCE_PUBLICATION_NEED_NOT_APPROVED'; END IF;
    definition_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'exercise_key', p_exercise_key,
        'origin_kind', 'willab_library',
        'author_principal_id', p_reviewer_principal_id,
        'language_code', p_language_code
    ));
    INSERT INTO public.exercise_definitions (
        exercise_key, origin_kind, author_principal_id, language_code,
        definition_sha256, created_by
    ) VALUES (
        p_exercise_key, 'willab_library', p_reviewer_principal_id,
        p_language_code, definition_hash, p_reviewer_principal_id::TEXT
    ) ON CONFLICT (exercise_key) DO NOTHING;
    SELECT * INTO STRICT definition FROM public.exercise_definitions row
     WHERE row.exercise_key = p_exercise_key
       AND row.definition_sha256 = definition_hash;
    SELECT COALESCE(MAX(row.version_number), 0) + 1 INTO next_version
      FROM public.exercise_versions row
     WHERE row.exercise_definition_id = definition.id;
    version_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'exercise_definition_id', definition.id,
        'version_number', next_version,
        'need_contract_id', attachment.need_contract_id,
        'media_object_id', binding.media_object_id,
        'instruction_text', btrim(p_instruction_text),
        'language_policy_version', version_row.language_policy_version,
        'safety_policy_version', version_row.safety_policy_version,
        'rights_policy_version', version_row.rights_policy_version,
        'content_review_version', version_row.content_review_version,
        'source_attachment_version_id', version_row.id
    ));
    INSERT INTO public.exercise_versions (
        exercise_definition_id, version_number, need_contract_id,
        media_object_id, instruction_text, instruction_sha256,
        safety_state, catalogue_state, version_sha256, created_by
    ) VALUES (
        definition.id, next_version, attachment.need_contract_id,
        binding.media_object_id, btrim(p_instruction_text),
        public.exercise_json_sha256_v1(to_jsonb(btrim(p_instruction_text))),
        'approved', 'active', version_hash, p_reviewer_principal_id::TEXT
    ) RETURNING * INTO exercise_version;
    SELECT jsonb_agg(jsonb_build_object(
               'exercise_version_id', version_source.id,
               'exercise_key', definition_source.exercise_key,
               'version_number', version_source.version_number,
               'catalogue_state', version_source.catalogue_state,
               'safety_state', version_source.safety_state,
               'version_sha256', version_source.version_sha256
           ) ORDER BY definition_source.exercise_key,
                    version_source.version_number, version_source.id)
      INTO version_manifest
      FROM public.exercise_versions version_source
      JOIN public.exercise_definitions definition_source
        ON definition_source.id = version_source.exercise_definition_id
     WHERE definition_source.language_code = p_language_code;
    snapshot_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'catalog_policy_version', 'first-client-catalog-publication-v1',
        'scope_language_code', p_language_code,
        'complete_version_manifest', version_manifest
    ));
    INSERT INTO public.exercise_catalog_snapshots (
        catalog_policy_version, scope_language_code, version_cutoff_at,
        version_count, manifest_sha256, idempotency_key, created_by
    ) VALUES (
        'first-client-catalog-publication-v1', p_language_code,
        clock_timestamp(), jsonb_array_length(version_manifest),
        snapshot_hash, 'service-catalog:' || p_idempotency_key,
        p_reviewer_principal_id::TEXT
    ) RETURNING * INTO snapshot;
    INSERT INTO public.exercise_catalog_snapshot_items (
        catalog_snapshot_id, exercise_version_id, exercise_key,
        version_number, catalogue_state, safety_state, item_sha256
    )
    SELECT snapshot.id, version_source.id, definition_source.exercise_key,
           version_source.version_number, version_source.catalogue_state,
           version_source.safety_state,
           public.exercise_json_sha256_v1(jsonb_build_object(
               'catalog_snapshot_id', snapshot.id,
               'exercise_version_id', version_source.id,
               'exercise_key', definition_source.exercise_key,
               'version_number', version_source.version_number,
               'catalogue_state', version_source.catalogue_state,
               'safety_state', version_source.safety_state,
               'version_sha256', version_source.version_sha256
           ))
      FROM public.exercise_versions version_source
      JOIN public.exercise_definitions definition_source
        ON definition_source.id = version_source.exercise_definition_id
     WHERE definition_source.language_code = p_language_code;
    publication_hash := public.exercise_json_sha256_v1(jsonb_build_object(
        'operation_mode', 'allowlisted_service',
        'source_attachment_version_id', version_row.id,
        'source_acquisition_principal_id',
            attachment.acquisition_principal_id,
        'published_exercise_version_id', exercise_version.id,
        'catalog_snapshot_id', snapshot.id,
        'provenance_class', 'independent_clean_media',
        'authorization_snapshot_id', attachment.authorization_snapshot_id,
        'media_review_id', media_review.id
    ));
    INSERT INTO public.coach_guidance_publications (
        source_attachment_version_id, source_acquisition_principal_id,
        published_exercise_version_id, catalog_snapshot_id,
        provenance_class, authorization_snapshot_id, publication_sha256,
        idempotency_key, operation_mode, service_contract_version
    ) VALUES (
        version_row.id, attachment.acquisition_principal_id,
        exercise_version.id, snapshot.id, 'independent_clean_media',
        attachment.authorization_snapshot_id, publication_hash,
        p_idempotency_key, 'allowlisted_service',
        'mlc3-first-client-service-v1'
    ) RETURNING * INTO result;
    context := public.require_coach_guidance_service_access_v1(
        attachment.service_reveal_access_id, p_reviewer_principal_id,
        'personalized_exercise_recommendation'
    );
    PERFORM public.require_coach_guidance_service_media_live_v1(
        version_row.media_binding_id, attachment.acquisition_principal_id
    );
    RETURN result;
END;
$$;

-- ── Authoritative service reads and deletion/media serialization ─────────
CREATE OR REPLACE FUNCTION public.serialize_mlc3_processing_audio_leaf_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
DECLARE object_id UUID;
BEGIN
    -- RECORD field resolution is dynamic in trigger functions.  A CASE that
    -- names both table-specific fields can fail before choosing its branch,
    -- so resolve the field only inside the matching trigger-table branch.
    IF TG_TABLE_NAME = 'processing_audio_object_deletion_events' THEN
        object_id := NEW.audio_object_id;
    ELSE
        object_id := NEW.id;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-processing-audio-object:' || object_id::TEXT, 0
    ));
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS processing_audio_deletion_mlc3_serialization
    ON public.processing_audio_object_deletion_events;
CREATE TRIGGER processing_audio_deletion_mlc3_serialization
BEFORE INSERT ON public.processing_audio_object_deletion_events
FOR EACH ROW EXECUTE FUNCTION public.serialize_mlc3_processing_audio_leaf_v1();
DROP TRIGGER IF EXISTS processing_audio_object_mlc3_serialization
    ON public.processing_audio_objects;
CREATE TRIGGER processing_audio_object_mlc3_serialization
BEFORE UPDATE OF deleted_at ON public.processing_audio_objects
FOR EACH ROW EXECUTE FUNCTION public.serialize_mlc3_processing_audio_leaf_v1();

CREATE OR REPLACE FUNCTION public.serialize_mlc3_exercise_media_leaf_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-exercise-media:' || NEW.media_object_id::TEXT, 0
    ));
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS exercise_media_availability_mlc3_serialization
    ON public.exercise_media_availability_checks;
CREATE TRIGGER exercise_media_availability_mlc3_serialization
BEFORE INSERT ON public.exercise_media_availability_checks
FOR EACH ROW EXECUTE FUNCTION public.serialize_mlc3_exercise_media_leaf_v1();

CREATE OR REPLACE FUNCTION public.resolve_exercise_service_offer_read_v1(
    p_offer_id UUID,
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    offer public.exercise_service_offers;
    lineage public.exercise_audio_lineages;
    version_row public.exercise_versions;
    media public.exercise_media_objects;
    availability public.exercise_media_availability_checks;
BEGIN
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    SELECT * INTO STRICT offer FROM public.exercise_service_offers row
     WHERE row.id = p_offer_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service'
       AND row.serves_user AND NOT row.dataset_eligible;
    SELECT * INTO STRICT lineage FROM public.exercise_audio_lineages row
     WHERE row.id = offer.source_audio_lineage_id
       AND row.acquisition_principal_id = p_acquisition_principal_id;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-processing-audio-object:' ||
        lineage.processing_audio_object_id::TEXT, 0
    ));
    PERFORM public.require_feedback_v3_service_response_v1(
        offer.feedback_response_binding_id, p_acquisition_principal_id,
        offer.feedback_membership_id, offer.feedback_candidate_id,
        (SELECT response.feedback_exposure_id
           FROM public.feedback_v3_service_response_bindings response
          WHERE response.id = offer.feedback_response_binding_id)
    );
    PERFORM public.require_exercise_service_current_authority_v1(
        offer.authorization_check_id, p_acquisition_principal_id
    );
    IF EXISTS (
        SELECT 1 FROM public.processing_audio_object_deletion_events deletion
         WHERE deletion.audio_object_id = lineage.processing_audio_object_id
    ) OR NOT EXISTS (
        SELECT 1 FROM public.processing_audio_objects object_row
         WHERE object_row.id = lineage.processing_audio_object_id
           AND object_row.acquisition_principal_id = p_acquisition_principal_id
           AND object_row.deleted_at IS NULL
           AND object_row.exact_bytes_sha256 = lineage.exact_audio_sha256
    ) THEN
        RAISE EXCEPTION 'EXERCISE_SERVICE_OFFER_SOURCE_NOT_LIVE';
    END IF;
    IF offer.selected_exercise_version_id IS NOT NULL THEN
        SELECT * INTO STRICT version_row FROM public.exercise_versions row
         WHERE row.id = offer.selected_exercise_version_id
           AND row.safety_state = 'approved'
           AND row.catalogue_state = 'active';
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'mlc3-exercise-media:' || version_row.media_object_id::TEXT, 0
        ));
        SELECT * INTO STRICT media FROM public.exercise_media_objects row
         WHERE row.id = version_row.media_object_id
           AND row.storage_provider = 'r2';
        SELECT * INTO STRICT availability
          FROM public.exercise_media_availability_checks row
         WHERE row.media_object_id = media.id
         ORDER BY row.checked_at DESC, row.recorded_at DESC, row.id DESC
         LIMIT 1;
        IF availability.availability <> 'available'
           OR availability.observed_sha256 <> media.exact_bytes_sha256
           OR availability.expires_at <= clock_timestamp()
        THEN RAISE EXCEPTION 'EXERCISE_SERVICE_MEDIA_NOT_LIVE'; END IF;
    END IF;
    PERFORM public.require_mlc3_service_principal_v1(
        p_acquisition_principal_id
    );
    RETURN jsonb_build_object(
        'offer', to_jsonb(offer),
        'exercise_version', CASE WHEN version_row.id IS NULL THEN NULL
            ELSE to_jsonb(version_row) END,
        'media', CASE WHEN media.id IS NULL THEN NULL ELSE to_jsonb(media) END
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.resolve_exercise_practice_session_read_v1(
    p_session_id UUID,
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    practice public.exercise_practice_sessions;
    lineage public.exercise_audio_lineages;
BEGIN
    SELECT * INTO STRICT lineage
      FROM public.exercise_audio_lineages row
     WHERE row.id = (
         SELECT source_audio_lineage_id
           FROM public.exercise_practice_sessions session_row
          WHERE session_row.id = p_session_id
            AND session_row.acquisition_principal_id =
                p_acquisition_principal_id
     );
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-processing-audio-object:' ||
        lineage.processing_audio_object_id::TEXT, 0
    ));
    practice := public.require_exercise_practice_service_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    IF EXISTS (
        SELECT 1 FROM public.processing_audio_object_deletion_events deletion
         WHERE deletion.audio_object_id = lineage.processing_audio_object_id
    ) THEN RAISE EXCEPTION 'PRACTICE_SERVICE_SOURCE_DELETED'; END IF;
    practice := public.require_exercise_practice_service_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    RETURN to_jsonb(practice) || jsonb_build_object(
        'next_attempt_index', COALESCE((
            SELECT max(recovery.attempt_index) + 1
              FROM public.exercise_practice_upload_recoveries recovery
             WHERE recovery.session_id = practice.id
               AND recovery.acquisition_principal_id =
                   practice.acquisition_principal_id
        ), 1)
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.resolve_exercise_practice_media_read_v1(
    p_attempt_id UUID,
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    attempt public.exercise_practice_attempts;
    object_row public.processing_audio_objects;
BEGIN
    SELECT * INTO STRICT attempt FROM public.exercise_practice_attempts row
     WHERE row.id = p_attempt_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.operation_mode = 'allowlisted_service';
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-processing-audio-object:' ||
        attempt.processing_audio_object_id::TEXT, 0
    ));
    PERFORM public.require_exercise_practice_service_live_v1(
        attempt.session_id, p_acquisition_principal_id
    );
    SELECT * INTO STRICT object_row FROM public.processing_audio_objects row
     WHERE row.id = attempt.processing_audio_object_id
       AND row.acquisition_principal_id = p_acquisition_principal_id
       AND row.exact_bytes_sha256 = attempt.exact_audio_sha256
       AND row.storage_provider = 'r2'
       AND row.deleted_at IS NULL;
    IF attempt.state IN ('cancelled', 'quarantined') OR EXISTS (
        SELECT 1 FROM public.processing_audio_object_deletion_events deletion
         WHERE deletion.audio_object_id = object_row.id
    ) THEN RAISE EXCEPTION 'PRACTICE_SERVICE_MEDIA_NOT_LIVE'; END IF;
    PERFORM public.require_exercise_practice_service_live_v1(
        attempt.session_id, p_acquisition_principal_id
    );
    RETURN jsonb_build_object(
        'attempt_id', attempt.id,
        'session_id', attempt.session_id,
        'bucket', object_row.bucket,
        'object_key', object_row.object_key,
        'exact_bytes_sha256', object_row.exact_bytes_sha256,
        'content_type', object_row.content_type,
        'byte_size', object_row.byte_size
    );
END;
$$;

DROP FUNCTION IF EXISTS public.resolve_exercise_confidence_media_read_v1(
    UUID, UUID
);
CREATE OR REPLACE FUNCTION public.resolve_exercise_confidence_media_read_v1(
    p_playback_reference_id UUID,
    p_reviewer_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path = public AS $$
DECLARE
    assignment public.exercise_service_confidence_assignments;
    object_row public.processing_audio_objects;
BEGIN
    SELECT * INTO STRICT assignment
      FROM public.exercise_service_confidence_assignments row
     WHERE row.playback_reference_id = p_playback_reference_id
       AND row.reviewer_principal_id = p_reviewer_principal_id;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-processing-audio-object:' ||
        assignment.processing_audio_object_id::TEXT, 0
    ));
    assignment := public.require_exercise_service_confidence_live_v1(
        assignment.id, p_reviewer_principal_id
    );
    SELECT * INTO STRICT object_row FROM public.processing_audio_objects row
     WHERE row.id = assignment.processing_audio_object_id
       AND row.acquisition_principal_id =
           assignment.acquisition_principal_id
       AND row.exact_bytes_sha256 = assignment.exact_audio_sha256
       AND row.storage_provider = 'r2'
       AND row.deleted_at IS NULL;
    IF EXISTS (
        SELECT 1 FROM public.processing_audio_object_deletion_events deletion
         WHERE deletion.audio_object_id = object_row.id
    ) THEN RAISE EXCEPTION 'EXERCISE_SERVICE_REVIEW_MEDIA_NOT_LIVE'; END IF;
    assignment := public.require_exercise_service_confidence_live_v1(
        assignment.id, p_reviewer_principal_id
    );
    RETURN jsonb_build_object(
        'assignment_id', assignment.id,
        'bucket', object_row.bucket,
        'object_key', object_row.object_key,
        'exact_bytes_sha256', object_row.exact_bytes_sha256,
        'content_type', object_row.content_type,
        'byte_size', object_row.byte_size,
        'start_offset_ms', assignment.start_offset_ms,
        'duration_ms', assignment.duration_ms
    );
END;
$$;

ALTER TABLE public.mlc3_service_contracts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.mlc3_service_principal_allowlist ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_v3_service_response_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.feedback_v3_service_render_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_acquisition_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_practice_transcription_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_confidence_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_confidence_render_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_confidence_judgments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_blind_review_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_blind_reveal_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_service_blind_reveal_accesses ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'mlc3_service_contracts', 'mlc3_service_principal_allowlist',
        'feedback_v3_service_response_bindings',
        'feedback_v3_service_render_receipts',
        'exercise_service_acquisition_receipts',
        'exercise_service_confidence_assignments',
        'exercise_service_confidence_render_receipts',
        'exercise_service_confidence_judgments',
        'exercise_service_blind_review_sets',
        'exercise_service_blind_reveal_grants',
        'exercise_service_blind_reveal_accesses'
    ] LOOP
        EXECUTE format(
            'REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role',
            relation_name
        );
        EXECUTE format('GRANT SELECT ON public.%I TO service_role', relation_name);
        IF relation_name NOT IN (
            'mlc3_service_contracts', 'mlc3_service_principal_allowlist'
        ) THEN
            EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',
                relation_name || '_append_only', relation_name);
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
                'FOR EACH ROW EXECUTE FUNCTION '
                'public.reject_mlc2_immutable_mutation()',
                relation_name || '_append_only', relation_name
            );
        END IF;
    END LOOP;
END;
$$;

REVOKE ALL ON public.exercise_practice_transcription_runs
    FROM PUBLIC,anon,authenticated,service_role;
GRANT SELECT ON public.exercise_practice_transcription_runs TO service_role;

-- Internal trigger/serialization helpers are never PostgREST RPCs. PostgreSQL
-- grants function execution to PUBLIC by default, so revoke that implicit
-- surface explicitly in the same migration that creates the functions.
REVOKE ALL ON FUNCTION public.prepare_feedback_v3_service_row_v1()
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.prepare_exercise_service_row_v1()
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.prepare_exercise_practice_service_row_v1()
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.reject_feedback_exposure_mutation_v2()
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.serialize_mlc3_service_purge_v1()
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.serialize_mlc3_processing_audio_leaf_v1()
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.serialize_mlc3_exercise_media_leaf_v1()
    FROM PUBLIC,anon,authenticated,service_role;

REVOKE ALL ON FUNCTION public.require_mlc3_service_principal_v1(UUID)
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.require_feedback_v3_service_membership_live_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.record_exercise_service_acquisition_receipt_v1(
    UUID,TEXT,UUID,UUID,UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_service_acquisition_receipt_v1(
    UUID,TEXT,UUID,UUID,UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.require_feedback_v3_service_response_v1(
    UUID,UUID,UUID,UUID,UUID
) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.record_feedback_v3_service_candidate_set_v1(
    UUID,UUID,UUID,JSONB
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_feedback_v3_service_candidate_set_v1(
    UUID,UUID,UUID,JSONB
) TO service_role;
REVOKE ALL ON FUNCTION public.freeze_feedback_v3_service_membership_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,JSONB,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_feedback_v3_service_membership_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,JSONB,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.ack_feedback_v3_service_render_v1(
    UUID,UUID,UUID,UUID,UUID,UUID,TEXT,TIMESTAMPTZ,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ack_feedback_v3_service_render_v1(
    UUID,UUID,UUID,UUID,UUID,UUID,TEXT,TIMESTAMPTZ,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_feedback_v3_service_response_v1(
    UUID,UUID,UUID,UUID,UUID,UUID,UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_feedback_v3_service_response_v1(
    UUID,UUID,UUID,UUID,UUID,UUID,UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.freeze_exercise_service_offer_v2(
    UUID,UUID,UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_exercise_service_offer_v2(
    UUID,UUID,UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.issue_exercise_service_authority_v1(
    UUID,UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.require_exercise_service_current_authority_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.require_exercise_service_offer_live_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.prepare_feedback_v3_service_context_v1(
    UUID,UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.prepare_feedback_v3_service_context_v1(
    UUID,UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.require_exercise_practice_service_live_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.require_exercise_service_confidence_live_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.freeze_exercise_service_blind_review_set_v1(
    UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_exercise_service_blind_review_set_v1(
    UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.ack_exercise_service_confidence_render_v1(
    UUID,UUID,UUID,TEXT,TIMESTAMPTZ,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ack_exercise_service_confidence_render_v1(
    UUID,UUID,UUID,TEXT,TIMESTAMPTZ,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.submit_exercise_service_confidence_judgment_v1(
    UUID,UUID,UUID,TEXT,TIMESTAMPTZ,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.submit_exercise_service_confidence_judgment_v1(
    UUID,UUID,UUID,TEXT,TIMESTAMPTZ,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.complete_exercise_service_blind_review_v1(
    UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.complete_exercise_service_blind_review_v1(
    UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.access_exercise_service_blind_reveal_v1(
    UUID,UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.access_exercise_service_blind_reveal_v1(
    UUID,UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.create_exercise_practice_service_session_v1(
    UUID,UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.create_exercise_practice_service_session_v1(
    UUID,UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.reserve_exercise_practice_service_upload_v1(
    UUID,UUID,UUID,TEXT,BIGINT,TEXT,TEXT,TEXT,INTEGER
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_exercise_practice_service_upload_v1(
    UUID,UUID,UUID,TEXT,BIGINT,TEXT,TEXT,TEXT,INTEGER
) TO service_role;
REVOKE ALL ON FUNCTION public.ack_exercise_practice_service_upload_v1(
    UUID,UUID,TEXT,BIGINT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.ack_exercise_practice_service_upload_v1(
    UUID,UUID,TEXT,BIGINT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.finalize_exercise_practice_service_media_v1(
    UUID,UUID,UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_exercise_practice_service_media_v1(
    UUID,UUID,UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.guard_exercise_practice_transcription_run_v1()
    FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.authorize_exercise_practice_transcription_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.authorize_exercise_practice_transcription_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.mark_exercise_practice_transcription_dispatched_v1(
    UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.mark_exercise_practice_transcription_dispatched_v1(
    UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.finalize_exercise_practice_transcription_v1(
    UUID,UUID,TEXT,JSONB,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_exercise_practice_transcription_v1(
    UUID,UUID,TEXT,JSONB,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.reconcile_exercise_practice_transcription_v1(
    UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.reconcile_exercise_practice_transcription_v1(
    UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.reconcile_exercise_practice_transcription_request_v1(
    UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.reconcile_exercise_practice_transcription_request_v1(
    UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.attach_exercise_practice_service_attempt_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,INTEGER,
    TIMESTAMPTZ,TIMESTAMPTZ,JSONB,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.attach_exercise_practice_service_attempt_v1(
    UUID,UUID,UUID,UUID,UUID,TEXT,INTEGER,
    TIMESTAMPTZ,TIMESTAMPTZ,JSONB,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_exercise_practice_service_measurement_v1(
    UUID,INTEGER,TEXT,TEXT,JSONB,JSONB,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_practice_service_measurement_v1(
    UUID,INTEGER,TEXT,TEXT,JSONB,JSONB,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_exercise_practice_service_validity_v1(
    UUID,UUID,INTEGER,TEXT,TEXT[],TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_practice_service_validity_v1(
    UUID,UUID,INTEGER,TEXT,TEXT[],TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.freeze_exercise_practice_service_selection_v1(
    UUID,UUID,INTEGER,INTEGER,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_exercise_practice_service_selection_v1(
    UUID,UUID,INTEGER,INTEGER,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_exercise_offer_service_event_v1(
    UUID,UUID,UUID,TEXT,UUID,TEXT,JSONB,TIMESTAMPTZ,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_offer_service_event_v1(
    UUID,UUID,UUID,TEXT,UUID,TEXT,JSONB,TIMESTAMPTZ,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_exercise_practice_service_event_v1(
    UUID,UUID,UUID,UUID,TEXT,UUID,TEXT,JSONB,TIMESTAMPTZ,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_practice_service_event_v1(
    UUID,UUID,UUID,UUID,TEXT,UUID,TEXT,JSONB,TIMESTAMPTZ,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.freeze_exercise_service_pair_v1(
    UUID,UUID,UUID,INTEGER,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_exercise_service_pair_v1(
    UUID,UUID,UUID,INTEGER,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.assign_exercise_service_owner_pair_v1(
    UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.assign_exercise_service_owner_pair_v1(
    UUID,UUID,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.submit_exercise_service_owner_pair_judgment_v1(
    UUID,UUID,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.submit_exercise_service_owner_pair_judgment_v1(
    UUID,UUID,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.require_coach_guidance_service_access_v1(
    UUID,UUID,TEXT
) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.reserve_coach_guidance_service_upload_v1(
    UUID,UUID,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_coach_guidance_service_upload_v1(
    UUID,UUID,TEXT,TEXT,TEXT,TEXT,BIGINT,TEXT,TIMESTAMPTZ,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_coach_guidance_service_upload_event_v1(
    UUID,UUID,TEXT,TEXT,BIGINT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_coach_guidance_service_upload_event_v1(
    UUID,UUID,TEXT,TEXT,BIGINT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.finalize_coach_guidance_service_media_v1(
    UUID,UUID,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_coach_guidance_service_media_v1(
    UUID,UUID,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.require_coach_guidance_service_media_live_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.create_coach_guidance_service_attachment_v1(
    UUID,UUID,UUID,UUID,TEXT,TEXT,TEXT,UUID,UUID,UUID,UUID,
    TEXT,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.create_coach_guidance_service_attachment_v1(
    UUID,UUID,UUID,UUID,TEXT,TEXT,TEXT,UUID,UUID,UUID,UUID,
    TEXT,TEXT,TEXT,TEXT,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_coach_guidance_service_event_v1(
    UUID,UUID,TEXT,UUID,JSONB,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_coach_guidance_service_event_v1(
    UUID,UUID,TEXT,UUID,JSONB,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.resolve_coach_guidance_service_media_read_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_coach_guidance_service_media_read_v1(
    UUID,UUID
) TO service_role;
REVOKE ALL ON FUNCTION public.resolve_exercise_service_offer_read_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_exercise_service_offer_read_v1(
    UUID,UUID
) TO service_role;
REVOKE ALL ON FUNCTION public.resolve_exercise_practice_session_read_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_exercise_practice_session_read_v1(
    UUID,UUID
) TO service_role;
REVOKE ALL ON FUNCTION public.resolve_exercise_practice_media_read_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_exercise_practice_media_read_v1(
    UUID,UUID
) TO service_role;
REVOKE ALL ON FUNCTION public.resolve_exercise_confidence_media_read_v1(
    UUID,UUID
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_exercise_confidence_media_read_v1(
    UUID,UUID
) TO service_role;
REVOKE ALL ON FUNCTION public.publish_coach_guidance_service_exercise_v1(
    UUID,UUID,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.publish_coach_guidance_service_exercise_v1(
    UUID,UUID,TEXT,TEXT,TEXT,TEXT
) TO service_role;

-- No RPC for activating a contract or changing the principal allowlist is
-- deliberately exposed.  Those release operations require a separately
-- reviewed migration/configuration change.

NOTIFY pgrst, 'reload schema';
COMMIT;
