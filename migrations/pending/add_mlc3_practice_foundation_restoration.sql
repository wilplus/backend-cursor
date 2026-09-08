-- MLC-3 P1/P2 restoration. Pending and deliberately unassigned.
--
-- This is the canonical product-practice evidence boundary consumed by RPQ.
-- It does not serve an exercise, expose a user, or make a learning label.
-- Every executable writer is synthetic-only until a later release migration
-- replaces the structural false constraints under separate authorization.

BEGIN;

-- The released schema already has this relational identity.  The explicit
-- named index also makes the restored contract self-contained in disposable
-- rehearsals built from narrow prerequisite fixtures.
CREATE UNIQUE INDEX IF NOT EXISTS exercise_practice_take_owner_identity
    ON public.takes (id, project_id, owner_principal_id);

CREATE TABLE IF NOT EXISTS public.exercise_practice_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT,
    source_take_id UUID NOT NULL REFERENCES public.takes(id) ON DELETE RESTRICT,
    source_audio_lineage_id UUID NOT NULL
        REFERENCES public.exercise_audio_lineages(id) ON DELETE RESTRICT,
    -- Bound by the subsequent fresh-offer restoration migration.  Keeping the
    -- UUID here lets this lower P1 evidence layer remain independently
    -- replayable without depending on a dark assignment.
    source_offer_id UUID NOT NULL UNIQUE,
    exercise_version_id UUID NOT NULL
        REFERENCES public.exercise_versions(id) ON DELETE RESTRICT,
    authorization_check_id UUID NOT NULL
        REFERENCES public.exercise_authorization_checks(id) ON DELETE RESTRICT,
    exact_passage TEXT NOT NULL CHECK (length(btrim(exact_passage)) > 0),
    exact_passage_sha256 TEXT NOT NULL CHECK (
        exact_passage_sha256 ~ '^[0-9a-f]{64}$'
    ),
    baseline_revision INTEGER NOT NULL DEFAULT 1 CHECK (baseline_revision > 0),
    session_window_version TEXT NOT NULL,
    opens_at TIMESTAMPTZ NOT NULL,
    closes_at TIMESTAMPTZ NOT NULL,
    state TEXT NOT NULL DEFAULT 'open' CHECK (state IN (
        'open', 'completed', 'cancelled', 'quarantined'
    )),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK (closes_at > opens_at),
    FOREIGN KEY (source_take_id, project_id, acquisition_principal_id)
        REFERENCES public.takes(id, project_id, owner_principal_id)
        ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.exercise_practice_upload_recoveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES public.exercise_practice_sessions(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    attempt_index INTEGER NOT NULL CHECK (attempt_index > 0),
    storage_provider TEXT NOT NULL CHECK (storage_provider = 'local_synthetic'),
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    intended_exact_bytes_sha256 TEXT NOT NULL CHECK (
        intended_exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
    ),
    status TEXT NOT NULL DEFAULT 'write_started' CHECK (status IN (
        'write_started', 'attached', 'orphaned', 'deleted'
    )),
    processing_audio_object_id UUID NULL
        REFERENCES public.processing_audio_objects(id) ON DELETE RESTRICT,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (storage_provider, bucket, object_key),
    UNIQUE (session_id, attempt_index)
);

CREATE TABLE IF NOT EXISTS public.exercise_practice_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES public.exercise_practice_sessions(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    processing_recording_attempt_id UUID NOT NULL
        REFERENCES public.processing_recording_attempts(id) ON DELETE RESTRICT,
    processing_audio_object_id UUID NOT NULL
        REFERENCES public.processing_audio_objects(id) ON DELETE RESTRICT,
    upload_recovery_id UUID NOT NULL UNIQUE
        REFERENCES public.exercise_practice_upload_recoveries(id)
        ON DELETE RESTRICT,
    attempt_index INTEGER NOT NULL CHECK (attempt_index > 0),
    exact_passage TEXT NOT NULL CHECK (length(btrim(exact_passage)) > 0),
    transcript_text TEXT NOT NULL CHECK (length(btrim(transcript_text)) > 0),
    transcript_sha256 TEXT NOT NULL CHECK (
        transcript_sha256 ~ '^[0-9a-f]{64}$'
    ),
    exact_audio_sha256 TEXT NOT NULL CHECK (
        exact_audio_sha256 ~ '^[0-9a-f]{64}$'
    ),
    duration_ms INTEGER NOT NULL CHECK (duration_ms > 0),
    capture_started_at TIMESTAMPTZ NOT NULL,
    capture_completed_at TIMESTAMPTZ NOT NULL,
    recording_conditions JSONB NOT NULL CHECK (
        jsonb_typeof(recording_conditions) = 'object'
    ),
    state TEXT NOT NULL CHECK (state IN (
        'captured', 'processed', 'invalid', 'cancelled', 'quarantined'
    )),
    attempt_sha256 TEXT NOT NULL CHECK (attempt_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK (capture_completed_at >= capture_started_at),
    UNIQUE (session_id, attempt_index),
    UNIQUE (processing_recording_attempt_id),
    UNIQUE (processing_audio_object_id)
);

CREATE TABLE IF NOT EXISTS public.exercise_practice_measurement_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.exercise_practice_attempts(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    measurement_revision INTEGER NOT NULL CHECK (measurement_revision > 0),
    extractor_version TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    raw_measurements JSONB NOT NULL CHECK (jsonb_typeof(raw_measurements) = 'object'),
    safeguards JSONB NOT NULL CHECK (jsonb_typeof(safeguards) = 'object'),
    input_sha256 TEXT NOT NULL CHECK (input_sha256 ~ '^[0-9a-f]{64}$'),
    output_sha256 TEXT NOT NULL CHECK (output_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (attempt_id, measurement_revision)
);

CREATE TABLE IF NOT EXISTS public.exercise_practice_validity_assessments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    attempt_id UUID NOT NULL REFERENCES public.exercise_practice_attempts(id)
        ON DELETE RESTRICT,
    measurement_revision_id UUID NOT NULL
        REFERENCES public.exercise_practice_measurement_revisions(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    baseline_revision INTEGER NOT NULL CHECK (baseline_revision > 0),
    validity TEXT NOT NULL CHECK (validity IN ('valid', 'invalid', 'pending')),
    reason_codes TEXT[] NOT NULL,
    validity_contract_version TEXT NOT NULL,
    assessment_sha256 TEXT NOT NULL CHECK (assessment_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK ((validity = 'valid' AND cardinality(reason_codes) = 0)
        OR (validity <> 'valid' AND cardinality(reason_codes) > 0)),
    UNIQUE (attempt_id, baseline_revision, validity_contract_version)
);

CREATE TABLE IF NOT EXISTS public.exercise_practice_selection_revisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES public.exercise_practice_sessions(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    baseline_revision INTEGER NOT NULL CHECK (baseline_revision > 0),
    revision INTEGER NOT NULL CHECK (revision > 0),
    inventory JSONB NOT NULL CHECK (jsonb_typeof(inventory) = 'array'),
    selected_attempt_id UUID NULL REFERENCES public.exercise_practice_attempts(id)
        ON DELETE RESTRICT,
    selection_state TEXT NOT NULL CHECK (selection_state IN (
        'selected_first_valid', 'pending_earlier_attempt', 'no_valid_attempt',
        'no_attempt'
    )),
    selection_policy_version TEXT NOT NULL CHECK (
        selection_policy_version = 'first-valid-attempt-v1'
    ),
    inventory_sha256 TEXT NOT NULL CHECK (inventory_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (session_id, baseline_revision, revision)
);

CREATE TABLE IF NOT EXISTS public.exercise_practice_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL REFERENCES public.exercise_practice_sessions(id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    attempt_id UUID NULL REFERENCES public.exercise_practice_attempts(id)
        ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK (event_kind IN (
        'assignment_prepared', 'delivery_prepared', 'render_confirmed',
        'playback_started', 'playback_completed', 'capture_reserved',
        'capture_started', 'capture_completed', 'attempt_processed',
        'session_cancelled', 'session_quarantined'
    )),
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (
        jsonb_typeof(event_payload) = 'object'
    ),
    occurred_at TIMESTAMPTZ NOT NULL,
    event_sha256 TEXT NOT NULL CHECK (event_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

CREATE OR REPLACE FUNCTION public.require_practice_processing_authority_v1(
    p_authorization_check_id UUID,
    p_acquisition_principal_id UUID
) RETURNS VOID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    auth public.exercise_authorization_checks;
    checked_now TIMESTAMPTZ;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'PRACTICE_REQUIRES_READ_COMMITTED';
    END IF;
    auth := public.require_current_exercise_authorization_v1(
        p_authorization_check_id,
        p_acquisition_principal_id,
        'practice_processing'
    );
    checked_now := clock_timestamp();
    IF EXISTS (
        SELECT 1 FROM public.processing_service_blocks block
         WHERE block.acquisition_principal_id = p_acquisition_principal_id
           AND block.effective_at <= checked_now
    ) OR NOT EXISTS (
        SELECT 1
          FROM public.processing_authorization_snapshots snapshot
          JOIN public.processing_policy_versions policy
            ON policy.id = snapshot.policy_id
         WHERE snapshot.id = auth.authorization_snapshot_id
           AND snapshot.acquisition_principal_id = p_acquisition_principal_id
           AND auth.purpose_id = snapshot.purpose_id
           AND auth.policy_version = policy.version
           AND policy.status = 'active'
           AND policy.activated_at <= checked_now
           AND (policy.retired_at IS NULL OR policy.retired_at > checked_now)
    ) THEN
        RAISE EXCEPTION 'EXERCISE_CURRENT_AUTHORIZATION_REVOKED';
    END IF;
    IF auth.checked_at < checked_now - interval '5 minutes'
       OR auth.checked_at > checked_now THEN
        RAISE EXCEPTION 'EXERCISE_CURRENT_AUTHORIZATION_REQUIRED';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.require_practice_source_live_v1(
    p_session_id UUID,
    p_acquisition_principal_id UUID
) RETURNS public.exercise_practice_sessions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    practice public.exercise_practice_sessions;
    lineage public.exercise_audio_lineages;
    source_object public.processing_audio_objects;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'PRACTICE_REQUIRES_READ_COMMITTED';
    END IF;
    SELECT * INTO STRICT practice FROM public.exercise_practice_sessions
     WHERE id = p_session_id AND acquisition_principal_id = p_acquisition_principal_id;
    SELECT * INTO STRICT lineage FROM public.exercise_audio_lineages
     WHERE id = practice.source_audio_lineage_id
       AND acquisition_principal_id = practice.acquisition_principal_id;
    SELECT * INTO STRICT source_object FROM public.processing_audio_objects
     WHERE id = lineage.processing_audio_object_id
       AND acquisition_principal_id = practice.acquisition_principal_id
       AND deleted_at IS NULL;
    PERFORM public.require_practice_processing_authority_v1(
        practice.authorization_check_id, practice.acquisition_principal_id);
    IF practice.state NOT IN ('open', 'completed')
       OR EXISTS (
          SELECT 1 FROM public.data_purge_requests purge
           WHERE purge.acquisition_principal_id = practice.acquisition_principal_id
             AND purge.state <> 'done'
       )
    THEN RAISE EXCEPTION 'PRACTICE_SOURCE_NOT_LIVE'; END IF;
    RETURN practice;
END;
$$;

CREATE OR REPLACE FUNCTION public.reserve_synthetic_practice_upload_v1(
    p_session_id UUID,
    p_acquisition_principal_id UUID,
    p_attempt_index INTEGER,
    p_storage_provider TEXT,
    p_bucket TEXT,
    p_object_key TEXT,
    p_intended_exact_bytes_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_upload_recoveries
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE result public.exercise_practice_upload_recoveries;
BEGIN
    IF p_attempt_index < 1 OR p_intended_exact_bytes_sha256 !~ '^[0-9a-f]{64}$'
       OR COALESCE(btrim(p_object_key), '') = ''
       OR COALESCE(btrim(p_idempotency_key), '') = ''
    THEN RAISE EXCEPTION 'PRACTICE_UPLOAD_RESERVATION_INVALID'; END IF;
    PERFORM public.require_practice_source_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-upload:' || p_idempotency_key, 0
    ));
    PERFORM public.require_practice_source_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    SELECT * INTO result FROM public.exercise_practice_upload_recoveries
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.session_id <> p_session_id
           OR result.acquisition_principal_id <> p_acquisition_principal_id
           OR result.attempt_index <> p_attempt_index
           OR result.storage_provider <> p_storage_provider
           OR result.bucket <> p_bucket OR result.object_key <> p_object_key
           OR result.intended_exact_bytes_sha256 <>
              lower(p_intended_exact_bytes_sha256)
        THEN RAISE EXCEPTION 'PRACTICE_UPLOAD_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    IF (SELECT state FROM public.exercise_practice_sessions
         WHERE id = p_session_id) <> 'open'
    THEN RAISE EXCEPTION 'PRACTICE_SESSION_NOT_OPEN'; END IF;
    INSERT INTO public.exercise_practice_upload_recoveries (
        session_id, acquisition_principal_id, attempt_index, storage_provider,
        bucket, object_key, intended_exact_bytes_sha256, idempotency_key
    ) VALUES (
        p_session_id, p_acquisition_principal_id, p_attempt_index,
        p_storage_provider, p_bucket, p_object_key,
        lower(p_intended_exact_bytes_sha256), p_idempotency_key
    ) RETURNING * INTO result;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.attach_synthetic_practice_attempt_v1(
    p_recovery_id UUID,
    p_processing_recording_attempt_id UUID,
    p_processing_audio_object_id UUID,
    p_exact_passage TEXT,
    p_transcript_text TEXT,
    p_transcript_sha256 TEXT,
    p_duration_ms INTEGER,
    p_capture_started_at TIMESTAMPTZ,
    p_capture_completed_at TIMESTAMPTZ,
    p_recording_conditions JSONB,
    p_attempt_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_attempts
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    recovery public.exercise_practice_upload_recoveries;
    practice public.exercise_practice_sessions;
    processing_attempt public.processing_recording_attempts;
    audio_object public.processing_audio_objects;
    result public.exercise_practice_attempts;
    derived_transcript_sha256 TEXT;
    derived_attempt_sha256 TEXT;
BEGIN
    SELECT * INTO STRICT recovery FROM public.exercise_practice_upload_recoveries
     WHERE id = p_recovery_id FOR UPDATE;
    SELECT * INTO practice FROM public.require_practice_source_live_v1(
        recovery.session_id, recovery.acquisition_principal_id
    );
    SELECT * INTO STRICT processing_attempt FROM public.processing_recording_attempts
     WHERE id = p_processing_recording_attempt_id
       AND acquisition_principal_id = practice.acquisition_principal_id
       AND project_id = practice.project_id
       AND status NOT IN ('cancelled', 'purged');
    SELECT * INTO STRICT audio_object FROM public.processing_audio_objects
     WHERE id = p_processing_audio_object_id
       AND recording_attempt_id = processing_attempt.id
       AND acquisition_principal_id = practice.acquisition_principal_id
       AND storage_provider = recovery.storage_provider
       AND bucket = recovery.bucket AND object_key = recovery.object_key
       AND exact_bytes_sha256 = recovery.intended_exact_bytes_sha256
       AND deleted_at IS NULL;
    derived_transcript_sha256 := public.exercise_json_sha256_v1(
        to_jsonb(p_transcript_text));
    derived_attempt_sha256 := public.exercise_json_sha256_v1(jsonb_build_object(
        'session_id', practice.id,
        'acquisition_principal_id', practice.acquisition_principal_id,
        'processing_recording_attempt_id', processing_attempt.id,
        'processing_audio_object_id', audio_object.id,
        'upload_recovery_id', recovery.id,
        'attempt_index', recovery.attempt_index,
        'exact_passage', p_exact_passage,
        'transcript_text', p_transcript_text,
        'transcript_sha256', derived_transcript_sha256,
        'exact_audio_sha256', audio_object.exact_bytes_sha256,
        'duration_ms', p_duration_ms,
        'capture_started_at', p_capture_started_at,
        'capture_completed_at', p_capture_completed_at,
        'recording_conditions', p_recording_conditions));
    IF recovery.status NOT IN ('write_started', 'attached')
       OR p_exact_passage IS DISTINCT FROM practice.exact_passage
       OR lower(p_transcript_sha256) IS DISTINCT FROM derived_transcript_sha256
       OR lower(p_attempt_sha256) IS DISTINCT FROM derived_attempt_sha256
       OR p_duration_ms < 1
       OR p_capture_completed_at < p_capture_started_at
       OR jsonb_typeof(p_recording_conditions) <> 'object'
    THEN RAISE EXCEPTION 'PRACTICE_ATTEMPT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-attempt:' || p_idempotency_key, 0
    ));
    SELECT * INTO practice FROM public.require_practice_source_live_v1(
        recovery.session_id, recovery.acquisition_principal_id
    );
    SELECT * INTO STRICT processing_attempt FROM public.processing_recording_attempts
     WHERE id = p_processing_recording_attempt_id
       AND acquisition_principal_id = practice.acquisition_principal_id
       AND project_id = practice.project_id
       AND status NOT IN ('cancelled', 'purged');
    SELECT * INTO STRICT audio_object FROM public.processing_audio_objects
     WHERE id = p_processing_audio_object_id
       AND recording_attempt_id = processing_attempt.id
       AND acquisition_principal_id = practice.acquisition_principal_id
       AND storage_provider = recovery.storage_provider
       AND bucket = recovery.bucket AND object_key = recovery.object_key
       AND exact_bytes_sha256 = recovery.intended_exact_bytes_sha256
       AND deleted_at IS NULL;
    derived_transcript_sha256 := public.exercise_json_sha256_v1(
        to_jsonb(p_transcript_text));
    derived_attempt_sha256 := public.exercise_json_sha256_v1(jsonb_build_object(
        'session_id', practice.id,
        'acquisition_principal_id', practice.acquisition_principal_id,
        'processing_recording_attempt_id', processing_attempt.id,
        'processing_audio_object_id', audio_object.id,
        'upload_recovery_id', recovery.id,
        'attempt_index', recovery.attempt_index,
        'exact_passage', p_exact_passage,
        'transcript_text', p_transcript_text,
        'transcript_sha256', derived_transcript_sha256,
        'exact_audio_sha256', audio_object.exact_bytes_sha256,
        'duration_ms', p_duration_ms,
        'capture_started_at', p_capture_started_at,
        'capture_completed_at', p_capture_completed_at,
        'recording_conditions', p_recording_conditions));
    IF lower(p_transcript_sha256) IS DISTINCT FROM derived_transcript_sha256
       OR lower(p_attempt_sha256) IS DISTINCT FROM derived_attempt_sha256
    THEN RAISE EXCEPTION 'PRACTICE_ATTEMPT_HASH_MISMATCH'; END IF;
    SELECT * INTO result FROM public.exercise_practice_attempts
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.upload_recovery_id <> recovery.id
           OR result.processing_audio_object_id <> audio_object.id
           OR result.attempt_sha256 <> lower(p_attempt_sha256)
        THEN RAISE EXCEPTION 'PRACTICE_ATTEMPT_REPLAY_CONFLICT'; END IF;
        PERFORM public.require_practice_source_live_v1(
            practice.id, practice.acquisition_principal_id
        );
        RETURN result;
    END IF;
    IF practice.state <> 'open' THEN
        RAISE EXCEPTION 'PRACTICE_SESSION_NOT_OPEN'; END IF;
    INSERT INTO public.exercise_practice_attempts (
        session_id, acquisition_principal_id, processing_recording_attempt_id,
        processing_audio_object_id, upload_recovery_id, attempt_index,
        exact_passage, transcript_text, transcript_sha256, exact_audio_sha256,
        duration_ms, capture_started_at, capture_completed_at,
        recording_conditions, state, attempt_sha256, idempotency_key
    ) VALUES (
        practice.id, practice.acquisition_principal_id, processing_attempt.id,
        audio_object.id, recovery.id, recovery.attempt_index, p_exact_passage,
        p_transcript_text, lower(p_transcript_sha256),
        audio_object.exact_bytes_sha256, p_duration_ms, p_capture_started_at,
        p_capture_completed_at, p_recording_conditions, 'captured',
        lower(p_attempt_sha256), p_idempotency_key
    ) RETURNING * INTO result;
    UPDATE public.exercise_practice_upload_recoveries
       SET status = 'attached', processing_audio_object_id = audio_object.id
     WHERE id = recovery.id;
    PERFORM public.require_practice_source_live_v1(
        practice.id, practice.acquisition_principal_id
    );
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_synthetic_practice_validity_v1(
    p_attempt_id UUID,
    p_measurement_revision_id UUID,
    p_baseline_revision INTEGER,
    p_validity TEXT,
    p_reason_codes TEXT[],
    p_validity_contract_version TEXT,
    p_assessment_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_validity_assessments
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    attempt public.exercise_practice_attempts;
    measurement public.exercise_practice_measurement_revisions;
    practice public.exercise_practice_sessions;
    result public.exercise_practice_validity_assessments;
    derived_assessment_sha256 TEXT;
BEGIN
    SELECT * INTO STRICT attempt FROM public.exercise_practice_attempts
     WHERE id = p_attempt_id;
    SELECT * INTO practice FROM public.require_practice_source_live_v1(
        attempt.session_id, attempt.acquisition_principal_id
    );
    SELECT * INTO STRICT measurement FROM public.exercise_practice_measurement_revisions
     WHERE id = p_measurement_revision_id AND attempt_id = attempt.id
       AND acquisition_principal_id = attempt.acquisition_principal_id;
    derived_assessment_sha256 := public.exercise_json_sha256_v1(jsonb_build_object(
        'attempt_id', attempt.id,
        'attempt_sha256', attempt.attempt_sha256,
        'measurement_revision_id', measurement.id,
        'measurement_output_sha256', measurement.output_sha256,
        'baseline_revision', p_baseline_revision,
        'validity', p_validity,
        'reason_codes', to_jsonb(p_reason_codes),
        'validity_contract_version', p_validity_contract_version));
    IF p_baseline_revision <> practice.baseline_revision
       OR p_validity NOT IN ('valid', 'invalid', 'pending')
       OR (p_validity = 'valid' AND cardinality(p_reason_codes) <> 0)
       OR (p_validity <> 'valid' AND cardinality(p_reason_codes) = 0)
       OR lower(p_assessment_sha256) IS DISTINCT FROM derived_assessment_sha256
    THEN RAISE EXCEPTION 'PRACTICE_VALIDITY_INVALID'; END IF;
    INSERT INTO public.exercise_practice_validity_assessments (
        attempt_id, measurement_revision_id, acquisition_principal_id,
        baseline_revision, validity, reason_codes, validity_contract_version,
        assessment_sha256, idempotency_key
    ) VALUES (
        attempt.id, measurement.id, attempt.acquisition_principal_id,
        p_baseline_revision, p_validity, p_reason_codes,
        p_validity_contract_version, lower(p_assessment_sha256),
        p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO STRICT result FROM public.exercise_practice_validity_assessments
     WHERE idempotency_key = p_idempotency_key;
    IF result.attempt_id <> attempt.id
       OR result.measurement_revision_id <> measurement.id
       OR result.baseline_revision <> p_baseline_revision
       OR result.validity <> p_validity
    THEN RAISE EXCEPTION 'PRACTICE_VALIDITY_REPLAY_CONFLICT'; END IF;
    PERFORM public.require_practice_source_live_v1(
        practice.id, practice.acquisition_principal_id);
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_synthetic_practice_measurement_v1(
    p_attempt_id UUID,
    p_measurement_revision INTEGER,
    p_extractor_version TEXT,
    p_feature_schema_version TEXT,
    p_raw_measurements JSONB,
    p_safeguards JSONB,
    p_input_sha256 TEXT,
    p_output_sha256 TEXT,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_measurement_revisions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    attempt public.exercise_practice_attempts;
    practice public.exercise_practice_sessions;
    result public.exercise_practice_measurement_revisions;
    derived_input_sha256 TEXT;
    derived_output_sha256 TEXT;
BEGIN
    SELECT * INTO STRICT attempt FROM public.exercise_practice_attempts
     WHERE id = p_attempt_id;
    SELECT * INTO practice FROM public.require_practice_source_live_v1(
        attempt.session_id, attempt.acquisition_principal_id
    );
    derived_input_sha256 := public.exercise_json_sha256_v1(jsonb_build_object(
        'attempt_id', attempt.id, 'attempt_sha256', attempt.attempt_sha256,
        'measurement_revision', p_measurement_revision,
        'extractor_version', p_extractor_version,
        'feature_schema_version', p_feature_schema_version));
    derived_output_sha256 := public.exercise_json_sha256_v1(jsonb_build_object(
        'input_sha256', derived_input_sha256,
        'raw_measurements', p_raw_measurements,
        'safeguards', p_safeguards));
    IF attempt.state IN ('cancelled', 'quarantined')
       OR p_measurement_revision < 1
       OR COALESCE(btrim(p_extractor_version), '') = ''
       OR COALESCE(btrim(p_feature_schema_version), '') = ''
       OR jsonb_typeof(p_raw_measurements) <> 'object'
       OR jsonb_typeof(p_safeguards) <> 'object'
       OR lower(p_input_sha256) IS DISTINCT FROM derived_input_sha256
       OR lower(p_output_sha256) IS DISTINCT FROM derived_output_sha256
    THEN RAISE EXCEPTION 'PRACTICE_MEASUREMENT_INVALID'; END IF;
    INSERT INTO public.exercise_practice_measurement_revisions (
        attempt_id, acquisition_principal_id, measurement_revision,
        extractor_version, feature_schema_version, raw_measurements,
        safeguards, input_sha256, output_sha256, idempotency_key
    ) VALUES (
        attempt.id, attempt.acquisition_principal_id, p_measurement_revision,
        p_extractor_version, p_feature_schema_version, p_raw_measurements,
        p_safeguards, lower(p_input_sha256), lower(p_output_sha256),
        p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO STRICT result FROM public.exercise_practice_measurement_revisions
     WHERE idempotency_key = p_idempotency_key;
    IF result.attempt_id <> attempt.id
       OR result.measurement_revision <> p_measurement_revision
       OR result.input_sha256 <> lower(p_input_sha256)
       OR result.output_sha256 <> lower(p_output_sha256)
    THEN RAISE EXCEPTION 'PRACTICE_MEASUREMENT_REPLAY_CONFLICT'; END IF;
    PERFORM public.require_practice_source_live_v1(
        practice.id, practice.acquisition_principal_id);
    RETURN result;
END;
$$;

-- Selection is recomputed as one immutable inventory for one baseline. An
-- unresolved earlier attempt prevents a later valid attempt from winning.
CREATE OR REPLACE FUNCTION public.freeze_synthetic_practice_selection_v1(
    p_session_id UUID,
    p_acquisition_principal_id UUID,
    p_baseline_revision INTEGER,
    p_revision INTEGER,
    p_idempotency_key TEXT
) RETURNS public.exercise_practice_selection_revisions
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    practice public.exercise_practice_sessions;
    result public.exercise_practice_selection_revisions;
    inventory JSONB;
    first_valid UUID;
    first_valid_index INTEGER;
    unresolved_earlier BOOLEAN;
    selection_state TEXT;
BEGIN
    SELECT * INTO practice FROM public.require_practice_source_live_v1(
        p_session_id, p_acquisition_principal_id
    );
    IF p_baseline_revision <> practice.baseline_revision OR p_revision < 1
    THEN RAISE EXCEPTION 'PRACTICE_SELECTION_BASELINE_STALE'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'practice-selection:' || p_session_id::text, 0
    ));
    SELECT * INTO practice FROM public.require_practice_source_live_v1(
        p_session_id, p_acquisition_principal_id);
    IF p_baseline_revision <> practice.baseline_revision THEN
        RAISE EXCEPTION 'PRACTICE_SELECTION_BASELINE_STALE'; END IF;
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'attempt_id', attempt.id,
        'attempt_index', attempt.attempt_index,
        'assessment_id', assessment.id,
        'validity', COALESCE(assessment.validity, 'pending'),
        'reason_codes', COALESCE(to_jsonb(assessment.reason_codes),
            '["assessment_missing"]'::jsonb)
    ) ORDER BY attempt.attempt_index), '[]'::jsonb)
      INTO inventory
      FROM public.exercise_practice_attempts attempt
      LEFT JOIN public.exercise_practice_validity_assessments assessment
        ON assessment.attempt_id = attempt.id
       AND assessment.baseline_revision = p_baseline_revision
     WHERE attempt.session_id = practice.id;
    SELECT attempt.id, attempt.attempt_index
      INTO first_valid, first_valid_index
      FROM public.exercise_practice_attempts attempt
      JOIN public.exercise_practice_validity_assessments assessment
        ON assessment.attempt_id = attempt.id
       AND assessment.baseline_revision = p_baseline_revision
       AND assessment.validity = 'valid'
     WHERE attempt.session_id = practice.id
     ORDER BY attempt.attempt_index LIMIT 1;
    SELECT EXISTS (
        SELECT 1 FROM public.exercise_practice_attempts attempt
        LEFT JOIN public.exercise_practice_validity_assessments assessment
          ON assessment.attempt_id = attempt.id
         AND assessment.baseline_revision = p_baseline_revision
       WHERE attempt.session_id = practice.id
         AND (first_valid_index IS NULL OR attempt.attempt_index < first_valid_index)
         AND (assessment.id IS NULL OR assessment.validity = 'pending')
    ) INTO unresolved_earlier;
    IF jsonb_array_length(inventory) = 0 THEN
        selection_state := 'no_attempt'; first_valid := NULL;
    ELSIF unresolved_earlier THEN
        selection_state := 'pending_earlier_attempt'; first_valid := NULL;
    ELSIF first_valid IS NOT NULL THEN
        selection_state := 'selected_first_valid';
    ELSE
        selection_state := 'no_valid_attempt';
    END IF;
    INSERT INTO public.exercise_practice_selection_revisions (
        session_id, acquisition_principal_id, baseline_revision, revision,
        inventory, selected_attempt_id, selection_state,
        selection_policy_version, inventory_sha256, idempotency_key
    ) VALUES (
        practice.id, practice.acquisition_principal_id, p_baseline_revision,
        p_revision, inventory, first_valid, selection_state,
        'first-valid-attempt-v1', public.exercise_json_sha256_v1(inventory),
        p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO STRICT result FROM public.exercise_practice_selection_revisions
     WHERE idempotency_key = p_idempotency_key;
    IF result.session_id <> practice.id
       OR result.baseline_revision <> p_baseline_revision
       OR result.inventory IS DISTINCT FROM inventory
       OR result.selected_attempt_id IS DISTINCT FROM first_valid
    THEN RAISE EXCEPTION 'PRACTICE_SELECTION_REPLAY_CONFLICT'; END IF;
    RETURN result;
END;
$$;

ALTER TABLE public.exercise_practice_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_practice_upload_recoveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_practice_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_practice_measurement_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_practice_validity_assessments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_practice_selection_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_practice_events ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'exercise_practice_sessions', 'exercise_practice_upload_recoveries',
        'exercise_practice_attempts', 'exercise_practice_measurement_revisions',
        'exercise_practice_validity_assessments',
        'exercise_practice_selection_revisions', 'exercise_practice_events'
    ] LOOP
        EXECUTE format(
            'REVOKE ALL ON public.%I FROM PUBLIC, anon, authenticated, service_role',
            relation_name
        );
        EXECUTE format('GRANT SELECT ON public.%I TO service_role', relation_name);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',
            relation_name || '_append_only', relation_name);
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.reject_mlc2_immutable_mutation()',
            relation_name || '_append_only', relation_name
        );
    END LOOP;
    -- Recovery state is the sole mutable exception; its transition is owned
    -- by the attachment/deletion RPCs and remains unreadable to runtime roles.
    EXECUTE 'DROP TRIGGER IF EXISTS exercise_practice_upload_recoveries_append_only '
        'ON public.exercise_practice_upload_recoveries';
END;
$$;

REVOKE ALL ON FUNCTION public.require_practice_source_live_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.require_practice_processing_authority_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION public.reserve_synthetic_practice_upload_v1(
    UUID, UUID, INTEGER, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_synthetic_practice_upload_v1(
    UUID, UUID, INTEGER, TEXT, TEXT, TEXT, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.attach_synthetic_practice_attempt_v1(
    UUID, UUID, UUID, TEXT, TEXT, TEXT, INTEGER, TIMESTAMPTZ,
    TIMESTAMPTZ, JSONB, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.attach_synthetic_practice_attempt_v1(
    UUID, UUID, UUID, TEXT, TEXT, TEXT, INTEGER, TIMESTAMPTZ,
    TIMESTAMPTZ, JSONB, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_practice_validity_v1(
    UUID, UUID, INTEGER, TEXT, TEXT[], TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_practice_validity_v1(
    UUID, UUID, INTEGER, TEXT, TEXT[], TEXT, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.record_synthetic_practice_measurement_v1(
    UUID, INTEGER, TEXT, TEXT, JSONB, JSONB, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_synthetic_practice_measurement_v1(
    UUID, INTEGER, TEXT, TEXT, JSONB, JSONB, TEXT, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.freeze_synthetic_practice_selection_v1(
    UUID, UUID, INTEGER, INTEGER, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_synthetic_practice_selection_v1(
    UUID, UUID, INTEGER, INTEGER, TEXT
) TO service_role;

COMMENT ON TABLE public.exercise_practice_attempts IS
    'Synthetic-only exact practice capture evidence. Raw measurements and human judgments remain separate; no row is an improvement label.';

COMMIT;
