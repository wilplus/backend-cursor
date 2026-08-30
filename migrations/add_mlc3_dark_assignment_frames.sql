-- 0314 · MLC-3-D2 / M3-3. Dark, non-exposure assignment contracts only.
-- No seeds, producers, flags, policy activation, jobs, labels or releases.
BEGIN;

-- A verification receipt is evidence of availability, not a permanent promise
-- that an immutable object still exists. No provider is called by this RPC.
CREATE TABLE IF NOT EXISTS public.exercise_media_availability_checks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    media_object_id UUID NOT NULL REFERENCES public.exercise_media_objects(id),
    availability TEXT NOT NULL CHECK (availability IN ('available','missing','checksum_mismatch','unavailable')),
    observed_sha256 TEXT NULL CHECK (observed_sha256 ~ '^[0-9a-f]{64}$'),
    verification_evidence_sha256 TEXT NOT NULL CHECK (verification_evidence_sha256 ~ '^[0-9a-f]{64}$'),
    checked_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    recorded_xid XID8 NOT NULL DEFAULT pg_current_xact_id(),
    idempotency_key TEXT NOT NULL UNIQUE,
    CHECK (expires_at > checked_at AND expires_at <= checked_at + interval '5 minutes')
);
CREATE INDEX IF NOT EXISTS exercise_media_checks_time_idx ON public.exercise_media_availability_checks
    (media_object_id,checked_at DESC,recorded_at DESC);

-- Empty catalogue is a valid no-match universe; v1 remains unchanged.
ALTER TABLE public.exercise_catalog_snapshots DROP CONSTRAINT IF EXISTS exercise_catalog_snapshots_version_count_check;
ALTER TABLE public.exercise_catalog_snapshots ADD CONSTRAINT exercise_catalog_snapshots_version_count_check CHECK (version_count >= 0);

CREATE TABLE IF NOT EXISTS public.learning_profile_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    speaker_id UUID NOT NULL REFERENCES public.ml_speakers(id),
    audio_lineage_id UUID NOT NULL REFERENCES public.exercise_audio_lineages(id),
    need_contract_id UUID NOT NULL REFERENCES public.exercise_need_contracts(id),
    prediction_id UUID NOT NULL REFERENCES public.ml_machine_predictions(id),
    authorization_check_id UUID NOT NULL REFERENCES public.exercise_authorization_checks(id),
    features JSONB NOT NULL CHECK (jsonb_typeof(features) = 'object'),
    audio_quality TEXT NOT NULL CHECK (audio_quality IN ('usable', 'audio_unclear', 'unreliable')),
    detector_version TEXT NOT NULL,
    feature_schema_version TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    source_code_version TEXT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    recorded_xid XID8 NOT NULL DEFAULT pg_current_xact_id(),
    event_sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    observation_sha256 TEXT NOT NULL CHECK (observation_sha256 ~ '^[0-9a-f]{64}$'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (audio_lineage_id, need_contract_id, prediction_id),
    FOREIGN KEY (speaker_id, acquisition_principal_id)
        REFERENCES public.ml_speaker_principals(speaker_id, acquisition_principal_id)
);
CREATE INDEX IF NOT EXISTS exercise_observations_asof_idx ON public.learning_profile_observations
    (speaker_id, need_contract_id, event_sequence);

CREATE TABLE IF NOT EXISTS public.exercise_selection_feature_snapshots (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    speaker_id UUID NOT NULL REFERENCES public.ml_speakers(id),
    audio_lineage_id UUID NOT NULL REFERENCES public.exercise_audio_lineages(id),
    source_observation_id UUID NOT NULL REFERENCES public.learning_profile_observations(id),
    assignment_at TIMESTAMPTZ NOT NULL,
    source_visibility_snapshot PG_SNAPSHOT NOT NULL,
    snapshot_schema_version TEXT NOT NULL CHECK (snapshot_schema_version = 'exercise-asof-v1'),
    snapshot JSONB NOT NULL CHECK (jsonb_typeof(snapshot) = 'object'),
    snapshot_sha256 TEXT NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

CREATE TABLE IF NOT EXISTS public.exercise_candidate_sets (
    id UUID PRIMARY KEY,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    speaker_id UUID NOT NULL REFERENCES public.ml_speakers(id),
    audio_lineage_id UUID NOT NULL REFERENCES public.exercise_audio_lineages(id),
    need_contract_id UUID NOT NULL REFERENCES public.exercise_need_contracts(id),
    catalog_snapshot_id UUID NOT NULL REFERENCES public.exercise_catalog_snapshots(id),
    feature_snapshot_id UUID NOT NULL UNIQUE REFERENCES public.exercise_selection_feature_snapshots(id),
    authorization_check_id UUID NOT NULL REFERENCES public.exercise_authorization_checks(id),
    source_take_id UUID NOT NULL,
    source_policy_version TEXT NOT NULL CHECK (source_policy_version = 'take-feedback-policy-v3-universal-dark-v3'),
    source_block_id TEXT NOT NULL,
    source_candidate_id TEXT NOT NULL,
    source_frame_hash TEXT NOT NULL CHECK (source_frame_hash ~ '^[0-9a-f]{64}$'),
    policy_version TEXT NOT NULL CHECK (policy_version = 'exercise-assignment-dark-v1'),
    execution_kind TEXT NOT NULL CHECK (execution_kind = 'deterministic_policy'),
    model_assignment_id UUID NULL CHECK (model_assignment_id IS NULL),
    candidate_count INTEGER NOT NULL CHECK (candidate_count >= 0),
    eligible_count INTEGER NOT NULL CHECK (eligible_count BETWEEN 0 AND candidate_count),
    inventory JSONB NOT NULL CHECK (jsonb_typeof(inventory) = 'array'),
    pool_sha256 TEXT NOT NULL CHECK (pool_sha256 ~ '^[0-9a-f]{64}$'),
    versions JSONB NOT NULL CHECK (jsonb_typeof(versions) = 'object'),
    frame_sha256 TEXT NOT NULL CHECK (frame_sha256 ~ '^[0-9a-f]{64}$'),
    assigned_at TIMESTAMPTZ NOT NULL,
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    rendered_exposure_id UUID NULL CHECK (rendered_exposure_id IS NULL),
    FOREIGN KEY (source_take_id, source_policy_version)
        REFERENCES public.take_feedback_policy_v3_shadow_frames(take_session_id, policy_version)
);

CREATE TABLE IF NOT EXISTS public.exercise_candidates (
    candidate_set_id UUID NOT NULL REFERENCES public.exercise_candidate_sets(id),
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    exercise_version_id UUID NOT NULL REFERENCES public.exercise_versions(id),
    eligibility TEXT NOT NULL CHECK (eligibility IN ('eligible','excluded')),
    exclusion_reasons TEXT[] NOT NULL CHECK (exclusion_reasons <@ ARRAY[
        'inactive_version','superseded_version','safety_not_approved','case_specific_not_shared',
        'need_contract_mismatch','need_not_approved','language_mismatch',
        'media_unavailable','audio_unreliable','audio_unclear','missing_need_features',
        'unsupported_safety_contract','unreproducible_gate','need_outside_contract',
        'already_assigned_version'
    ]::text[]),
    deterministic_rank INTEGER NULL CHECK (deterministic_rank > 0),
    probability_numerator BIGINT NOT NULL CHECK (probability_numerator >= 0),
    probability_denominator BIGINT NOT NULL CHECK (probability_denominator > 0),
    probability NUMERIC NOT NULL CHECK (probability BETWEEN 0 AND 1),
    probability_floor_reason TEXT NULL CHECK (probability_floor_reason = 'insufficient_assignment_probability'),
    inputs JSONB NOT NULL CHECK (jsonb_typeof(inputs) = 'object'),
    candidate_sha256 TEXT NOT NULL CHECK (candidate_sha256 ~ '^[0-9a-f]{64}$'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    PRIMARY KEY (candidate_set_id, exercise_version_id),
    UNIQUE (candidate_set_id, deterministic_rank),
    CHECK ((eligibility = 'eligible' AND cardinality(exclusion_reasons) = 0
            AND deterministic_rank IS NOT NULL AND probability_numerator > 0)
        OR (eligibility = 'excluded' AND cardinality(exclusion_reasons) > 0
            AND deterministic_rank IS NULL AND probability_numerator = 0 AND probability = 0)),
    CHECK (probability = probability_numerator::numeric / probability_denominator)
);

CREATE TABLE IF NOT EXISTS public.exercise_assignments (
    id UUID PRIMARY KEY REFERENCES public.exercise_candidate_sets(id),
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    speaker_id UUID NOT NULL REFERENCES public.ml_speakers(id),
    audio_lineage_id UUID NOT NULL REFERENCES public.exercise_audio_lineages(id),
    need_contract_id UUID NOT NULL REFERENCES public.exercise_need_contracts(id),
    source_block_id TEXT NOT NULL,
    exposure_policy_version TEXT NOT NULL CHECK (exposure_policy_version = 'exercise-80-20-simulation-v1'),
    selected_exercise_version_id UUID NULL REFERENCES public.exercise_versions(id),
    outcome TEXT NOT NULL CHECK (outcome IN ('dark_selected','dark_no_match')),
    assigned_at TIMESTAMPTZ NOT NULL,
    recorded_xid XID8 NOT NULL DEFAULT pg_current_xact_id(),
    request_sha256 TEXT NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(btrim(idempotency_key)) > 0),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK ((outcome = 'dark_no_match' AND selected_exercise_version_id IS NULL)
        OR (outcome = 'dark_selected' AND selected_exercise_version_id IS NOT NULL)),
    UNIQUE (speaker_id, audio_lineage_id, source_block_id, need_contract_id, exposure_policy_version),
    FOREIGN KEY (id, selected_exercise_version_id)
        REFERENCES public.exercise_candidates(candidate_set_id, exercise_version_id)
);
CREATE INDEX IF NOT EXISTS exercise_assignment_history_idx ON public.exercise_assignments
    (speaker_id, need_contract_id, assigned_at);

CREATE TABLE IF NOT EXISTS public.exercise_randomization_assignments (
    assignment_id UUID PRIMARY KEY REFERENCES public.exercise_assignments(id),
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    randomization_unit_sha256 TEXT NOT NULL UNIQUE CHECK (randomization_unit_sha256 ~ '^[0-9a-f]{64}$'),
    rng_algorithm_version TEXT NOT NULL CHECK (rng_algorithm_version = 'sha256-first52-v1'),
    protected_seed BYTEA NOT NULL CHECK (octet_length(protected_seed) = 32),
    seed_commitment_sha256 TEXT NOT NULL CHECK (seed_commitment_sha256 ~ '^[0-9a-f]{64}$'),
    draw NUMERIC NOT NULL CHECK (draw >= 0 AND draw < 1),
    selection_mode TEXT NOT NULL CHECK (selection_mode IN (
        'no_match','deterministic_singleton','simulated_top','simulated_exploration'
    )),
    selected_rank INTEGER NULL CHECK (selected_rank > 0),
    minimum_probability NUMERIC NOT NULL CHECK (minimum_probability = 0.01),
    prior_assignment_ids UUID[] NOT NULL,
    repetition_state TEXT NOT NULL CHECK (repetition_state IN ('first_dark_assignment','repeated_dark_assignment')),
    causal_evaluation_exclusion TEXT NOT NULL CHECK (causal_evaluation_exclusion = 'dark_non_exposure'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

CREATE TABLE IF NOT EXISTS public.exercise_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id UUID NOT NULL REFERENCES public.exercise_assignments(id),
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    blind_packet_id UUID NOT NULL REFERENCES public.exercise_blind_packets(id),
    judgment_id UUID NOT NULL REFERENCES public.ml_judgments(id),
    reveal_event_id UUID NOT NULL REFERENCES public.exercise_blind_packet_events(id),
    authorization_check_id UUID NOT NULL REFERENCES public.exercise_authorization_checks(id),
    reviewer_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    state TEXT NOT NULL CHECK (state = 'dark_pending'),
    reason_code TEXT NOT NULL CHECK (reason_code = 'no_eligible_exercise'),
    request_sha256 TEXT NOT NULL CHECK (request_sha256 ~ '^[0-9a-f]{64}$'),
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (assignment_id, reviewer_principal_id)
);

-- Internal helpers are not executable by runtime roles.
CREATE OR REPLACE FUNCTION public.exercise_json_sha256_v1(p_value JSONB)
RETURNS TEXT LANGUAGE sql IMMUTABLE SET search_path = public
AS $$ SELECT encode(extensions.digest(convert_to(p_value::text, 'UTF8'), 'sha256'), 'hex') $$;

CREATE OR REPLACE FUNCTION public.require_exercise_assignment_authority_v1(p_check UUID,p_principal UUID)
RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_REQUIRES_READ_COMMITTED'; END IF;
    PERFORM public.require_current_exercise_authorization_v1(p_check,p_principal,'catalog_assignment');
    -- The accepted foundation helper uses transaction-time `now()`. A block
    -- becoming effective during a keyed-lock wait must also stop this work.
    IF EXISTS (SELECT 1 FROM public.processing_service_blocks
        WHERE acquisition_principal_id=p_principal AND effective_at<=clock_timestamp())
    THEN RAISE EXCEPTION 'EXERCISE_CURRENT_AUTHORIZATION_REVOKED'; END IF;
    IF NOT EXISTS (SELECT 1 FROM public.exercise_authorization_checks
        WHERE id=p_check AND checked_at >= clock_timestamp()-interval '5 minutes'
          AND checked_at <= clock_timestamp())
    THEN RAISE EXCEPTION 'EXERCISE_CURRENT_AUTHORIZATION_REQUIRED'; END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.finalize_exercise_catalog_snapshot_v2(
    p_scope_language_code TEXT,p_idempotency_key TEXT,p_created_by TEXT
) RETURNS public.exercise_catalog_snapshots
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE result public.exercise_catalog_snapshots; manifest JSONB; cutoff TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF COALESCE(btrim(p_idempotency_key),'') = '' OR COALESCE(btrim(p_created_by),'') = ''
       OR (p_scope_language_code IS NOT NULL AND p_scope_language_code !~ '^[a-z]{2}(-[A-Z]{2})?$')
    THEN RAISE EXCEPTION 'EXERCISE_CATALOG_SNAPSHOT_INVALID'; END IF;
    PERFORM pg_advisory_xact_lock(hashtextextended('exercise-catalog-v2:' || p_idempotency_key,0));
    SELECT * INTO result FROM public.exercise_catalog_snapshots WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NOT NULL THEN
        IF result.catalog_policy_version <> 'exercise-complete-catalog-v2'
           OR result.scope_language_code IS DISTINCT FROM p_scope_language_code
           OR result.created_by <> p_created_by
        THEN RAISE EXCEPTION 'EXERCISE_CATALOG_IDEMPOTENCY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    SELECT COALESCE(jsonb_agg(jsonb_build_object('exercise_version_id',v.id,'exercise_key',d.exercise_key,
        'version_number',v.version_number,'version_sha256',v.version_sha256,
        'catalogue_state',v.catalogue_state,'safety_state',v.safety_state) ORDER BY d.exercise_key COLLATE "C",v.version_number),'[]')
      INTO manifest FROM public.exercise_versions v JOIN public.exercise_definitions d ON d.id = v.exercise_definition_id
     WHERE v.created_at <= cutoff AND (p_scope_language_code IS NULL OR d.language_code = p_scope_language_code);
    INSERT INTO public.exercise_catalog_snapshots (catalog_policy_version,scope_language_code,version_cutoff_at,
        version_count,manifest_sha256,idempotency_key,created_by)
    VALUES ('exercise-complete-catalog-v2',p_scope_language_code,cutoff,jsonb_array_length(manifest),
        public.exercise_json_sha256_v1(manifest),p_idempotency_key,p_created_by) RETURNING * INTO result;
    INSERT INTO public.exercise_catalog_snapshot_items (catalog_snapshot_id,exercise_version_id,exercise_key,
        version_number,catalogue_state,safety_state,item_sha256)
    SELECT result.id,(m->>'exercise_version_id')::uuid,m->>'exercise_key',(m->>'version_number')::integer,
        m->>'catalogue_state',m->>'safety_state',public.exercise_json_sha256_v1(m)
    FROM jsonb_array_elements(manifest) m;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_exercise_media_availability_v1(
    p_media_object_id UUID,p_availability TEXT,p_observed_sha256 TEXT,
    p_evidence_sha256 TEXT,p_checked_at TIMESTAMPTZ,p_idempotency_key TEXT
) RETURNS public.exercise_media_availability_checks
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE m public.exercise_media_objects; result public.exercise_media_availability_checks;
BEGIN
    SELECT * INTO STRICT m FROM public.exercise_media_objects WHERE id = p_media_object_id;
    IF p_checked_at IS NULL OR p_checked_at > clock_timestamp()
       OR p_checked_at < clock_timestamp() - interval '5 minutes'
       OR COALESCE(btrim(p_idempotency_key),'') = ''
       OR (p_availability = 'available' AND p_observed_sha256 IS DISTINCT FROM m.exact_bytes_sha256)
    THEN RAISE EXCEPTION 'EXERCISE_MEDIA_VERIFICATION_INVALID'; END IF;
    INSERT INTO public.exercise_media_availability_checks (
        media_object_id,availability,observed_sha256,verification_evidence_sha256,checked_at,expires_at,idempotency_key
    ) VALUES (m.id,p_availability,p_observed_sha256,p_evidence_sha256,p_checked_at,
        p_checked_at + interval '5 minutes',p_idempotency_key)
    ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO STRICT result FROM public.exercise_media_availability_checks WHERE idempotency_key = p_idempotency_key;
    IF result.media_object_id <> m.id OR result.availability <> p_availability
       OR result.observed_sha256 IS DISTINCT FROM p_observed_sha256
       OR result.verification_evidence_sha256 <> p_evidence_sha256 OR result.checked_at <> p_checked_at
    THEN RAISE EXCEPTION 'EXERCISE_MEDIA_VERIFICATION_REPLAY_CONFLICT'; END IF;
    RETURN result;
END;
$$;

CREATE OR REPLACE FUNCTION public.exercise_evidence_matches_audio_v1(p_evidence UUID, p_lineage UUID)
RETURNS BOOLEAN LANGUAGE sql STABLE SET search_path = public
AS $$
SELECT EXISTS (
    SELECT 1 FROM public.exercise_audio_lineages l
    JOIN public.ml_evidence_spans e ON e.id = p_evidence
    JOIN public.ml_object_artifacts o ON o.id = e.object_artifact_id
    JOIN public.processing_audio_objects a ON a.id = l.processing_audio_object_id
    WHERE l.id = p_lineage
      AND e.acquisition_principal_id = l.acquisition_principal_id
      AND e.speaker_id = l.speaker_id AND e.project_id = l.project_id
      AND e.take_id = l.take_id AND e.recording_attempt_id = l.recording_attempt_id
      AND o.acquisition_principal_id = l.acquisition_principal_id AND o.speaker_id = l.speaker_id
      AND o.object_store = 'cloudflare_r2' AND a.storage_provider = 'r2'
      AND o.bucket = a.bucket AND o.object_key = a.object_key
      AND o.sha256 = a.exact_bytes_sha256 AND o.sha256 = l.exact_audio_sha256
      AND o.byte_size = a.byte_size AND a.byte_size = l.object_byte_size
      AND a.deleted_at IS NULL
      AND a.acquisition_principal_id = l.acquisition_principal_id
      AND (e.coordinates->>'start_ms')::numeric = l.start_offset_ms
      AND (e.coordinates->>'end_ms')::numeric = l.start_offset_ms + l.duration_ms
      AND EXISTS (SELECT 1 FROM public.snippets s WHERE s.id = l.snippet_id
          AND s.session_id = l.take_id AND s.recording_id = l.recording_id
          AND s.start_offset_ms = l.start_offset_ms AND s.duration_ms = l.duration_ms)
)
$$;

CREATE OR REPLACE FUNCTION public.record_exercise_profile_observation_v1(
    p_audio_lineage_id UUID, p_need_contract_id UUID,
    p_prediction_id UUID, p_authorization_check_id UUID
) RETURNS public.learning_profile_observations
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    l public.exercise_audio_lineages; n public.exercise_need_contracts;
    p public.ml_machine_predictions; c public.ml_classification_runs;
    r public.ml_model_runs; o public.learning_profile_observations; f JSONB; h TEXT;
BEGIN
    SELECT * INTO STRICT l FROM public.exercise_audio_lineages WHERE id = p_audio_lineage_id;
    PERFORM public.require_exercise_assignment_authority_v1(p_authorization_check_id,l.acquisition_principal_id);
    SELECT * INTO STRICT n FROM public.exercise_need_contracts WHERE id = p_need_contract_id;
    SELECT * INTO STRICT p FROM public.ml_machine_predictions WHERE id = p_prediction_id;
    SELECT * INTO STRICT c FROM public.ml_classification_runs WHERE model_run_id = p.classification_run_id;
    SELECT * INTO STRICT r FROM public.ml_model_runs WHERE id = c.model_run_id;
    IF NOT public.exercise_evidence_matches_audio_v1(p.evidence_span_id, l.id)
       OR r.learning_surface_id <> 'confidence_classification' OR r.status <> 'succeeded'
       OR c.detector_version <> 'voice-confidence-universal-v3'
       OR n.approval_state <> 'approved' OR c.feature_schema_version <> n.feature_schema_version
       OR p.output_schema_version <> 'mlc3-acoustic-observation-v1'
       OR r.completed_at > clock_timestamp()
    THEN RAISE EXCEPTION 'EXERCISE_OBSERVATION_PROVENANCE_INVALID'; END IF;
    f := p.raw_output->'acoustic_features';
    IF jsonb_typeof(f) IS DISTINCT FROM 'object'
       OR EXISTS (SELECT 1 FROM jsonb_each(f) kv
          WHERE NOT kv.key = ANY(n.allowed_feature_names) OR jsonb_typeof(kv.value) <> 'number')
       OR NOT COALESCE(p.raw_output->>'audio_quality', '') = ANY(ARRAY['usable','audio_unclear','unreliable'])
    THEN RAISE EXCEPTION 'EXERCISE_OBSERVATION_FEATURE_CONTRACT_INVALID'; END IF;
    -- Missing features are retained, then typed-excluded by the gate, never invented.
    h := public.exercise_json_sha256_v1(jsonb_build_object(
        'lineage',l.lineage_sha256,'need',n.contract_sha256,'prediction',p.id,
        'features',f,'quality',p.raw_output->>'audio_quality','run',r.id,
        'detector',c.detector_version,'extractor',c.feature_extractor_version,
        'schema',c.feature_schema_version,'code',r.code_version,'observed_at',r.completed_at));
    INSERT INTO public.learning_profile_observations (
        acquisition_principal_id,speaker_id,audio_lineage_id,need_contract_id,prediction_id,
        authorization_check_id,features,audio_quality,detector_version,feature_schema_version,
        extractor_version,source_code_version,observed_at,observation_sha256
    ) VALUES (l.acquisition_principal_id,l.speaker_id,l.id,n.id,p.id,p_authorization_check_id,
        f,p.raw_output->>'audio_quality',c.detector_version,c.feature_schema_version,
        c.feature_extractor_version,r.code_version,r.completed_at,h)
    ON CONFLICT (audio_lineage_id,need_contract_id,prediction_id) DO NOTHING;
    SELECT * INTO STRICT o FROM public.learning_profile_observations
     WHERE audio_lineage_id = l.id AND need_contract_id = n.id AND prediction_id = p.id;
    IF o.observation_sha256 <> h THEN RAISE EXCEPTION 'EXERCISE_OBSERVATION_REPLAY_CONFLICT'; END IF;
    RETURN o;
END;
$$;

-- A small declarative, versioned range gate. No clinical rules or unapproved
-- acoustic thresholds are seeded. Unknown contracts fail closed, not best-effort.
CREATE OR REPLACE FUNCTION public.exercise_need_gate_reasons_v1(
    p_need public.exercise_need_contracts, p_features JSONB, p_quality TEXT
) RETURNS TEXT[] LANGUAGE plpgsql IMMUTABLE SET search_path = public
AS $$
DECLARE reasons TEXT[] := '{}'; gate JSONB; feature RECORD; bounds JSONB;
BEGIN
    IF p_need.approval_state <> 'approved' THEN reasons := array_append(reasons,'need_not_approved'); END IF;
    IF p_quality <> 'usable' THEN
        reasons := array_append(reasons,CASE WHEN p_quality = 'audio_unclear' THEN 'audio_unclear' ELSE 'audio_unreliable' END);
    END IF;
    IF NOT p_features ?& p_need.required_feature_names THEN
        reasons := array_append(reasons,'missing_need_features');
    END IF;
    -- Nonempty contraindications need their own approved implementation;
    -- never interpret a free-text medical/safety rule as a passing boolean.
    IF p_need.contraindications <> '[]'::jsonb THEN
        reasons := array_append(reasons,'unsupported_safety_contract');
    END IF;
    gate := p_need.operational_definition->'assignment_gate';
    IF jsonb_typeof(gate) IS DISTINCT FROM 'object'
       OR gate->>'schema_version' IS DISTINCT FROM 'exercise-need-gate-v1'
       OR jsonb_typeof(gate->'feature_ranges') IS DISTINCT FROM 'object'
       OR gate - ARRAY['schema_version','feature_ranges'] <> '{}'::jsonb
       OR NOT (gate->'feature_ranges') ?& p_need.required_feature_names
    THEN RETURN array_append(reasons,'unreproducible_gate'); END IF;
    FOR feature IN SELECT * FROM jsonb_each(gate->'feature_ranges') LOOP
        bounds := feature.value;
        IF NOT feature.key = ANY(p_need.allowed_feature_names)
           OR jsonb_typeof(bounds) <> 'object'
           OR bounds - ARRAY['min','max'] <> '{}'::jsonb
           OR (NOT bounds ? 'min' AND NOT bounds ? 'max')
           OR (bounds ? 'min' AND jsonb_typeof(bounds->'min') <> 'number')
           OR (bounds ? 'max' AND jsonb_typeof(bounds->'max') <> 'number')
        THEN RETURN array_append(reasons,'unreproducible_gate'); END IF;
        IF (bounds->>'min')::numeric > (bounds->>'max')::numeric THEN
            RETURN array_append(reasons,'unreproducible_gate'); END IF;
        IF NOT p_features ? feature.key THEN
            reasons := array_append(reasons,'missing_need_features');
        ELSIF (p_features->>feature.key)::numeric < (bounds->>'min')::numeric
           OR (p_features->>feature.key)::numeric > (bounds->>'max')::numeric THEN
            reasons := array_append(reasons,'need_outside_contract');
        END IF;
    END LOOP;
    RETURN ARRAY(SELECT DISTINCT v FROM unnest(reasons) v ORDER BY v);
END;
$$;

CREATE OR REPLACE FUNCTION public.exercise_rng_draw_v1(p_seed BYTEA, p_unit TEXT)
RETURNS NUMERIC LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
SELECT ('x' || substr(encode(extensions.digest(p_seed || convert_to(p_unit,'UTF8'),'sha256'),'hex'),1,13))::bit(52)::bigint::numeric
       / 4503599627370496::numeric
$$;

CREATE OR REPLACE FUNCTION public.finalize_exercise_dark_assignment_v1(
    p_audio_lineage_id UUID, p_need_contract_id UUID, p_source_observation_id UUID,
    p_catalog_snapshot_id UUID, p_source_block_id TEXT, p_language_code TEXT,
    p_authorization_check_id UUID, p_idempotency_key TEXT
) RETURNS public.exercise_assignments
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    l public.exercise_audio_lineages; n public.exercise_need_contracts;
    o public.learning_profile_observations; catalog public.exercise_catalog_snapshots;
    source_frame public.take_feedback_policy_v3_shadow_frames;
    existing public.exercise_assignments;
    visibility PG_SNAPSHOT := pg_current_snapshot(); assignment_at TIMESTAMPTZ := clock_timestamp();
    assignment_id UUID := gen_random_uuid(); unit_hash TEXT; request_hash TEXT;
    block JSONB; source_candidate JSONB; feature_snapshot JSONB; versions JSONB;
    observation_inventory JSONB; prior_ids UUID[]; prior_versions UUID[];
    frame_inventory JSONB := '[]'; raw_inventory JSONB := '[]'; row_data RECORD;
    item JSONB; reasons TEXT[]; common_reasons TEXT[];
    rank_number INTEGER := 0; eligible_count INTEGER := 0; selected_rank INTEGER;
    numerator BIGINT; denominator BIGINT; probability NUMERIC;
    seed BYTEA := extensions.gen_random_bytes(32); draw NUMERIC; selection_mode TEXT;
    selected_version UUID; pool_hash TEXT; feature_hash TEXT; version_hash TEXT;
    media_check public.exercise_media_availability_checks;
BEGIN
    IF COALESCE(btrim(p_idempotency_key),'') = '' OR COALESCE(btrim(p_source_block_id),'') = ''
       OR COALESCE(p_language_code,'') !~ '^[a-z]{2}(-[A-Z]{2})?$'
    THEN RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_INPUT_INVALID'; END IF;
    SELECT * INTO STRICT l FROM public.exercise_audio_lineages WHERE id = p_audio_lineage_id;
    PERFORM public.require_exercise_assignment_authority_v1(p_authorization_check_id,l.acquisition_principal_id);
    SELECT * INTO STRICT n FROM public.exercise_need_contracts WHERE id = p_need_contract_id;
    SELECT * INTO STRICT o FROM public.learning_profile_observations WHERE id = p_source_observation_id;
    IF o.audio_lineage_id <> l.id OR o.need_contract_id <> n.id
       OR o.acquisition_principal_id <> l.acquisition_principal_id OR o.speaker_id <> l.speaker_id
       OR NOT public.exercise_evidence_matches_audio_v1(
            (SELECT evidence_span_id FROM public.ml_machine_predictions WHERE id = o.prediction_id), l.id)
    THEN RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_SOURCE_MISMATCH'; END IF;
    unit_hash := public.exercise_json_sha256_v1(jsonb_build_array(l.speaker_id,l.id,
        p_source_block_id,n.id,'exercise-80-20-simulation-v1'));
    request_hash := public.exercise_json_sha256_v1(jsonb_build_array(l.id,n.id,o.id,
        p_catalog_snapshot_id,p_source_block_id,p_language_code));
    -- Serialize every assignment for the same profile/need, not merely the
    -- idempotency key: simultaneous different clips cannot bypass repetition.
    PERFORM pg_advisory_xact_lock(hashtextextended('exercise-idem:' || p_idempotency_key,0));
    PERFORM pg_advisory_xact_lock(hashtextextended('exercise-profile:' || l.speaker_id::text || ':' || n.id::text,0));
    PERFORM public.require_exercise_assignment_authority_v1(p_authorization_check_id,l.acquisition_principal_id);
    SELECT a.* INTO existing FROM public.exercise_assignments a
    WHERE a.idempotency_key = p_idempotency_key;
    IF existing.id IS NULL THEN
        SELECT a.* INTO existing FROM public.exercise_assignments a
        WHERE a.speaker_id = l.speaker_id AND a.audio_lineage_id = l.id AND a.source_block_id = p_source_block_id
          AND a.need_contract_id = n.id AND a.exposure_policy_version = 'exercise-80-20-simulation-v1';
    END IF;
    IF existing.id IS NOT NULL THEN
        IF existing.request_sha256 <> request_hash THEN RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    -- The snapshot was captured BEFORE waiting for locks. A concurrent first
    -- assignment is either visible in that snapshot or forces a retry; it
    -- cannot silently become an assignment-time feature from the future.
    IF EXISTS (SELECT 1 FROM public.exercise_assignments a
        WHERE a.speaker_id = l.speaker_id AND a.need_contract_id = n.id
          AND (a.recorded_xid = pg_current_xact_id() OR NOT pg_visible_in_snapshot(a.recorded_xid,visibility)))
    THEN RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_CONCURRENT_HISTORY_RETRY' USING ERRCODE = '40001'; END IF;
    IF o.observed_at >= assignment_at OR o.recorded_at >= assignment_at
       OR o.recorded_xid = pg_current_xact_id() OR NOT pg_visible_in_snapshot(o.recorded_xid,visibility)
    THEN RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_SOURCE_NOT_COMMITTED_ASOF'; END IF;
    SELECT * INTO STRICT catalog FROM public.exercise_catalog_snapshots WHERE id = p_catalog_snapshot_id;
    IF catalog.finalized_at > assignment_at
       OR (catalog.scope_language_code IS NOT NULL AND catalog.scope_language_code <> p_language_code)
    THEN RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_CATALOG_SCOPE_INVALID'; END IF;
    -- A stale snapshot may be replayed, but cannot hide a newly retired,
    -- restricted, or otherwise changed version from a new assignment.
    IF EXISTS (SELECT 1 FROM public.exercise_versions v
        JOIN public.exercise_definitions d ON d.id = v.exercise_definition_id
        WHERE (catalog.scope_language_code IS NULL OR d.language_code = catalog.scope_language_code)
          AND NOT EXISTS (SELECT 1 FROM public.exercise_catalog_snapshot_items i
              WHERE i.catalog_snapshot_id = catalog.id AND i.exercise_version_id = v.id))
    THEN RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_CATALOG_STALE'; END IF;
    SELECT * INTO STRICT source_frame FROM public.take_feedback_policy_v3_shadow_frames
     WHERE take_session_id = l.take_id AND policy_version = 'take-feedback-policy-v3-universal-dark-v3';
    IF source_frame.acquisition_principal_id <> l.acquisition_principal_id
       OR source_frame.recording_id <> l.recording_id OR source_frame.created_at > assignment_at
    THEN RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_FRAME_LINEAGE_INVALID'; END IF;
    IF (SELECT count(*) FROM jsonb_array_elements(source_frame.frame->'blocks') b
         WHERE b->>'block_id' = p_source_block_id) <> 1 THEN
        RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_BLOCK_INVALID';
    END IF;
    SELECT b INTO block FROM jsonb_array_elements(source_frame.frame->'blocks') b
     WHERE b->>'block_id' = p_source_block_id;
    IF (SELECT count(*) FROM jsonb_array_elements(block->'confidence_candidates') c
         WHERE c->>'candidate_id' = block->>'selected_candidate_id') <> 1 THEN
        RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_CANDIDATE_INVALID';
    END IF;
    SELECT c INTO source_candidate FROM jsonb_array_elements(block->'confidence_candidates') c
     WHERE c->>'candidate_id' = block->>'selected_candidate_id';
    IF source_candidate->>'eligibility' IS DISTINCT FROM 'eligible'
       OR source_candidate->>'snippet_id' IS DISTINCT FROM l.snippet_id::text
       OR source_candidate #>> '{clip_identity,take_id}' IS DISTINCT FROM l.take_id::text
       OR source_candidate #>> '{clip_identity,recording_id}' IS DISTINCT FROM l.recording_id::text
       OR source_candidate #>> '{clip_identity,start_offset_ms}' IS DISTINCT FROM l.start_offset_ms::text
       OR source_candidate #>> '{clip_identity,duration_ms}' IS DISTINCT FROM l.duration_ms::text
    THEN RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_CANDIDATE_LINEAGE_INVALID'; END IF;
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
        'id',obs.id,'event_sequence',obs.event_sequence,'observed_at',obs.observed_at,
        'recorded_at',obs.recorded_at,'features',obs.features,'sha256',obs.observation_sha256
    ) ORDER BY obs.event_sequence),'[]'::jsonb) INTO observation_inventory
    FROM public.learning_profile_observations obs
    WHERE obs.speaker_id = l.speaker_id AND obs.need_contract_id = n.id
      AND obs.acquisition_principal_id = l.acquisition_principal_id
      AND obs.observed_at < assignment_at AND obs.recorded_at < assignment_at
      AND obs.recorded_xid <> pg_current_xact_id() AND pg_visible_in_snapshot(obs.recorded_xid,visibility);
    SELECT COALESCE(array_agg(a.id ORDER BY a.assigned_at,a.id),'{}'::uuid[]),
           COALESCE(array_agg(a.selected_exercise_version_id) FILTER (WHERE a.selected_exercise_version_id IS NOT NULL),'{}'::uuid[])
      INTO prior_ids,prior_versions FROM public.exercise_assignments a
     WHERE a.speaker_id = l.speaker_id AND a.need_contract_id = n.id;
    feature_snapshot := jsonb_build_object(
        'schema_version','exercise-asof-v1','assignment_at',assignment_at,
        'source_observation_id',o.id,'source_observation_sha256',o.observation_sha256,
        'source_features',o.features,'source_audio_quality',o.audio_quality,
        'profile_observations',observation_inventory,
        'max_source_event_sequence',(SELECT max((x->>'event_sequence')::bigint) FROM jsonb_array_elements(observation_inventory) x),
        'max_source_observed_at',(SELECT max((x->>'observed_at')::timestamptz) FROM jsonb_array_elements(observation_inventory) x),
        'max_source_recorded_at',(SELECT max((x->>'recorded_at')::timestamptz) FROM jsonb_array_elements(observation_inventory) x),
        'baseline_version','not_used-dark-v1','baseline_observation_ids','[]'::jsonb,
        'prior_assignment_ids',to_jsonb(prior_ids),'prior_rendered_exposures','[]'::jsonb,
        'exposure_state','not_collected_dark','owner_response','not_collected_dark',
        'excluded_observations',(SELECT COALESCE(jsonb_agg(jsonb_build_object(
            'id',obs.id,'reason',CASE WHEN obs.acquisition_principal_id <> l.acquisition_principal_id
            THEN 'cross_principal_not_authorized' ELSE 'not_available_asof' END) ORDER BY obs.event_sequence),'[]'::jsonb)
            FROM public.learning_profile_observations obs WHERE obs.speaker_id = l.speaker_id
            AND obs.need_contract_id = n.id AND (obs.acquisition_principal_id <> l.acquisition_principal_id
                OR obs.observed_at >= assignment_at OR obs.recorded_at >= assignment_at
                OR obs.recorded_xid = pg_current_xact_id() OR NOT pg_visible_in_snapshot(obs.recorded_xid,visibility)))
    );
    feature_snapshot := feature_snapshot || jsonb_build_object(
        'excluded_observation_count',jsonb_array_length(feature_snapshot->'excluded_observations'),
        'not_available_asof_count',(SELECT count(*) FROM jsonb_array_elements(feature_snapshot->'excluded_observations') x
            WHERE x->>'reason'='not_available_asof'),
        'cross_principal_exclusion_count',(SELECT count(*) FROM jsonb_array_elements(feature_snapshot->'excluded_observations') x
            WHERE x->>'reason'='cross_principal_not_authorized'));
    feature_hash := public.exercise_json_sha256_v1(feature_snapshot);
    common_reasons := public.exercise_need_gate_reasons_v1(n,o.features,o.audio_quality);
    -- Catalogue items, not a caller-supplied shortlist, are the complete universe.
    FOR row_data IN SELECT v.*,d.exercise_key,d.language_code,d.origin_kind,
            m.exact_bytes_sha256,m.verification_method,m.content_type,
            nc.approval_state AS need_approval
        FROM public.exercise_catalog_snapshot_items i
        JOIN public.exercise_versions v ON v.id = i.exercise_version_id
        JOIN public.exercise_definitions d ON d.id = v.exercise_definition_id
        JOIN public.exercise_media_objects m ON m.id = v.media_object_id
        JOIN public.exercise_need_contracts nc ON nc.id = v.need_contract_id
        WHERE i.catalog_snapshot_id = catalog.id
        ORDER BY d.exercise_key COLLATE "C",v.version_number DESC,v.id
    LOOP
        reasons := common_reasons;
        SELECT * INTO media_check FROM public.exercise_media_availability_checks c
         WHERE c.media_object_id = row_data.media_object_id
           AND c.checked_at < assignment_at AND c.recorded_at < assignment_at
           AND c.recorded_xid <> pg_current_xact_id() AND pg_visible_in_snapshot(c.recorded_xid,visibility)
         ORDER BY c.checked_at DESC,c.recorded_at DESC,c.id DESC LIMIT 1;
        IF row_data.catalogue_state <> 'active' THEN reasons := array_append(reasons,'inactive_version'); END IF;
        IF row_data.safety_state <> 'approved' THEN reasons := array_append(reasons,'safety_not_approved'); END IF;
        IF row_data.need_contract_id <> n.id THEN reasons := array_append(reasons,'need_contract_mismatch'); END IF;
        IF row_data.need_approval <> 'approved' THEN reasons := array_append(reasons,'need_not_approved'); END IF;
        IF row_data.language_code <> p_language_code THEN reasons := array_append(reasons,'language_mismatch'); END IF;
        IF row_data.origin_kind <> 'willab_library' THEN reasons := array_append(reasons,'case_specific_not_shared'); END IF;
        IF EXISTS (SELECT 1 FROM public.exercise_catalog_snapshot_items i
            WHERE i.catalog_snapshot_id = catalog.id AND i.exercise_key = row_data.exercise_key
              AND i.version_number > row_data.version_number)
        THEN reasons := array_append(reasons,'superseded_version'); END IF;
        IF row_data.id = ANY(prior_versions) THEN reasons := array_append(reasons,'already_assigned_version'); END IF;
        -- This version admits verified audio/video delivery only, with no free-form fallback.
        IF media_check.id IS NULL OR media_check.availability <> 'available'
           OR media_check.expires_at <= assignment_at
           OR media_check.observed_sha256 IS DISTINCT FROM row_data.exact_bytes_sha256
           OR row_data.exact_bytes_sha256 !~ '^[0-9a-f]{64}$'
           OR row_data.verification_method NOT IN ('read_after_write_sha256','trusted_object_checksum_sha256')
           OR NOT (row_data.content_type LIKE 'audio/%' OR row_data.content_type LIKE 'video/%')
        THEN reasons := array_append(reasons,'media_unavailable'); END IF;
        reasons := ARRAY(SELECT DISTINCT reason FROM unnest(reasons) reason ORDER BY reason);
        IF cardinality(reasons) = 0 THEN eligible_count := eligible_count + 1; END IF;
        raw_inventory := raw_inventory || jsonb_build_array(jsonb_build_object(
            'exercise_version_id',row_data.id,'exercise_key',row_data.exercise_key,
            'version_number',row_data.version_number,'reasons',to_jsonb(reasons),
            'inputs',jsonb_build_object('version_sha256',row_data.version_sha256,
                'media_sha256',row_data.exact_bytes_sha256,'need_contract_id',row_data.need_contract_id,
                'safety_state',row_data.safety_state,'catalogue_state',row_data.catalogue_state,
                'language_code',row_data.language_code,'delivery_kind',row_data.content_type,
                'origin_kind',row_data.origin_kind,'media_availability_check_id',media_check.id,
                'media_availability',media_check.availability,
                'media_verification_evidence_sha256',media_check.verification_evidence_sha256)));
    END LOOP;
    IF jsonb_array_length(raw_inventory) <> catalog.version_count THEN
        RAISE EXCEPTION 'EXERCISE_ASSIGNMENT_INVENTORY_INCOMPLETE'; END IF;
    draw := public.exercise_rng_draw_v1(seed,unit_hash);
    IF eligible_count = 0 THEN selection_mode := 'no_match'; selected_rank := NULL;
    ELSIF eligible_count = 1 THEN selection_mode := 'deterministic_singleton'; selected_rank := 1;
    ELSIF draw < 0.8 THEN selection_mode := 'simulated_top'; selected_rank := 1;
    ELSE selection_mode := 'simulated_exploration';
        selected_rank := 2 + floor((draw - 0.8) * 5 * (eligible_count - 1))::integer;
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(raw_inventory) LOOP
        IF jsonb_array_length(item->'reasons') = 0 THEN
            rank_number := rank_number + 1;
            numerator := CASE WHEN eligible_count = 1 THEN 1 WHEN rank_number = 1 THEN 4 ELSE 1 END;
            denominator := CASE WHEN eligible_count = 1 THEN 1 WHEN rank_number = 1 THEN 5 ELSE 5::bigint*(eligible_count-1) END;
            probability := numerator::numeric / denominator;
            item := item || jsonb_build_object('eligibility','eligible','rank',rank_number);
            IF rank_number = selected_rank THEN selected_version := (item->>'exercise_version_id')::uuid; END IF;
        ELSE numerator := 0; denominator := 1; probability := 0;
            item := item || jsonb_build_object('eligibility','excluded','rank',NULL);
        END IF;
        item := item || jsonb_build_object('probability_numerator',numerator,'probability_denominator',denominator,
            'probability',probability,'probability_floor_reason',CASE WHEN numerator > 0 AND probability < 0.01
                THEN 'insufficient_assignment_probability' ELSE NULL END);
        frame_inventory := frame_inventory || jsonb_build_array(item);
    END LOOP;
    pool_hash := public.exercise_json_sha256_v1(frame_inventory);
    versions := jsonb_build_object('contract','MLC-3-D2/M3-3','frame','exercise-assignment-dark-v1',
        'gate','exercise-need-gate-v1','fallback_ranker','exercise-key-C-version-desc-v1',
        'exposure_policy','exercise-80-20-simulation-v1','rng','sha256-first52-v1',
        'need_contract',n.contract_sha256,'catalog',catalog.manifest_sha256,
        'detector',o.detector_version,'acoustic_schema',o.feature_schema_version,
        'extractor',o.extractor_version,'source_code',o.source_code_version,
        'feedback_implementation',source_frame.frame->'implementation_versions',
        'gate_implementation_sha256',encode(extensions.digest(pg_get_functiondef(
            'public.exercise_need_gate_reasons_v1(public.exercise_need_contracts,jsonb,text)'::regprocedure),'sha256'),'hex'),
        'rng_implementation_sha256',encode(extensions.digest(pg_get_functiondef(
            'public.exercise_rng_draw_v1(bytea,text)'::regprocedure),'sha256'),'hex'),
        'assignment_implementation_sha256',encode(extensions.digest(
            pg_get_functiondef('public.finalize_exercise_dark_assignment_v1(uuid,uuid,uuid,uuid,text,text,uuid,text)'::regprocedure),
            'sha256'),'hex'));
    version_hash := public.exercise_json_sha256_v1(versions);
    PERFORM public.require_exercise_assignment_authority_v1(p_authorization_check_id,l.acquisition_principal_id);
    INSERT INTO public.exercise_selection_feature_snapshots VALUES (
        assignment_id,l.acquisition_principal_id,l.speaker_id,l.id,o.id,assignment_at,visibility,
        'exercise-asof-v1',feature_snapshot,feature_hash,false,false);
    INSERT INTO public.exercise_candidate_sets (
        id,acquisition_principal_id,speaker_id,audio_lineage_id,need_contract_id,catalog_snapshot_id,
        feature_snapshot_id,authorization_check_id,source_take_id,source_policy_version,source_block_id,
        source_candidate_id,source_frame_hash,policy_version,execution_kind,candidate_count,eligible_count,
        inventory,pool_sha256,versions,frame_sha256,assigned_at
    ) VALUES (assignment_id,l.acquisition_principal_id,l.speaker_id,l.id,n.id,catalog.id,assignment_id,
        p_authorization_check_id,l.take_id,source_frame.policy_version,p_source_block_id,
        block->>'selected_candidate_id',source_frame.frame_hash,'exercise-assignment-dark-v1',
        'deterministic_policy',catalog.version_count,eligible_count,frame_inventory,pool_hash,versions,
        public.exercise_json_sha256_v1(jsonb_build_array(unit_hash,request_hash,feature_hash,pool_hash,
            version_hash,draw,selected_rank,encode(extensions.digest(seed,'sha256'),'hex'))),assignment_at);
    FOR item IN SELECT value FROM jsonb_array_elements(frame_inventory) LOOP
        INSERT INTO public.exercise_candidates VALUES (
            assignment_id,l.acquisition_principal_id,(item->>'exercise_version_id')::uuid,
            item->>'eligibility',ARRAY(SELECT jsonb_array_elements_text(item->'reasons')),
            (item->>'rank')::integer,(item->>'probability_numerator')::bigint,
            (item->>'probability_denominator')::bigint,(item->>'probability')::numeric,
            item->>'probability_floor_reason',item->'inputs',public.exercise_json_sha256_v1(item),false,false);
    END LOOP;
    INSERT INTO public.exercise_assignments (
        id,acquisition_principal_id,speaker_id,audio_lineage_id,need_contract_id,source_block_id,
        exposure_policy_version,selected_exercise_version_id,outcome,assigned_at,request_sha256,idempotency_key
    ) VALUES (assignment_id,l.acquisition_principal_id,l.speaker_id,l.id,n.id,p_source_block_id,
        'exercise-80-20-simulation-v1',selected_version,
        CASE WHEN selected_version IS NULL THEN 'dark_no_match' ELSE 'dark_selected' END,
        assignment_at,request_hash,p_idempotency_key) RETURNING * INTO existing;
    INSERT INTO public.exercise_randomization_assignments VALUES (
        assignment_id,l.acquisition_principal_id,unit_hash,'sha256-first52-v1',seed,
        encode(extensions.digest(seed,'sha256'),'hex'),draw,selection_mode,selected_rank,0.01,prior_ids,
        CASE WHEN cardinality(prior_ids)=0 THEN 'first_dark_assignment' ELSE 'repeated_dark_assignment' END,
        'dark_non_exposure',false,false);
    RETURN existing;
END;
$$;

CREATE OR REPLACE FUNCTION public.register_exercise_no_match_request_v1(
    p_assignment_id UUID,p_blind_packet_id UUID,p_reviewer_principal_id UUID,
    p_authorization_check_id UUID,p_idempotency_key TEXT
) RETURNS public.exercise_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE a public.exercise_assignments; packet public.exercise_blind_packets;
    review public.ml_review_assignments; judgment public.ml_judgments;
    reveal public.exercise_blind_packet_events; submission public.exercise_blind_packet_events;
    result public.exercise_requests; h TEXT;
BEGIN
    SELECT * INTO STRICT a FROM public.exercise_assignments WHERE id = p_assignment_id;
    PERFORM public.require_exercise_assignment_authority_v1(p_authorization_check_id,a.acquisition_principal_id);
    IF a.outcome <> 'dark_no_match' THEN RAISE EXCEPTION 'EXERCISE_REQUEST_REQUIRES_NO_MATCH'; END IF;
    -- Unusable need/source evidence is not a request to invent an exercise.
    IF EXISTS (SELECT 1 FROM public.exercise_selection_feature_snapshots s
        JOIN public.learning_profile_observations o ON o.id = s.source_observation_id
        JOIN public.exercise_need_contracts n ON n.id = o.need_contract_id
        WHERE s.id = a.id AND cardinality(public.exercise_need_gate_reasons_v1(n,o.features,o.audio_quality)) > 0)
    THEN RAISE EXCEPTION 'EXERCISE_REQUEST_SOURCE_NOT_ACTIONABLE'; END IF;
    SELECT * INTO STRICT packet FROM public.exercise_blind_packets WHERE id = p_blind_packet_id;
    SELECT * INTO STRICT review FROM public.ml_review_assignments WHERE id = packet.review_assignment_id;
    SELECT * INTO submission FROM public.exercise_blind_packet_events
     WHERE blind_packet_id = packet.id AND event_kind = 'blind_judgment_submitted';
    SELECT * INTO judgment FROM public.ml_judgments WHERE id = submission.judgment_id;
    SELECT * INTO reveal FROM public.exercise_blind_packet_events
     WHERE blind_packet_id = packet.id AND event_kind = 'post_judgment_reveal_accessed';
    IF packet.audio_lineage_id <> a.audio_lineage_id OR packet.reviewer_principal_id <> p_reviewer_principal_id
       OR review.learning_surface_id <> 'confidence_classification'
       OR judgment.id IS NULL OR reveal.id IS NULL
       OR judgment.actor_provenance <> 'blind_coach'
       OR judgment.actor_principal_id <> p_reviewer_principal_id
       OR judgment.review_assignment_id <> review.id OR judgment.evidence_span_id <> review.evidence_span_id
       OR reveal.actor_principal_id IS DISTINCT FROM p_reviewer_principal_id
       OR submission.actor_principal_id IS DISTINCT FROM p_reviewer_principal_id
       OR reveal.occurred_at < submission.occurred_at OR reveal.created_at < submission.created_at
       OR reveal.occurred_at > clock_timestamp() OR submission.occurred_at > clock_timestamp()
       OR NOT public.exercise_evidence_matches_audio_v1(judgment.evidence_span_id,a.audio_lineage_id)
    THEN RAISE EXCEPTION 'EXERCISE_REQUEST_REQUIRES_EXACT_POST_BLIND_REVEAL'; END IF;
    IF COALESCE(btrim(p_idempotency_key),'') = '' THEN RAISE EXCEPTION 'EXERCISE_REQUEST_KEY_REQUIRED'; END IF;
    h := public.exercise_json_sha256_v1(jsonb_build_array(a.id,packet.id,p_reviewer_principal_id,judgment.id,reveal.id));
    PERFORM pg_advisory_xact_lock(hashtextextended('exercise-request-idem:' || p_idempotency_key,0));
    PERFORM pg_advisory_xact_lock(hashtextextended('exercise-request:' || a.id::text || ':' || p_reviewer_principal_id::text,0));
    PERFORM public.require_exercise_assignment_authority_v1(p_authorization_check_id,a.acquisition_principal_id);
    SELECT * INTO result FROM public.exercise_requests
     WHERE idempotency_key = p_idempotency_key;
    IF result.id IS NULL THEN
        SELECT * INTO result FROM public.exercise_requests
         WHERE assignment_id = a.id AND reviewer_principal_id = p_reviewer_principal_id;
    END IF;
    IF result.id IS NOT NULL THEN
        IF result.request_sha256 <> h THEN RAISE EXCEPTION 'EXERCISE_REQUEST_REPLAY_CONFLICT'; END IF;
        RETURN result;
    END IF;
    INSERT INTO public.exercise_requests (assignment_id,acquisition_principal_id,blind_packet_id,judgment_id,
        reveal_event_id,authorization_check_id,reviewer_principal_id,state,reason_code,request_sha256,idempotency_key)
    VALUES (a.id,a.acquisition_principal_id,packet.id,judgment.id,reveal.id,p_authorization_check_id,
        p_reviewer_principal_id,'dark_pending','no_eligible_exercise',h,p_idempotency_key) RETURNING * INTO result;
    RETURN result;
END;
$$;

-- The frame must commit as one complete object. Even a future definer RPC
-- cannot leave a header without candidates/assignment/RNG or pick exclusions.
CREATE OR REPLACE FUNCTION public.validate_exercise_assignment_finalization_v1()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE f public.exercise_candidate_sets; a public.exercise_assignments;
    s public.exercise_selection_feature_snapshots; r public.exercise_randomization_assignments;
    l public.exercise_audio_lineages; expected_rank INTEGER; expected_hash TEXT;
BEGIN
    SELECT * INTO STRICT f FROM public.exercise_candidate_sets WHERE id=NEW.id;
    SELECT * INTO a FROM public.exercise_assignments WHERE id=f.id;
    SELECT * INTO s FROM public.exercise_selection_feature_snapshots WHERE id=f.feature_snapshot_id;
    SELECT * INTO r FROM public.exercise_randomization_assignments WHERE assignment_id=f.id;
    SELECT * INTO STRICT l FROM public.exercise_audio_lineages WHERE id=f.audio_lineage_id;
    IF a.id IS NULL OR s.id IS NULL OR r.assignment_id IS NULL
       OR f.feature_snapshot_id <> f.id
       OR f.acquisition_principal_id <> l.acquisition_principal_id OR f.speaker_id <> l.speaker_id
       OR a.acquisition_principal_id <> f.acquisition_principal_id OR a.speaker_id <> f.speaker_id
       OR a.audio_lineage_id <> f.audio_lineage_id OR a.need_contract_id <> f.need_contract_id
       OR a.source_block_id <> f.source_block_id OR a.assigned_at <> f.assigned_at
       OR s.acquisition_principal_id <> f.acquisition_principal_id OR s.speaker_id <> f.speaker_id
       OR s.audio_lineage_id <> f.audio_lineage_id OR s.assignment_at <> f.assigned_at
       OR r.acquisition_principal_id <> f.acquisition_principal_id
       OR f.candidate_count <> jsonb_array_length(f.inventory)
       OR f.candidate_count <> (SELECT count(*) FROM public.exercise_candidates c WHERE c.candidate_set_id=f.id)
       OR f.candidate_count <> (SELECT version_count FROM public.exercise_catalog_snapshots WHERE id=f.catalog_snapshot_id)
       OR f.eligible_count <> (SELECT count(*) FROM public.exercise_candidates c WHERE c.candidate_set_id=f.id AND c.eligibility='eligible')
       OR f.pool_sha256 <> public.exercise_json_sha256_v1(f.inventory)
       OR s.snapshot_sha256 <> public.exercise_json_sha256_v1(s.snapshot)
       OR r.seed_commitment_sha256 <> encode(extensions.digest(r.protected_seed,'sha256'),'hex')
       OR r.draw <> public.exercise_rng_draw_v1(r.protected_seed,r.randomization_unit_sha256)
    THEN RAISE EXCEPTION 'EXERCISE_FINALIZATION_INCOMPLETE_OR_INVALID'; END IF;
    IF EXISTS (SELECT 1 FROM public.exercise_candidates c
        WHERE c.candidate_set_id=f.id AND (
            c.acquisition_principal_id <> f.acquisition_principal_id
            OR NOT EXISTS (SELECT 1 FROM public.exercise_catalog_snapshot_items i
                WHERE i.catalog_snapshot_id=f.catalog_snapshot_id AND i.exercise_version_id=c.exercise_version_id)
            OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(f.inventory) i
                WHERE i->>'exercise_version_id'=c.exercise_version_id::text
                AND public.exercise_json_sha256_v1(i)=c.candidate_sha256
                AND i->>'eligibility'=c.eligibility
                AND i->'reasons'=to_jsonb(c.exclusion_reasons)
                AND (i->>'rank')::integer IS NOT DISTINCT FROM c.deterministic_rank
                AND (i->>'probability_numerator')::bigint=c.probability_numerator
                AND (i->>'probability_denominator')::bigint=c.probability_denominator
                AND (i->>'probability')::numeric=c.probability
                AND i->'inputs'=c.inputs)))
    THEN RAISE EXCEPTION 'EXERCISE_FINALIZATION_CANDIDATE_INVALID'; END IF;
    expected_rank := CASE WHEN f.eligible_count=0 THEN NULL WHEN f.eligible_count=1 OR r.draw<0.8 THEN 1
        ELSE 2+floor((r.draw-0.8)*5*(f.eligible_count-1))::integer END;
    IF r.selected_rank IS DISTINCT FROM expected_rank
       OR a.selected_exercise_version_id IS DISTINCT FROM (SELECT c.exercise_version_id
           FROM public.exercise_candidates c WHERE c.candidate_set_id=f.id AND c.deterministic_rank=expected_rank AND c.eligibility='eligible')
    THEN RAISE EXCEPTION 'EXERCISE_FINALIZATION_SELECTION_INVALID'; END IF;
    expected_hash := public.exercise_json_sha256_v1(jsonb_build_array(r.randomization_unit_sha256,a.request_sha256,
        s.snapshot_sha256,f.pool_sha256,public.exercise_json_sha256_v1(f.versions),r.draw,r.selected_rank,r.seed_commitment_sha256));
    IF f.frame_sha256 <> expected_hash THEN RAISE EXCEPTION 'EXERCISE_FINALIZATION_HASH_INVALID'; END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS exercise_assignment_atomic_finalization ON public.exercise_candidate_sets;
CREATE CONSTRAINT TRIGGER exercise_assignment_atomic_finalization AFTER INSERT ON public.exercise_candidate_sets
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.validate_exercise_assignment_finalization_v1();

CREATE OR REPLACE FUNCTION public.get_mlc3_dark_assignment_health_v1()
RETURNS JSONB LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public
AS $$ SELECT jsonb_build_object(
    'serves_user',false,'dataset_eligible',false,
    'assignments',(SELECT count(*) FROM public.exercise_assignments),
    'no_match',(SELECT count(*) FROM public.exercise_assignments WHERE outcome = 'dark_no_match'),
    'post_blind_requests',(SELECT count(*) FROM public.exercise_requests),
    'incomplete_frames',(SELECT count(*) FROM public.exercise_candidate_sets f
        WHERE f.candidate_count <> (SELECT count(*) FROM public.exercise_candidates c WHERE c.candidate_set_id=f.id)
           OR NOT EXISTS (SELECT 1 FROM public.exercise_assignments a WHERE a.id=f.id)
           OR NOT EXISTS (SELECT 1 FROM public.exercise_randomization_assignments r WHERE r.assignment_id=f.id)),
    'invalid_selections',(SELECT count(*) FROM public.exercise_assignments a
        JOIN public.exercise_candidates c ON c.candidate_set_id=a.id AND c.exercise_version_id=a.selected_exercise_version_id
        WHERE c.eligibility <> 'eligible')) $$;

-- All writes use the validating RPCs. No user/coach can read seeds, frames,
-- profiles or requests; no RPC renders/exposes them or dispatches a job.
ALTER TABLE public.learning_profile_observations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_media_availability_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_selection_feature_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_candidate_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_randomization_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_requests ENABLE ROW LEVEL SECURITY;
DO $$
DECLARE relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY['exercise_media_availability_checks','learning_profile_observations','exercise_selection_feature_snapshots',
        'exercise_candidate_sets','exercise_candidates','exercise_assignments','exercise_randomization_assignments','exercise_requests']
    LOOP
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role',relation_name);
        EXECUTE format('GRANT SELECT ON public.%I TO service_role',relation_name);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',relation_name || '_append_only',relation_name);
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.reject_mlc2_immutable_mutation()',
            relation_name || '_append_only',relation_name);
    END LOOP;
END;
$$;
REVOKE ALL ON SEQUENCE public.learning_profile_observations_event_sequence_seq FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.exercise_json_sha256_v1(JSONB) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.require_exercise_assignment_authority_v1(UUID,UUID) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.validate_exercise_assignment_finalization_v1() FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.exercise_evidence_matches_audio_v1(UUID,UUID) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.exercise_need_gate_reasons_v1(public.exercise_need_contracts,JSONB,TEXT) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.exercise_rng_draw_v1(BYTEA,TEXT) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.record_exercise_profile_observation_v1(UUID,UUID,UUID,UUID) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_profile_observation_v1(UUID,UUID,UUID,UUID) TO service_role;
REVOKE ALL ON FUNCTION public.record_exercise_media_availability_v1(UUID,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_media_availability_v1(UUID,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT) TO service_role;
REVOKE ALL ON FUNCTION public.finalize_exercise_catalog_snapshot_v2(TEXT,TEXT,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_exercise_catalog_snapshot_v2(TEXT,TEXT,TEXT) TO service_role;
REVOKE ALL ON FUNCTION public.get_mlc3_dark_assignment_health_v1() FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc3_dark_assignment_health_v1() TO service_role;
REVOKE ALL ON FUNCTION public.finalize_exercise_dark_assignment_v1(UUID,UUID,UUID,UUID,TEXT,TEXT,UUID,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_exercise_dark_assignment_v1(UUID,UUID,UUID,UUID,TEXT,TEXT,UUID,TEXT) TO service_role;
REVOKE ALL ON FUNCTION public.register_exercise_no_match_request_v1(UUID,UUID,UUID,UUID,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.register_exercise_no_match_request_v1(UUID,UUID,UUID,UUID,TEXT) TO service_role;

COMMIT;
