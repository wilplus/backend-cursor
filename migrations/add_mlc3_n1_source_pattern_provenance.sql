-- MLC-3-N1-LIVE-D2 · disabled source-pattern compatibility foundation.
-- No serving, exposure, collection, dataset, training, evaluation or promotion.
BEGIN;

CREATE TABLE IF NOT EXISTS public.exercise_n1_source_pattern_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    audio_lineage_id UUID NOT NULL REFERENCES public.exercise_audio_lineages(id),
    source_observation_id UUID NOT NULL REFERENCES public.learning_profile_observations(id),
    machine_prediction_id UUID NOT NULL REFERENCES public.ml_machine_predictions(id),
    source_pattern TEXT NOT NULL CHECK (source_pattern IN (
        'low_confidence_rushing_dominant','near_confident','confident'
    )),
    result_origin TEXT NOT NULL DEFAULT 'machine' CHECK (result_origin='machine'),
    source_pattern_policy_version TEXT NOT NULL
        CHECK (source_pattern_policy_version='confidence-pattern-source-v1'),
    ordinal_policy_version TEXT NOT NULL
        CHECK (ordinal_policy_version='confidence-pattern-distance-v1'),
    prediction_output_sha256 TEXT NOT NULL CHECK (prediction_output_sha256 ~ '^[0-9a-f]{64}$'),
    result_sha256 TEXT NOT NULL CHECK (result_sha256 ~ '^[0-9a-f]{64}$'),
    completed_at TIMESTAMPTZ NOT NULL,
    recorded_xid XID8 NOT NULL DEFAULT pg_current_xact_id(),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 200),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    UNIQUE (audio_lineage_id,source_observation_id,machine_prediction_id,ordinal_policy_version)
);

CREATE TABLE IF NOT EXISTS public.exercise_n1_version_compatibility_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    exercise_version_id UUID NOT NULL UNIQUE REFERENCES public.exercise_versions(id),
    supported_confidence_patterns TEXT[] NOT NULL CHECK (
        cardinality(supported_confidence_patterns)>0
        AND supported_confidence_patterns <@ ARRAY[
            'low_confidence_rushing_dominant','near_confident','confident'
        ]::text[]
    ),
    supported_ratio_min NUMERIC NOT NULL,
    supported_ratio_max NUMERIC NOT NULL,
    preferred_ratio_min NUMERIC NOT NULL,
    preferred_ratio_max NUMERIC NOT NULL,
    editorial_priority INTEGER NOT NULL CHECK (editorial_priority BETWEEN 0 AND 100),
    publisher_approval_ref TEXT NOT NULL CHECK (length(btrim(publisher_approval_ref))>0),
    publisher_evidence_sha256 TEXT NOT NULL CHECK (publisher_evidence_sha256 ~ '^[0-9a-f]{64}$'),
    profile_sha256 TEXT NOT NULL CHECK (profile_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    recorded_xid XID8 NOT NULL DEFAULT pg_current_xact_id(),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 200),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    CHECK (supported_ratio_max>=supported_ratio_min),
    CHECK (preferred_ratio_min>=supported_ratio_min),
    CHECK (preferred_ratio_max>=preferred_ratio_min),
    CHECK (preferred_ratio_max<=supported_ratio_max)
);

-- PostgreSQL NUMERIC admits NaN and infinities. Ordinary ordering checks alone do
-- not form a finite measurement contract, so keep a separately named constraint
-- that is also installed when assigned migration 0317 is reapplied.
ALTER TABLE public.exercise_n1_version_compatibility_profiles
    DROP CONSTRAINT IF EXISTS exercise_n1_version_profiles_finite_ranges;
ALTER TABLE public.exercise_n1_version_compatibility_profiles
    ADD CONSTRAINT exercise_n1_version_profiles_finite_ranges CHECK (
        supported_ratio_min > 0 AND supported_ratio_min < 'Infinity'::numeric
        AND supported_ratio_max > 0 AND supported_ratio_max < 'Infinity'::numeric
        AND preferred_ratio_min > 0 AND preferred_ratio_min < 'Infinity'::numeric
        AND preferred_ratio_max > 0 AND preferred_ratio_max < 'Infinity'::numeric
    );

CREATE TABLE IF NOT EXISTS public.exercise_n1_pattern_snapshots (
    candidate_set_id UUID PRIMARY KEY REFERENCES public.exercise_candidate_sets(id),
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    source_pattern_result_id UUID NOT NULL REFERENCES public.exercise_n1_source_pattern_results(id),
    ordinal_policy_version TEXT NOT NULL
        CHECK (ordinal_policy_version='confidence-pattern-distance-v1'),
    inventory JSONB NOT NULL CHECK (jsonb_typeof(inventory)='array'),
    candidate_count INTEGER NOT NULL CHECK (candidate_count>=0),
    inventory_sha256 TEXT NOT NULL CHECK (inventory_sha256 ~ '^[0-9a-f]{64}$'),
    snapshot_sha256 TEXT NOT NULL CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    frozen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 200),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible)
);

CREATE TABLE IF NOT EXISTS public.exercise_n1_pattern_candidates (
    candidate_set_id UUID NOT NULL,
    acquisition_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
    exercise_version_id UUID NOT NULL REFERENCES public.exercise_versions(id),
    compatibility_profile_id UUID NULL REFERENCES public.exercise_n1_version_compatibility_profiles(id),
    source_pattern TEXT NOT NULL CHECK (source_pattern IN (
        'low_confidence_rushing_dominant','near_confident','confident'
    )),
    supported_confidence_patterns TEXT[] NOT NULL,
    pattern_distance INTEGER NULL CHECK (pattern_distance BETWEEN 0 AND 2),
    compatibility_state TEXT NOT NULL CHECK (compatibility_state IN ('rankable','excluded')),
    exclusion_reason TEXT NULL CHECK (exclusion_reason IN (
        'base_candidate_excluded','confidence_compatibility_unresolvable','profile_not_available_asof'
    )),
    candidate_sha256 TEXT NOT NULL CHECK (candidate_sha256 ~ '^[0-9a-f]{64}$'),
    serves_user BOOLEAN NOT NULL DEFAULT false CHECK (NOT serves_user),
    dataset_eligible BOOLEAN NOT NULL DEFAULT false CHECK (NOT dataset_eligible),
    PRIMARY KEY (candidate_set_id,exercise_version_id),
    CHECK ((compatibility_state='rankable' AND pattern_distance IS NOT NULL
            AND exclusion_reason IS NULL AND cardinality(supported_confidence_patterns)>0)
        OR (compatibility_state='excluded' AND pattern_distance IS NULL
            AND exclusion_reason IS NOT NULL))
);

-- Acquisition ownership is part of relational identity, not caller-provided
-- metadata.  The composite keys prevent a valid child identifier from being
-- paired with a different principal at any level of the frozen inventory.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='public.exercise_candidate_sets'::regclass
          AND conname='exercise_candidate_sets_id_principal_key'
    ) THEN
        ALTER TABLE public.exercise_candidate_sets
            ADD CONSTRAINT exercise_candidate_sets_id_principal_key
            UNIQUE (id,acquisition_principal_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='public.exercise_n1_source_pattern_results'::regclass
          AND conname='exercise_n1_source_results_id_principal_key'
    ) THEN
        ALTER TABLE public.exercise_n1_source_pattern_results
            ADD CONSTRAINT exercise_n1_source_results_id_principal_key
            UNIQUE (id,acquisition_principal_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='public.exercise_n1_pattern_snapshots'::regclass
          AND conname='exercise_n1_snapshots_set_principal_key'
    ) THEN
        ALTER TABLE public.exercise_n1_pattern_snapshots
            ADD CONSTRAINT exercise_n1_snapshots_set_principal_key
            UNIQUE (candidate_set_id,acquisition_principal_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='public.exercise_n1_pattern_snapshots'::regclass
          AND conname='exercise_n1_snapshots_set_principal_fk'
    ) THEN
        ALTER TABLE public.exercise_n1_pattern_snapshots
            ADD CONSTRAINT exercise_n1_snapshots_set_principal_fk
            FOREIGN KEY (candidate_set_id,acquisition_principal_id)
            REFERENCES public.exercise_candidate_sets(id,acquisition_principal_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='public.exercise_n1_pattern_snapshots'::regclass
          AND conname='exercise_n1_snapshots_source_principal_fk'
    ) THEN
        ALTER TABLE public.exercise_n1_pattern_snapshots
            ADD CONSTRAINT exercise_n1_snapshots_source_principal_fk
            FOREIGN KEY (source_pattern_result_id,acquisition_principal_id)
            REFERENCES public.exercise_n1_source_pattern_results(id,acquisition_principal_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid='public.exercise_n1_pattern_candidates'::regclass
          AND conname='exercise_n1_candidates_snapshot_principal_fk'
    ) THEN
        ALTER TABLE public.exercise_n1_pattern_candidates
            ADD CONSTRAINT exercise_n1_candidates_snapshot_principal_fk
            FOREIGN KEY (candidate_set_id,acquisition_principal_id)
            REFERENCES public.exercise_n1_pattern_snapshots(
                candidate_set_id,acquisition_principal_id
            );
    END IF;
END $$;

CREATE OR REPLACE FUNCTION public.exercise_confidence_pattern_ordinal_v1(p_pattern TEXT)
RETURNS INTEGER LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path=public AS $$
SELECT CASE p_pattern
    WHEN 'low_confidence_rushing_dominant' THEN 0
    WHEN 'near_confident' THEN 1
    WHEN 'confident' THEN 2
    ELSE NULL
END $$;

CREATE OR REPLACE FUNCTION public.exercise_confidence_pattern_distance_v1(
    p_source TEXT,p_supported TEXT[]
) RETURNS INTEGER LANGUAGE sql IMMUTABLE PARALLEL SAFE SET search_path=public AS $$
SELECT min(abs(public.exercise_confidence_pattern_ordinal_v1(p_source)-
               public.exercise_confidence_pattern_ordinal_v1(pattern)))
FROM unnest(COALESCE(p_supported,'{}'::text[])) pattern
WHERE public.exercise_confidence_pattern_ordinal_v1(p_source) IS NOT NULL
  AND public.exercise_confidence_pattern_ordinal_v1(pattern) IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION public.register_exercise_n1_source_pattern_v1(
    p_audio_lineage_id UUID,p_source_observation_id UUID,
    p_authorization_check_id UUID,p_idempotency_key TEXT
) RETURNS public.exercise_n1_source_pattern_results
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE l public.exercise_audio_lineages; o public.learning_profile_observations;
    p public.ml_machine_predictions; r RECORD; existing public.exercise_n1_source_pattern_results;
    pattern TEXT; output_hash TEXT; result_hash TEXT; completed TIMESTAMPTZ;
BEGIN
    IF COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'N1_SOURCE_PATTERN_KEY_REQUIRED'; END IF;
    SELECT * INTO STRICT l FROM public.exercise_audio_lineages WHERE id=p_audio_lineage_id;
    PERFORM public.require_exercise_assignment_authority_v1(p_authorization_check_id,l.acquisition_principal_id);
    SELECT * INTO STRICT o FROM public.learning_profile_observations WHERE id=p_source_observation_id;
    SELECT * INTO STRICT p FROM public.ml_machine_predictions WHERE id=o.prediction_id;
    SELECT mr.learning_surface_id,mr.status,mr.completed_at,mr.code_version,
           cr.detector_version,cr.feature_schema_version,cr.feature_extractor_version
      INTO STRICT r
      FROM public.ml_classification_runs cr JOIN public.ml_model_runs mr ON mr.id=cr.model_run_id
     WHERE cr.model_run_id=p.classification_run_id;
    pattern:=p.raw_output->>'source_pattern';
    completed:=r.completed_at;
    IF o.audio_lineage_id<>l.id OR o.prediction_id<>p.id
       OR o.acquisition_principal_id<>l.acquisition_principal_id OR o.speaker_id<>l.speaker_id
       OR r.learning_surface_id<>'confidence_classification' OR r.status<>'succeeded'
       OR completed IS NULL OR completed>clock_timestamp()
       OR public.exercise_confidence_pattern_ordinal_v1(pattern) IS NULL
       OR NOT public.exercise_evidence_matches_audio_v1(p.evidence_span_id,l.id)
    THEN RAISE EXCEPTION 'N1_SOURCE_PATTERN_PROVENANCE_INVALID'; END IF;
    output_hash:=public.exercise_json_sha256_v1(jsonb_build_object(
        'prediction_id',p.id,'evidence_span_id',p.evidence_span_id,'raw_output',p.raw_output,
        'output_schema_version',p.output_schema_version,'classification_run_id',p.classification_run_id));
    result_hash:=public.exercise_json_sha256_v1(jsonb_build_object(
        'acquisition_principal_id',l.acquisition_principal_id,
        'audio_lineage_id',l.id,'source_observation_id',o.id,'machine_prediction_id',p.id,
        'source_pattern',pattern,'result_origin','machine',
        'source_pattern_policy_version','confidence-pattern-source-v1',
        'ordinal_policy_version','confidence-pattern-distance-v1',
        'prediction_output_sha256',output_hash,'completed_at',completed,
        'detector_version',r.detector_version,'feature_schema_version',r.feature_schema_version,
        'feature_extractor_version',r.feature_extractor_version,'code_version',r.code_version));
    PERFORM pg_advisory_xact_lock(hashtextextended('n1-source-pattern:'||p_idempotency_key,0));
    PERFORM public.require_exercise_assignment_authority_v1(p_authorization_check_id,l.acquisition_principal_id);
    IF NOT public.exercise_evidence_matches_audio_v1(p.evidence_span_id,l.id)
    THEN RAISE EXCEPTION 'N1_SOURCE_PATTERN_PROVENANCE_INVALID'; END IF;
    SELECT * INTO existing FROM public.exercise_n1_source_pattern_results WHERE idempotency_key=p_idempotency_key;
    IF existing.id IS NULL THEN
        SELECT * INTO existing FROM public.exercise_n1_source_pattern_results
         WHERE audio_lineage_id=l.id AND source_observation_id=o.id
           AND machine_prediction_id=p.id AND ordinal_policy_version='confidence-pattern-distance-v1';
    END IF;
    IF existing.id IS NOT NULL THEN
        IF existing.result_sha256<>result_hash THEN RAISE EXCEPTION 'N1_SOURCE_PATTERN_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_n1_source_pattern_results(
        acquisition_principal_id,audio_lineage_id,source_observation_id,machine_prediction_id,
        source_pattern,result_origin,source_pattern_policy_version,ordinal_policy_version,
        prediction_output_sha256,result_sha256,completed_at,idempotency_key)
    VALUES(l.acquisition_principal_id,l.id,o.id,p.id,pattern,'machine','confidence-pattern-source-v1',
        'confidence-pattern-distance-v1',output_hash,result_hash,completed,p_idempotency_key)
    RETURNING * INTO existing;
    RETURN existing;
END; $$;

CREATE OR REPLACE FUNCTION public.register_exercise_n1_version_profile_v1(
    p_exercise_version_id UUID,p_supported_patterns TEXT[],
    p_supported_min NUMERIC,p_supported_max NUMERIC,
    p_preferred_min NUMERIC,p_preferred_max NUMERIC,p_editorial_priority INTEGER,
    p_approval_ref TEXT,p_approval_sha256 TEXT,p_idempotency_key TEXT
) RETURNS public.exercise_n1_version_compatibility_profiles
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE v public.exercise_versions; normalized TEXT[]; h TEXT;
    existing public.exercise_n1_version_compatibility_profiles;
BEGIN
    SELECT array_agg(DISTINCT x ORDER BY x) INTO normalized FROM unnest(COALESCE(p_supported_patterns,'{}')) x
     WHERE public.exercise_confidence_pattern_ordinal_v1(x) IS NOT NULL;
    SELECT * INTO STRICT v FROM public.exercise_versions WHERE id=p_exercise_version_id;
    IF v.catalogue_state<>'active' OR v.safety_state<>'approved'
       OR cardinality(normalized)=0 OR cardinality(normalized)<>cardinality(p_supported_patterns)
       OR NOT COALESCE(
           p_supported_min>0 AND p_supported_min<'Infinity'::numeric
           AND p_supported_max>0 AND p_supported_max<'Infinity'::numeric
           AND p_preferred_min>0 AND p_preferred_min<'Infinity'::numeric
           AND p_preferred_max>0 AND p_preferred_max<'Infinity'::numeric
           AND p_supported_max>=p_supported_min
           AND p_preferred_min>=p_supported_min
           AND p_preferred_max>=p_preferred_min
           AND p_preferred_max<=p_supported_max,
           false
       ) OR p_editorial_priority NOT BETWEEN 0 AND 100
       OR COALESCE(btrim(p_approval_ref),'')='' OR p_approval_sha256 !~ '^[0-9a-f]{64}$'
       OR COALESCE(btrim(p_idempotency_key),'')=''
    THEN RAISE EXCEPTION 'N1_VERSION_PROFILE_INVALID'; END IF;
    h:=public.exercise_json_sha256_v1(jsonb_build_object('exercise_version_id',v.id,
        'version_sha256',v.version_sha256,'supported_confidence_patterns',to_jsonb(normalized),
        'supported_ratio_min',p_supported_min,'supported_ratio_max',p_supported_max,
        'preferred_ratio_min',p_preferred_min,'preferred_ratio_max',p_preferred_max,
        'editorial_priority',p_editorial_priority,'publisher_approval_ref',p_approval_ref,
        'publisher_evidence_sha256',p_approval_sha256));
    PERFORM pg_advisory_xact_lock(hashtextextended('n1-version-profile:'||p_idempotency_key,0));
    SELECT * INTO existing FROM public.exercise_n1_version_compatibility_profiles WHERE idempotency_key=p_idempotency_key;
    IF existing.id IS NULL THEN SELECT * INTO existing FROM public.exercise_n1_version_compatibility_profiles
        WHERE exercise_version_id=v.id; END IF;
    IF existing.id IS NOT NULL THEN
        IF existing.profile_sha256<>h THEN RAISE EXCEPTION 'N1_VERSION_PROFILE_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_n1_version_compatibility_profiles(
        exercise_version_id,supported_confidence_patterns,supported_ratio_min,supported_ratio_max,
        preferred_ratio_min,preferred_ratio_max,editorial_priority,publisher_approval_ref,
        publisher_evidence_sha256,profile_sha256,idempotency_key)
    VALUES(v.id,normalized,p_supported_min,p_supported_max,p_preferred_min,p_preferred_max,
        p_editorial_priority,p_approval_ref,p_approval_sha256,h,p_idempotency_key)
    RETURNING * INTO existing;
    RETURN existing;
END; $$;

CREATE OR REPLACE FUNCTION public.freeze_exercise_n1_pattern_snapshot_v1(
    p_candidate_set_id UUID,p_source_pattern_result_id UUID,p_idempotency_key TEXT
) RETURNS public.exercise_n1_pattern_snapshots
LANGUAGE plpgsql SECURITY DEFINER SET search_path=public AS $$
DECLARE f public.exercise_candidate_sets; s public.exercise_selection_feature_snapshots;
    source public.exercise_n1_source_pattern_results; existing public.exercise_n1_pattern_snapshots;
    visibility PG_SNAPSHOT:=pg_current_snapshot(); item RECORD; profile public.exercise_n1_version_compatibility_profiles;
    distance INTEGER; state TEXT; reason TEXT; entry JSONB; inventory JSONB:='[]';
    h TEXT; snapshot_hash TEXT;
BEGIN
    IF COALESCE(btrim(p_idempotency_key),'')='' THEN RAISE EXCEPTION 'N1_PATTERN_SNAPSHOT_KEY_REQUIRED'; END IF;
    SELECT * INTO STRICT f FROM public.exercise_candidate_sets WHERE id=p_candidate_set_id;
    SELECT * INTO STRICT s FROM public.exercise_selection_feature_snapshots WHERE id=f.feature_snapshot_id;
    SELECT * INTO STRICT source FROM public.exercise_n1_source_pattern_results WHERE id=p_source_pattern_result_id;
    PERFORM public.require_exercise_assignment_authority_v1(f.authorization_check_id,f.acquisition_principal_id);
    IF source.acquisition_principal_id<>f.acquisition_principal_id
       OR source.audio_lineage_id<>f.audio_lineage_id OR source.source_observation_id<>s.source_observation_id
       OR source.ordinal_policy_version<>'confidence-pattern-distance-v1'
       OR source.recorded_xid=pg_current_xact_id() OR NOT pg_visible_in_snapshot(source.recorded_xid,visibility)
       OR source.completed_at>f.assigned_at OR source.serves_user OR source.dataset_eligible
    THEN RAISE EXCEPTION 'N1_PATTERN_SOURCE_NOT_FROZEN_ASOF'; END IF;
    -- Serialize on the natural snapshot identity, not the caller's retry key.
    -- Different keys for the same candidate set must converge; the same key for
    -- a different candidate set must fail instead of returning the wrong frame.
    PERFORM pg_advisory_xact_lock(hashtextextended('n1-pattern-snapshot:'||f.id::text,0));
    -- The natural-identity lock cannot serialize two *different* candidate sets
    -- that reuse one retry key. Lock that key second, in a consistent order, so
    -- the loser observes the committed winner and returns the typed conflict.
    PERFORM pg_advisory_xact_lock(
        hashtextextended('n1-pattern-snapshot-idem:'||p_idempotency_key,0)
    );
    PERFORM public.require_exercise_assignment_authority_v1(f.authorization_check_id,f.acquisition_principal_id);
    FOR item IN SELECT c.* FROM public.exercise_candidates c WHERE c.candidate_set_id=f.id
        ORDER BY c.exercise_version_id LOOP
        SELECT * INTO profile FROM public.exercise_n1_version_compatibility_profiles p
         WHERE p.exercise_version_id=item.exercise_version_id AND p.created_at<=f.assigned_at
           AND p.recorded_xid<>pg_current_xact_id() AND pg_visible_in_snapshot(p.recorded_xid,visibility);
        distance:=NULL; reason:=NULL;
        IF item.eligibility<>'eligible' THEN state:='excluded'; reason:='base_candidate_excluded';
        ELSIF profile.id IS NULL THEN state:='excluded'; reason:='profile_not_available_asof';
        ELSE
            distance:=public.exercise_confidence_pattern_distance_v1(source.source_pattern,profile.supported_confidence_patterns);
            IF distance IS NULL THEN state:='excluded'; reason:='confidence_compatibility_unresolvable';
            ELSE state:='rankable'; END IF;
        END IF;
        entry:=jsonb_build_object('exercise_version_id',item.exercise_version_id,
            'acquisition_principal_id',f.acquisition_principal_id,
            'source_pattern_result_id',source.id,'source_pattern',source.source_pattern,
            'ordinal_policy_version',source.ordinal_policy_version,
            'compatibility_profile_id',profile.id,
            'supported_confidence_patterns',COALESCE(to_jsonb(profile.supported_confidence_patterns),'[]'::jsonb),
            'pattern_distance',distance,'compatibility_state',state,'exclusion_reason',reason,
            'base_candidate_sha256',item.candidate_sha256,'profile_sha256',profile.profile_sha256);
        inventory:=inventory||jsonb_build_array(entry);
    END LOOP;
    IF jsonb_array_length(inventory)<>f.candidate_count THEN RAISE EXCEPTION 'N1_PATTERN_INVENTORY_INCOMPLETE'; END IF;
    h:=public.exercise_json_sha256_v1(inventory);
    snapshot_hash:=public.exercise_json_sha256_v1(jsonb_build_array(
        f.id,f.acquisition_principal_id,source.result_sha256,
        'confidence-pattern-distance-v1',h));
    SELECT * INTO existing FROM public.exercise_n1_pattern_snapshots
     WHERE idempotency_key=p_idempotency_key;
    IF existing.candidate_set_id IS NOT NULL AND existing.candidate_set_id<>f.id THEN
        RAISE EXCEPTION 'N1_PATTERN_SNAPSHOT_REPLAY_CONFLICT';
    END IF;
    IF existing.candidate_set_id IS NULL THEN
        SELECT * INTO existing FROM public.exercise_n1_pattern_snapshots WHERE candidate_set_id=f.id;
    END IF;
    IF existing.candidate_set_id IS NOT NULL THEN
        IF existing.acquisition_principal_id<>f.acquisition_principal_id
           OR existing.source_pattern_result_id<>source.id
           OR existing.ordinal_policy_version<>'confidence-pattern-distance-v1'
           OR existing.inventory IS DISTINCT FROM inventory
           OR existing.candidate_count<>f.candidate_count
           OR existing.inventory_sha256<>h OR existing.snapshot_sha256<>snapshot_hash
           OR existing.serves_user OR existing.dataset_eligible
           OR (SELECT count(*) FROM public.exercise_n1_pattern_candidates c
                WHERE c.candidate_set_id=f.id)<>f.candidate_count
        THEN RAISE EXCEPTION 'N1_PATTERN_SNAPSHOT_REPLAY_CONFLICT'; END IF;
        RETURN existing;
    END IF;
    INSERT INTO public.exercise_n1_pattern_snapshots(candidate_set_id,acquisition_principal_id,
        source_pattern_result_id,ordinal_policy_version,inventory,candidate_count,inventory_sha256,
        snapshot_sha256,idempotency_key)
    VALUES(f.id,f.acquisition_principal_id,source.id,'confidence-pattern-distance-v1',inventory,
        f.candidate_count,h,snapshot_hash,p_idempotency_key) RETURNING * INTO existing;
    FOR entry IN SELECT value FROM jsonb_array_elements(inventory) LOOP
        INSERT INTO public.exercise_n1_pattern_candidates(candidate_set_id,acquisition_principal_id,exercise_version_id,
            compatibility_profile_id,source_pattern,supported_confidence_patterns,pattern_distance,
            compatibility_state,exclusion_reason,candidate_sha256)
        VALUES(f.id,f.acquisition_principal_id,(entry->>'exercise_version_id')::uuid,(entry->>'compatibility_profile_id')::uuid,
            entry->>'source_pattern',ARRAY(SELECT jsonb_array_elements_text(entry->'supported_confidence_patterns')),
            (entry->>'pattern_distance')::integer,entry->>'compatibility_state',entry->>'exclusion_reason',
            public.exercise_json_sha256_v1(entry));
    END LOOP;
    PERFORM public.require_exercise_assignment_authority_v1(f.authorization_check_id,f.acquisition_principal_id);
    RETURN existing;
END; $$;

ALTER TABLE public.exercise_n1_source_pattern_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_n1_version_compatibility_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_n1_pattern_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.exercise_n1_pattern_candidates ENABLE ROW LEVEL SECURITY;
DO $$ DECLARE n TEXT; BEGIN
    FOREACH n IN ARRAY ARRAY['exercise_n1_source_pattern_results','exercise_n1_version_compatibility_profiles',
        'exercise_n1_pattern_snapshots','exercise_n1_pattern_candidates'] LOOP
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC,anon,authenticated,service_role',n);
        EXECUTE format('GRANT SELECT ON public.%I TO service_role',n);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON public.%I',n||'_append_only',n);
        EXECUTE format('CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I FOR EACH ROW EXECUTE FUNCTION public.reject_mlc2_immutable_mutation()',n||'_append_only',n);
    END LOOP;
END $$;
REVOKE ALL ON FUNCTION public.exercise_confidence_pattern_ordinal_v1(TEXT) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.exercise_confidence_pattern_distance_v1(TEXT,TEXT[]) FROM PUBLIC,anon,authenticated,service_role;
REVOKE ALL ON FUNCTION public.register_exercise_n1_source_pattern_v1(UUID,UUID,UUID,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.register_exercise_n1_source_pattern_v1(UUID,UUID,UUID,TEXT) TO service_role;
REVOKE ALL ON FUNCTION public.register_exercise_n1_version_profile_v1(UUID,TEXT[],NUMERIC,NUMERIC,NUMERIC,NUMERIC,INTEGER,TEXT,TEXT,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.register_exercise_n1_version_profile_v1(UUID,TEXT[],NUMERIC,NUMERIC,NUMERIC,NUMERIC,INTEGER,TEXT,TEXT,TEXT) TO service_role;
REVOKE ALL ON FUNCTION public.freeze_exercise_n1_pattern_snapshot_v1(UUID,UUID,TEXT) FROM PUBLIC,anon,authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_exercise_n1_pattern_snapshot_v1(UUID,UUID,TEXT) TO service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
