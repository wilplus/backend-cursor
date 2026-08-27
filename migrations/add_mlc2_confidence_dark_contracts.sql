-- 0303 · MLC-2 confidence-classification dark runtime contracts.
--
-- Additive and inert.  No product producer imports or invokes these objects in
-- Slice 3.  The only writer is the reviewed, service-role-only atomic
-- finalizer below.  Dataset creation, training, promotion and legacy cutover
-- remain outside this migration.

CREATE TABLE IF NOT EXISTS public.ml_model_runs (
    id                       UUID PRIMARY KEY,
    canonical_event_id       UUID NOT NULL
        REFERENCES public.ml_canonical_events(id) ON DELETE RESTRICT,
    learning_surface_id      TEXT NOT NULL
        REFERENCES public.ml_learning_surfaces(id) ON DELETE RESTRICT,
    pipeline_stage_id        TEXT NOT NULL
        REFERENCES public.ml_pipeline_stages(id) ON DELETE RESTRICT,
    run_kind                 TEXT NOT NULL CHECK (run_kind IN (
        'classification', 'deterministic_policy'
    )),
    provider                 TEXT NOT NULL CHECK (length(btrim(provider)) > 0),
    model_id                 TEXT NOT NULL CHECK (length(btrim(model_id)) > 0),
    adapter_id               TEXT NULL,
    assignment_origin        TEXT NOT NULL CHECK (assignment_origin IN (
        'foundation', 'trained', 'deterministic_policy'
    )),
    assignment_version       TEXT NOT NULL
        CHECK (length(btrim(assignment_version)) > 0),
    code_version             TEXT NOT NULL CHECK (length(btrim(code_version)) > 0),
    configuration            JSONB NOT NULL CHECK (
        jsonb_typeof(configuration) = 'object'
    ),
    request_sha256           TEXT NOT NULL CHECK (length(request_sha256) = 64),
    status                   TEXT NOT NULL CHECK (status IN (
        'succeeded', 'failed', 'cancelled'
    )),
    started_at               TIMESTAMPTZ NOT NULL,
    completed_at             TIMESTAMPTZ NOT NULL,
    idempotency_key          TEXT NOT NULL UNIQUE,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_model_run_time_check CHECK (completed_at >= started_at),
    CONSTRAINT ml_model_run_confidence_shape_check CHECK (
        learning_surface_id = 'confidence_classification'
        AND (
            (run_kind = 'classification'
             AND pipeline_stage_id = 'classify'
             AND assignment_origin IN ('foundation', 'trained'))
            OR
            (run_kind = 'deterministic_policy'
             AND pipeline_stage_id = 'select'
             AND assignment_origin = 'deterministic_policy'
             AND provider = 'deterministic_policy')
        )
    )
);

CREATE INDEX IF NOT EXISTS ml_model_runs_event_idx
    ON public.ml_model_runs (canonical_event_id, run_kind);
CREATE INDEX IF NOT EXISTS ml_model_runs_provider_model_idx
    ON public.ml_model_runs (provider, model_id, completed_at DESC);

CREATE TABLE IF NOT EXISTS public.ml_classification_runs (
    model_run_id               UUID PRIMARY KEY
        REFERENCES public.ml_model_runs(id) ON DELETE RESTRICT,
    feature_schema_version     TEXT NOT NULL
        CHECK (length(btrim(feature_schema_version)) > 0),
    feature_extractor_version  TEXT NOT NULL
        CHECK (length(btrim(feature_extractor_version)) > 0),
    detector_version           TEXT NOT NULL
        CHECK (length(btrim(detector_version)) > 0),
    threshold_version          TEXT NOT NULL
        CHECK (length(btrim(threshold_version)) > 0),
    taxonomy_version           TEXT NOT NULL
        CHECK (length(btrim(taxonomy_version)) > 0),
    threshold_snapshot         JSONB NOT NULL CHECK (
        jsonb_typeof(threshold_snapshot) = 'object'
    ),
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ml_machine_predictions (
    id                       UUID PRIMARY KEY,
    classification_run_id    UUID NOT NULL
        REFERENCES public.ml_classification_runs(model_run_id)
        ON DELETE RESTRICT,
    evidence_span_id         UUID NOT NULL
        REFERENCES public.ml_evidence_spans(id) ON DELETE RESTRICT,
    prediction_kind          TEXT NOT NULL CHECK (
        prediction_kind = 'confidence_classification'
    ),
    predicted_value          TEXT NOT NULL
        CHECK (length(btrim(predicted_value)) > 0),
    confidence_score         NUMERIC NOT NULL CHECK (
        confidence_score >= 0 AND confidence_score <= 1
    ),
    probability_distribution JSONB NOT NULL CHECK (
        jsonb_typeof(probability_distribution) = 'object'
    ),
    raw_output               JSONB NOT NULL CHECK (jsonb_typeof(raw_output) = 'object'),
    output_schema_version    TEXT NOT NULL
        CHECK (length(btrim(output_schema_version)) > 0),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (classification_run_id, evidence_span_id)
);

CREATE INDEX IF NOT EXISTS ml_machine_predictions_evidence_idx
    ON public.ml_machine_predictions (evidence_span_id, created_at);

CREATE TABLE IF NOT EXISTS public.ml_selection_runs (
    model_run_id               UUID PRIMARY KEY
        REFERENCES public.ml_model_runs(id) ON DELETE RESTRICT,
    classification_run_id      UUID NOT NULL
        REFERENCES public.ml_classification_runs(model_run_id)
        ON DELETE RESTRICT,
    execution_kind             TEXT NOT NULL CHECK (
        execution_kind = 'deterministic_policy'
    ),
    selection_policy_version   TEXT NOT NULL
        CHECK (length(btrim(selection_policy_version)) > 0),
    eligibility_policy_version TEXT NOT NULL
        CHECK (length(btrim(eligibility_policy_version)) > 0),
    threshold_version          TEXT NOT NULL
        CHECK (length(btrim(threshold_version)) > 0),
    exploration_probability    NUMERIC NOT NULL CHECK (
        exploration_probability = 0.20
    ),
    rng_algorithm              TEXT NOT NULL
        CHECK (length(btrim(rng_algorithm)) > 0),
    rng_seed                   TEXT NOT NULL CHECK (length(btrim(rng_seed)) > 0),
    rng_draws                  JSONB NOT NULL CHECK (jsonb_typeof(rng_draws) = 'array'),
    created_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (model_run_id, classification_run_id)
);

CREATE TABLE IF NOT EXISTS public.ml_candidate_sets (
    id                       UUID PRIMARY KEY,
    canonical_event_id       UUID NOT NULL UNIQUE
        REFERENCES public.ml_canonical_events(id) ON DELETE RESTRICT,
    selection_run_id         UUID NOT NULL UNIQUE
        REFERENCES public.ml_selection_runs(model_run_id)
        ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    speaker_id               UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    project_id               UUID NOT NULL
        REFERENCES public.projects(id) ON DELETE RESTRICT,
    recording_attempt_id     UUID NOT NULL
        REFERENCES public.recording_attempts(id) ON DELETE RESTRICT,
    take_id                  UUID NOT NULL
        REFERENCES public.takes(id) ON DELETE RESTRICT,
    candidate_set_version    TEXT NOT NULL
        CHECK (length(btrim(candidate_set_version)) > 0),
    pool_size                INTEGER NOT NULL CHECK (pool_size > 0),
    eligible_count           INTEGER NOT NULL CHECK (eligible_count >= 0),
    excluded_count           INTEGER NOT NULL CHECK (excluded_count >= 0),
    selected_count           INTEGER NOT NULL CHECK (selected_count > 0),
    frame_manifest           JSONB NOT NULL CHECK (
        jsonb_typeof(frame_manifest) = 'object'
    ),
    immutable_pool_sha256    TEXT NOT NULL
        CHECK (length(immutable_pool_sha256) = 64),
    finalized_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_candidate_set_counts_check CHECK (
        eligible_count + excluded_count = pool_size
        AND selected_count <= eligible_count
    )
);

CREATE INDEX IF NOT EXISTS ml_candidate_sets_take_idx
    ON public.ml_candidate_sets (take_id, finalized_at DESC);
CREATE INDEX IF NOT EXISTS ml_candidate_sets_speaker_idx
    ON public.ml_candidate_sets (speaker_id, finalized_at DESC);

CREATE TABLE IF NOT EXISTS public.ml_candidates (
    id                       UUID PRIMARY KEY,
    candidate_set_id         UUID NOT NULL
        REFERENCES public.ml_candidate_sets(id) ON DELETE RESTRICT,
    candidate_key            TEXT NOT NULL CHECK (length(btrim(candidate_key)) > 0),
    clip_id                  UUID NOT NULL,
    evidence_span_id         UUID NOT NULL
        REFERENCES public.ml_evidence_spans(id) ON DELETE RESTRICT,
    machine_prediction_id    UUID NULL
        REFERENCES public.ml_machine_predictions(id) ON DELETE RESTRICT,
    eligible                 BOOLEAN NOT NULL,
    exclusion_reason_code    TEXT NULL,
    score                    NUMERIC NULL CHECK (
        score IS NULL OR (score >= 0 AND score <= 1)
    ),
    rank                     INTEGER NULL CHECK (rank IS NULL OR rank > 0),
    selected                 BOOLEAN NOT NULL,
    selection_mode           TEXT NOT NULL CHECK (selection_mode IN (
        'deterministic', 'exploration', 'not_selected', 'excluded'
    )),
    selection_reason_code    TEXT NOT NULL
        CHECK (length(btrim(selection_reason_code)) > 0),
    sampling_probability     NUMERIC NOT NULL CHECK (
        sampling_probability >= 0 AND sampling_probability <= 1
    ),
    rng_draw_index           INTEGER NULL CHECK (
        rng_draw_index IS NULL OR rng_draw_index >= 0
    ),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (candidate_set_id, candidate_key),
    UNIQUE (candidate_set_id, evidence_span_id),
    CONSTRAINT ml_candidate_eligibility_check CHECK (
        (eligible AND exclusion_reason_code IS NULL
         AND machine_prediction_id IS NOT NULL
         AND score IS NOT NULL AND rank IS NOT NULL)
        OR
        (NOT eligible AND exclusion_reason_code IS NOT NULL
         AND length(btrim(exclusion_reason_code)) > 0
         AND NOT selected AND rank IS NULL
         AND selection_mode = 'excluded'
         AND sampling_probability = 0)
    ),
    CONSTRAINT ml_candidate_selection_check CHECK (
        (selected AND eligible
         AND selection_mode IN ('deterministic', 'exploration'))
        OR
        (NOT selected AND eligible AND selection_mode = 'not_selected')
        OR
        (NOT selected AND NOT eligible AND selection_mode = 'excluded')
    ),
    CONSTRAINT ml_candidate_rng_check CHECK (
        (selection_mode = 'exploration' AND rng_draw_index IS NOT NULL)
        OR selection_mode <> 'exploration'
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS ml_candidates_rank_idx
    ON public.ml_candidates (candidate_set_id, rank)
    WHERE eligible;
CREATE INDEX IF NOT EXISTS ml_candidates_clip_idx
    ON public.ml_candidates (clip_id, created_at);

-- Finalize the event, R2 metadata, exact evidence, classifier output and the
-- complete selection frame in one transaction.  A failed insert rolls back the
-- generic outbox finalization too.  Replays return the existing frame only when
-- the immutable manifest is identical.
CREATE OR REPLACE FUNCTION public.finalize_mlc2_confidence_frame_v1(
    p_outbox_event_id UUID,
    p_worker_id TEXT,
    p_canonical_event JSONB,
    p_confidence_frame JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    outbox_event       public.ml_outbox_events;
    canonical_event    public.ml_canonical_events;
    existing_set       public.ml_candidate_sets;
    v_candidate_set_id UUID;
    classification_id  UUID;
    selection_id       UUID;
    candidate          JSONB;
    evidence           JSONB;
    object_metadata    JSONB;
    object_row          public.ml_object_artifacts;
    evidence_row        public.ml_evidence_spans;
    prediction_row      public.ml_machine_predictions;
    frame_manifest      JSONB;
    pool_sha256         TEXT;
    pool_size           INTEGER;
    eligible_count      INTEGER;
    excluded_count      INTEGER;
    selected_count      INTEGER;
BEGIN
    IF jsonb_typeof(p_confidence_frame) <> 'object'
       OR jsonb_typeof(p_confidence_frame #> '{candidate_set,candidates}')
          <> 'array' THEN
        RAISE EXCEPTION 'confidence frame requires a candidate array';
    END IF;
    IF p_canonical_event ->> 'learning_surface_id'
       IS DISTINCT FROM 'confidence_classification'
       OR p_canonical_event ->> 'pipeline_stage_id' IS DISTINCT FROM 'classify'
       OR p_canonical_event ->> 'feedback_family_id'
          IS DISTINCT FROM 'confident_voice' THEN
        RAISE EXCEPTION 'invalid confidence canonical event semantics';
    END IF;
    IF p_confidence_frame #>> '{selection_run,execution_kind}'
       IS DISTINCT FROM 'deterministic_policy'
       OR (p_confidence_frame #>> '{selection_run,exploration_probability}')::numeric
          IS DISTINCT FROM 0.20::numeric THEN
        RAISE EXCEPTION 'confidence selection requires deterministic policy with 20%% exploration';
    END IF;
    IF p_confidence_frame #>> '{selection_run,threshold_version}'
       IS DISTINCT FROM p_confidence_frame #>> '{classification_run,threshold_version}' THEN
        RAISE EXCEPTION 'classification and selection threshold versions differ';
    END IF;

    frame_manifest := p_confidence_frame - 'pool_sha256';
    pool_sha256 := encode(
        digest(convert_to(frame_manifest::text, 'UTF8'), 'sha256'), 'hex'
    );
    IF p_confidence_frame ? 'pool_sha256'
       AND p_confidence_frame ->> 'pool_sha256' IS DISTINCT FROM pool_sha256 THEN
        RAISE EXCEPTION 'submitted confidence pool hash does not verify';
    END IF;

    SELECT * INTO outbox_event FROM public.ml_outbox_events
     WHERE id = p_outbox_event_id
     FOR UPDATE;
    IF outbox_event.id IS NULL THEN
        RAISE EXCEPTION 'outbox event not found';
    END IF;
    IF outbox_event.learning_surface_id <> 'confidence_classification' THEN
        RAISE EXCEPTION 'outbox event is not confidence classification';
    END IF;
    IF outbox_event.processed_at IS NOT NULL THEN
        SELECT candidate_set.* INTO existing_set
          FROM public.ml_candidate_sets candidate_set
          JOIN public.ml_canonical_events event
            ON event.id = candidate_set.canonical_event_id
         WHERE event.source_outbox_event_id = outbox_event.id;
        IF existing_set.id IS NULL THEN
            RAISE EXCEPTION 'confidence outbox was finalized without its sampling frame';
        END IF;
        SELECT * INTO canonical_event FROM public.ml_canonical_events
         WHERE source_outbox_event_id = outbox_event.id;
        IF p_canonical_event ->> 'event_id' IS DISTINCT FROM canonical_event.event_id::text
           OR p_canonical_event ->> 'idempotency_key'
              IS DISTINCT FROM canonical_event.idempotency_key
           OR p_canonical_event ->> 'source_event_id'
              IS DISTINCT FROM canonical_event.source_event_id
           OR p_canonical_event ->> 'acquisition_principal_id'
              IS DISTINCT FROM canonical_event.acquisition_principal_id::text
           OR p_canonical_event ->> 'speaker_id'
              IS DISTINCT FROM canonical_event.speaker_id::text
           OR p_canonical_event ->> 'consent_snapshot_id'
              IS DISTINCT FROM canonical_event.consent_snapshot_id::text
           OR p_canonical_event -> 'payload' IS DISTINCT FROM canonical_event.payload
           OR p_canonical_event -> 'execution_version'
              IS DISTINCT FROM canonical_event.execution_version THEN
            RAISE EXCEPTION 'idempotent confidence replay changed canonical envelope';
        END IF;
        IF existing_set.immutable_pool_sha256 <> pool_sha256 THEN
            RAISE EXCEPTION 'idempotent confidence replay changed immutable frame';
        END IF;
        RETURN jsonb_build_object(
            'canonical_event_id', existing_set.canonical_event_id,
            'candidate_set_id', existing_set.id,
            'immutable_pool_sha256', existing_set.immutable_pool_sha256,
            'pool_size', existing_set.pool_size,
            'selected_count', existing_set.selected_count,
            'idempotent_replay', true
        );
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.ml_consent_snapshots snapshot
         WHERE snapshot.id =
               (p_canonical_event ->> 'consent_snapshot_id')::uuid
           AND snapshot.acquisition_principal_id =
               (p_canonical_event ->> 'acquisition_principal_id')::uuid
           AND snapshot.retention_state = 'eligible'
           AND snapshot.purpose_state #>>
               '{pooled_model_improvement,authorized}' = 'true'
           AND NOT EXISTS (
               SELECT 1 FROM public.ml_consent_events withdrawal
                WHERE withdrawal.event_kind = 'withdraw'
                  AND withdrawal.supersedes_event_id = snapshot.grant_event_id
           )
    ) THEN
        RAISE EXCEPTION 'confidence frame lacks current model-improvement consent';
    END IF;

    SELECT count(*)::integer,
           count(*) FILTER (WHERE (item ->> 'eligible')::boolean)::integer,
           count(*) FILTER (WHERE NOT (item ->> 'eligible')::boolean)::integer,
           count(*) FILTER (WHERE (item ->> 'selected')::boolean)::integer
      INTO pool_size, eligible_count, excluded_count, selected_count
      FROM jsonb_array_elements(
          p_confidence_frame #> '{candidate_set,candidates}'
      ) item;
    IF pool_size <= 0 OR selected_count <= 0 OR selected_count > eligible_count THEN
        RAISE EXCEPTION 'confidence frame candidate counts are invalid';
    END IF;

    SELECT * INTO canonical_event
      FROM public.finalize_mlc2_outbox_event_v1(
          p_outbox_event_id, p_worker_id, p_canonical_event
      );
    IF canonical_event.project_id IS NULL
       OR canonical_event.recording_attempt_id IS NULL
       OR canonical_event.take_id IS NULL THEN
        RAISE EXCEPTION 'confidence frame requires project, recording attempt and Take lineage';
    END IF;

    classification_id := (p_confidence_frame #>> '{classification_run,id}')::uuid;
    selection_id := (p_confidence_frame #>> '{selection_run,id}')::uuid;
    v_candidate_set_id := (p_confidence_frame #>> '{candidate_set,id}')::uuid;

    INSERT INTO public.ml_model_runs (
        id, canonical_event_id, learning_surface_id, pipeline_stage_id,
        run_kind, provider, model_id, adapter_id, assignment_origin,
        assignment_version, code_version, configuration, request_sha256,
        status, started_at, completed_at, idempotency_key
    ) VALUES (
        classification_id, canonical_event.id,
        'confidence_classification', 'classify', 'classification',
        p_confidence_frame #>> '{classification_run,provider}',
        p_confidence_frame #>> '{classification_run,model_id}',
        NULLIF(p_confidence_frame #>> '{classification_run,adapter_id}', ''),
        p_confidence_frame #>> '{classification_run,assignment_origin}',
        p_confidence_frame #>> '{classification_run,assignment_version}',
        p_confidence_frame #>> '{classification_run,code_version}',
        COALESCE(p_confidence_frame #> '{classification_run,configuration}', '{}'::jsonb),
        p_confidence_frame #>> '{classification_run,request_sha256}',
        'succeeded',
        (p_confidence_frame #>> '{classification_run,started_at}')::timestamptz,
        (p_confidence_frame #>> '{classification_run,completed_at}')::timestamptz,
        canonical_event.idempotency_key || ':classification'
    );

    INSERT INTO public.ml_classification_runs (
        model_run_id, feature_schema_version, feature_extractor_version,
        detector_version, threshold_version, taxonomy_version,
        threshold_snapshot
    ) VALUES (
        classification_id,
        p_confidence_frame #>> '{classification_run,feature_schema_version}',
        p_confidence_frame #>> '{classification_run,feature_extractor_version}',
        p_confidence_frame #>> '{classification_run,detector_version}',
        p_confidence_frame #>> '{classification_run,threshold_version}',
        p_confidence_frame #>> '{classification_run,taxonomy_version}',
        COALESCE(p_confidence_frame #> '{classification_run,threshold_snapshot}', '{}'::jsonb)
    );

    INSERT INTO public.ml_model_runs (
        id, canonical_event_id, learning_surface_id, pipeline_stage_id,
        run_kind, provider, model_id, adapter_id, assignment_origin,
        assignment_version, code_version, configuration, request_sha256,
        status, started_at, completed_at, idempotency_key
    ) VALUES (
        selection_id, canonical_event.id,
        'confidence_classification', 'select', 'deterministic_policy',
        'deterministic_policy',
        p_confidence_frame #>> '{selection_run,selection_policy_version}',
        NULL, 'deterministic_policy',
        p_confidence_frame #>> '{selection_run,selection_policy_version}',
        p_confidence_frame #>> '{selection_run,code_version}',
        COALESCE(p_confidence_frame #> '{selection_run,configuration}', '{}'::jsonb),
        p_confidence_frame #>> '{selection_run,request_sha256}',
        'succeeded',
        (p_confidence_frame #>> '{selection_run,started_at}')::timestamptz,
        (p_confidence_frame #>> '{selection_run,completed_at}')::timestamptz,
        canonical_event.idempotency_key || ':selection'
    );

    INSERT INTO public.ml_selection_runs (
        model_run_id, classification_run_id, execution_kind,
        selection_policy_version, eligibility_policy_version,
        threshold_version, exploration_probability, rng_algorithm,
        rng_seed, rng_draws
    ) VALUES (
        selection_id, classification_id, 'deterministic_policy',
        p_confidence_frame #>> '{selection_run,selection_policy_version}',
        p_confidence_frame #>> '{selection_run,eligibility_policy_version}',
        p_confidence_frame #>> '{selection_run,threshold_version}',
        (p_confidence_frame #>> '{selection_run,exploration_probability}')::numeric,
        p_confidence_frame #>> '{selection_run,rng_algorithm}',
        p_confidence_frame #>> '{selection_run,rng_seed}',
        p_confidence_frame #> '{selection_run,rng_draws}'
    );

    INSERT INTO public.ml_candidate_sets (
        id, canonical_event_id, selection_run_id,
        acquisition_principal_id, speaker_id, project_id,
        recording_attempt_id, take_id, candidate_set_version,
        pool_size, eligible_count, excluded_count, selected_count,
        frame_manifest, immutable_pool_sha256
    ) VALUES (
        v_candidate_set_id, canonical_event.id, selection_id,
        canonical_event.acquisition_principal_id, canonical_event.speaker_id,
        canonical_event.project_id, canonical_event.recording_attempt_id,
        canonical_event.take_id,
        p_confidence_frame #>> '{candidate_set,candidate_set_version}',
        pool_size, eligible_count, excluded_count, selected_count,
        frame_manifest, pool_sha256
    );

    FOR candidate IN SELECT value FROM jsonb_array_elements(
        p_confidence_frame #> '{candidate_set,candidates}'
    ) LOOP
        evidence := candidate -> 'evidence';
        object_metadata := evidence -> 'object';
        IF jsonb_typeof(evidence) <> 'object'
           OR jsonb_typeof(object_metadata) <> 'object'
           OR candidate ->> 'clip_id' IS NULL THEN
            RAISE EXCEPTION 'each confidence candidate requires exact audio evidence and clip id';
        END IF;
        IF jsonb_typeof(evidence -> 'coordinates') <> 'object'
           OR NOT (evidence -> 'coordinates' ? 'start_ms')
           OR NOT (evidence -> 'coordinates' ? 'end_ms')
           OR (evidence #>> '{coordinates,start_ms}')::integer < 0
           OR (evidence #>> '{coordinates,end_ms}')::integer
              <= (evidence #>> '{coordinates,start_ms}')::integer THEN
            RAISE EXCEPTION 'confidence audio evidence requires an exact positive span';
        END IF;
        IF object_metadata ->> 'content_type' NOT LIKE 'audio/%'
           OR (object_metadata ->> 'byte_size')::bigint <= 0 THEN
            RAISE EXCEPTION 'confidence evidence object must be non-empty audio';
        END IF;

        INSERT INTO public.ml_object_artifacts (
            id, acquisition_principal_id, speaker_id, consent_snapshot_id,
            object_store, bucket, object_key, sha256, byte_size, content_type,
            artifact_kind, retention_status, created_by
        ) VALUES (
            (object_metadata ->> 'id')::uuid,
            canonical_event.acquisition_principal_id, canonical_event.speaker_id,
            canonical_event.consent_snapshot_id, 'cloudflare_r2',
            object_metadata ->> 'bucket', object_metadata ->> 'object_key',
            object_metadata ->> 'sha256',
            (object_metadata ->> 'byte_size')::bigint,
            object_metadata ->> 'content_type', 'audio', 'eligible',
            'mlc2-confidence-finalizer:' || p_worker_id
        ) ON CONFLICT (object_key) DO NOTHING;

        SELECT * INTO object_row FROM public.ml_object_artifacts
         WHERE object_key = object_metadata ->> 'object_key';
        IF object_row.id IS NULL
           OR object_row.acquisition_principal_id
              <> canonical_event.acquisition_principal_id
           OR object_row.speaker_id <> canonical_event.speaker_id
           OR object_row.consent_snapshot_id <> canonical_event.consent_snapshot_id
           OR object_row.sha256 <> object_metadata ->> 'sha256'
           OR object_row.byte_size <> (object_metadata ->> 'byte_size')::bigint
           OR object_row.content_type <> object_metadata ->> 'content_type'
           OR object_row.artifact_kind <> 'audio'
           OR object_row.retention_status <> 'eligible' THEN
            RAISE EXCEPTION 'audio object metadata conflicts with immutable provenance';
        END IF;

        INSERT INTO public.ml_evidence_spans (
            id, canonical_event_id, acquisition_principal_id, speaker_id,
            project_id, recording_attempt_id, take_id, object_artifact_id,
            modality, coordinates, content_sha256, evidence_schema_version
        ) VALUES (
            (evidence ->> 'id')::uuid, canonical_event.id,
            canonical_event.acquisition_principal_id, canonical_event.speaker_id,
            canonical_event.project_id, canonical_event.recording_attempt_id,
            canonical_event.take_id, object_row.id, 'audio',
            evidence -> 'coordinates', evidence ->> 'content_sha256',
            evidence ->> 'evidence_schema_version'
        );
        SELECT * INTO evidence_row FROM public.ml_evidence_spans
         WHERE id = (evidence ->> 'id')::uuid;

        prediction_row := NULL;
        IF candidate ? 'prediction' AND candidate -> 'prediction' <> 'null'::jsonb THEN
            INSERT INTO public.ml_machine_predictions (
                id, classification_run_id, evidence_span_id, prediction_kind,
                predicted_value, confidence_score, probability_distribution,
                raw_output, output_schema_version
            ) VALUES (
                (candidate #>> '{prediction,id}')::uuid,
                classification_id, evidence_row.id,
                'confidence_classification',
                candidate #>> '{prediction,predicted_value}',
                (candidate #>> '{prediction,confidence_score}')::numeric,
                candidate #> '{prediction,probability_distribution}',
                candidate #> '{prediction,raw_output}',
                candidate #>> '{prediction,output_schema_version}'
            ) RETURNING * INTO prediction_row;
        END IF;

        INSERT INTO public.ml_candidates (
            id, candidate_set_id, candidate_key, clip_id, evidence_span_id,
            machine_prediction_id, eligible, exclusion_reason_code, score,
            rank, selected, selection_mode, selection_reason_code,
            sampling_probability, rng_draw_index
        ) VALUES (
            (candidate ->> 'id')::uuid, v_candidate_set_id,
            candidate ->> 'candidate_key', (candidate ->> 'clip_id')::uuid,
            evidence_row.id, prediction_row.id,
            (candidate ->> 'eligible')::boolean,
            NULLIF(candidate ->> 'exclusion_reason_code', ''),
            NULLIF(candidate ->> 'score', '')::numeric,
            NULLIF(candidate ->> 'rank', '')::integer,
            (candidate ->> 'selected')::boolean,
            candidate ->> 'selection_mode',
            candidate ->> 'selection_reason_code',
            (candidate ->> 'sampling_probability')::numeric,
            NULLIF(candidate ->> 'rng_draw_index', '')::integer
        );
    END LOOP;

    IF (SELECT count(*) FROM public.ml_candidates
         WHERE ml_candidates.candidate_set_id = v_candidate_set_id) <> pool_size THEN
        RAISE EXCEPTION 'confidence frame did not persist its complete candidate pool';
    END IF;

    RETURN jsonb_build_object(
        'canonical_event_id', canonical_event.id,
        'classification_run_id', classification_id,
        'selection_run_id', selection_id,
        'candidate_set_id', v_candidate_set_id,
        'immutable_pool_sha256', pool_sha256,
        'pool_size', pool_size,
        'eligible_count', eligible_count,
        'excluded_count', excluded_count,
        'selected_count', selected_count,
        'idempotent_replay', false
    );
END;
$$;

-- Keep these explicit as well as the defensive loop below.  The repository's
-- migration security gate statically proves that every new public table turns
-- RLS on in the same migration.
ALTER TABLE public.ml_model_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_classification_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_machine_predictions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_selection_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_candidate_sets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_candidates ENABLE ROW LEVEL SECURITY;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'ml_model_runs', 'ml_classification_runs',
        'ml_machine_predictions', 'ml_selection_runs',
        'ml_candidate_sets', 'ml_candidates'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', table_name);
        EXECUTE format(
            'REVOKE ALL ON TABLE public.%I FROM anon, authenticated', table_name
        );
        EXECUTE format(
            'GRANT SELECT ON TABLE public.%I TO service_role', table_name
        );
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON public.%I',
            table_name || '_append_only', table_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON public.%I '
            'FOR EACH ROW EXECUTE FUNCTION public.reject_mlc2_immutable_mutation()',
            table_name || '_append_only', table_name
        );
    END LOOP;
END;
$$;

REVOKE ALL ON FUNCTION public.finalize_mlc2_confidence_frame_v1(
    UUID, TEXT, JSONB, JSONB
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.finalize_mlc2_confidence_frame_v1(
    UUID, TEXT, JSONB, JSONB
) TO service_role;

COMMENT ON TABLE public.ml_model_runs IS
    'Provider-neutral runtime executions; confidence selection is a deterministic policy run, not an eighth learning surface.';
COMMENT ON TABLE public.ml_machine_predictions IS
    'Immutable machine confidence outputs kept separate from user, coach and peer judgments.';
COMMENT ON TABLE public.ml_candidate_sets IS
    'Atomically finalized complete confidence sampling frame with immutable server-computed hash.';
COMMENT ON FUNCTION public.finalize_mlc2_confidence_frame_v1(
    UUID, TEXT, JSONB, JSONB
) IS
    'Dark Slice-3 atomic confidence finalizer. No production producer is authorized to invoke it.';
