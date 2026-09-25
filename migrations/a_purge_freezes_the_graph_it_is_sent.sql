-- 0362 · A purge freezes the graph it is sent.
--
-- #490 (2026-09-13) taught `services/data_purge.py` a subject-graph key,
-- `delivery_job_ids`: `SubjectGraph.payload()` always carries it, and four
-- registry dependencies locate their rows by it (`locator_kind =
-- 'delivery_job'`). The two SQL functions that check that payload were never
-- told:
--
--   * `freeze_phase1_purge_inventory_v4` compares the graph it is sent with
--     `resolve_phase1_purge_subject_graph_v2(...)` using IS DISTINCT FROM. The
--     resolver never returned `delivery_job_ids`, so the comparison failed for
--     EVERY subject and the freeze raised `PURGE_SUBJECT_GRAPH_MISMATCH`;
--   * its locator CASE had no `'delivery_job'` branch, so even an agreeing
--     graph would have raised `PURGE_DEPENDENCY_TARGET_GRAPH_MISMATCH` on the
--     four job-keyed dependency targets every inventory emits.
--
-- So every governed Phase-1 purge stopped at the freeze: the request row was
-- written, it sat at `requested`, and nothing was erased. The rehearsal cases
-- froze with the resolver's own output and never with the payload Python
-- builds; tests/test_purge_freeze_python_payload_postgres.py now drives the
-- real orchestrator into the real freeze.
--
-- THE SERVER STAYS AUTHORITATIVE. The fix is not to trust the key Python
-- sends. The resolver now derives it — from the table and column the
-- orchestrator read, for the graph's own principals — and the exact
-- comparison stays exactly as strict. Python stops computing the key and
-- takes the server's (same PR), so the two cannot drift again.
--
-- ADDITIVE AND IDEMPOTENT. Two `CREATE OR REPLACE FUNCTION`s and the grants
-- they already carry. No table, column or row is created, altered or dropped,
-- and no role gains anything. The resolver is its 0313 body plus one derived
-- key; the freeze is its 0354 body plus one CASE branch; every other path,
-- check and error code is byte-identical to what runs today.
--
-- D11. 0327 injects advisory-lock preambles into a closed registry of writer
-- bodies. Neither function here is in that registry (its purge entries are
-- `mark_phase1_storage_object_purged_v1` and `finalize_phase1_purge_v3`), so
-- replacing them removes no lock — and this file touches neither of those two.
--
-- THIS OPENS NOTHING. It lets an erasure that is already authorised get past
-- its first step. A graph naming a job the server does not attribute to the
-- subject is still refused, and so is a target locating one.

CREATE OR REPLACE FUNCTION public.resolve_phase1_purge_subject_graph_v2(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    base_graph JSONB;
    principal_values TEXT[];
    user_values TEXT[];
    take_values TEXT[];
    speaker_values TEXT[];
    practice_values TEXT[];
    practice_attempt_values TEXT[];
    exercise_audio_lineage_values TEXT[];
    exercise_blind_packet_values TEXT[];
    delivery_job_values TEXT[] := '{}'::text[];
BEGIN
    base_graph := public.resolve_phase1_purge_subject_graph_v1(
        p_acquisition_principal_id
    );
    SELECT ARRAY(SELECT jsonb_array_elements_text(base_graph->'principal_ids'))
      INTO principal_values;
    SELECT ARRAY(SELECT jsonb_array_elements_text(base_graph->'user_ids'))
      INTO user_values;
    SELECT ARRAY(SELECT jsonb_array_elements_text(base_graph->'take_ids'))
      INTO take_values;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO speaker_values
      FROM (
          SELECT DISTINCT binding.speaker_id::text AS value
            FROM public.ml_speaker_principals binding
           WHERE binding.acquisition_principal_id::text = ANY(principal_values)
      ) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO practice_values
      FROM (
          SELECT DISTINCT practice.id::text AS value
            FROM public.confident_voice_practice practice
           WHERE practice.owner_user_id::text = ANY(user_values)
              OR practice.take_session_id::text = ANY(take_values)
      ) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO practice_attempt_values
      FROM (
          SELECT DISTINCT attempt.id::text AS value
            FROM public.confident_voice_practice_attempt attempt
           WHERE attempt.practice_id::text = ANY(practice_values)
      ) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO exercise_audio_lineage_values
      FROM (
          SELECT DISTINCT lineage.id::text AS value
            FROM public.exercise_audio_lineages lineage
           WHERE lineage.acquisition_principal_id::text = ANY(principal_values)
              OR lineage.speaker_id::text = ANY(speaker_values)
      ) rows;

    SELECT COALESCE(array_agg(value ORDER BY value), '{}'::text[])
      INTO exercise_blind_packet_values
      FROM (
          SELECT DISTINCT packet.id::text AS value
            FROM public.exercise_blind_packets packet
           WHERE packet.audio_lineage_id::text =
                 ANY(exercise_audio_lineage_values)
      ) rows;

    -- 0362. The orchestrator has sent this key since #490 and the freeze
    -- compares graphs exactly, so the server must derive it too — from the
    -- same table, by the same column, for the same principals. Ordered as
    -- uuid (byte order = lower-case hex order), which is what Python's
    -- sorted() gives and what no text collation can disturb. The table
    -- arrives with 0327; before that the subject simply has no such job.
    IF to_regclass('public.feedback_language_delivery_materialization_jobs')
       IS NOT NULL THEN
        SELECT COALESCE(array_agg(value::text ORDER BY value), '{}'::text[])
          INTO delivery_job_values
          FROM (
              SELECT DISTINCT job.id AS value
                FROM public.feedback_language_delivery_materialization_jobs job
               WHERE job.acquisition_principal_id::text = ANY(principal_values)
          ) rows;
    END IF;

    RETURN base_graph || jsonb_build_object(
        'speaker_ids', to_jsonb(speaker_values),
        'practice_ids', to_jsonb(practice_values),
        'practice_attempt_ids', to_jsonb(practice_attempt_values),
        'exercise_audio_lineage_ids', to_jsonb(exercise_audio_lineage_values),
        'exercise_blind_packet_ids', to_jsonb(exercise_blind_packet_values),
        'delivery_job_ids', to_jsonb(delivery_job_values)
    );
END;
$$;

-- CREATE OR REPLACE preserves a function's ACL, so each pair below restates
-- the service_role-only grant its function already has; a migration that
-- creates a function says in its own text who may call it.
REVOKE ALL ON FUNCTION public.resolve_phase1_purge_subject_graph_v2(
    UUID
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_purge_subject_graph_v2(
    UUID
) TO service_role;

CREATE OR REPLACE FUNCTION public.freeze_phase1_purge_inventory_v4(
    p_purge_request_id UUID,
    p_resolver_version TEXT,
    p_dependency_manifest_sha256 TEXT,
    p_subject_graph JSONB,
    p_targets JSONB,
    p_catalog_sha256 TEXT,
    p_catalog_unknown_relations TEXT[]
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE req public.data_purge_requests; existing public.data_purge_inventory_manifests;
        item JSONB; kind TEXT; ref TEXT; item_state TEXT; unknown_count INTEGER;
        computed_subject_graph_sha256 TEXT; computed_target_manifest_sha256 TEXT;
        expected_subject_graph JSONB; item_metadata JSONB; locator_key TEXT;
BEGIN
    SELECT * INTO req FROM public.data_purge_requests
     WHERE id = p_purge_request_id FOR UPDATE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    IF req.state = 'done' THEN RAISE EXCEPTION 'PURGE_ALREADY_FINALIZED'; END IF;
    IF jsonb_typeof(p_subject_graph) <> 'object'
       OR jsonb_typeof(p_targets) <> 'array'
       OR jsonb_array_length(p_targets) = 0
    THEN RAISE EXCEPTION 'PURGE_MANIFEST_INVALID'; END IF;
    IF p_resolver_version <> 'phase1-purge-resolver-v4' THEN
        RAISE EXCEPTION 'PURGE_RESOLVER_VERSION_INVALID';
    END IF;
    expected_subject_graph := public.resolve_phase1_purge_subject_graph_v2(
        req.acquisition_principal_id
    );
    IF p_subject_graph IS DISTINCT FROM expected_subject_graph THEN
        RAISE EXCEPTION 'PURGE_SUBJECT_GRAPH_MISMATCH';
    END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_targets) candidate
         GROUP BY COALESCE(candidate->>'target_kind', 'unknown'),
                  COALESCE(NULLIF(candidate->>'target_ref', ''), 'unresolved')
        HAVING count(*) > 1
    ) THEN RAISE EXCEPTION 'PURGE_MANIFEST_DUPLICATE_TARGET'; END IF;
    IF p_dependency_manifest_sha256 !~ '^[0-9a-f]{64}$'
       OR p_catalog_sha256 !~ '^[0-9a-f]{64}$'
    THEN RAISE EXCEPTION 'PURGE_MANIFEST_HASH_INVALID'; END IF;

    computed_subject_graph_sha256 := encode(
        extensions.digest(p_subject_graph::text, 'sha256'), 'hex'
    );
    computed_target_manifest_sha256 := encode(
        extensions.digest(p_targets::text, 'sha256'), 'hex'
    );

    SELECT * INTO existing FROM public.data_purge_inventory_manifests
     WHERE purge_request_id = p_purge_request_id;
    IF existing.id IS NOT NULL THEN
        IF existing.resolver_version <> p_resolver_version
           OR existing.dependency_manifest_sha256 <>
              lower(p_dependency_manifest_sha256)
           OR existing.subject_graph_sha256 <> computed_subject_graph_sha256
           OR existing.target_manifest_sha256 <>
              computed_target_manifest_sha256
           OR existing.catalog_sha256 <> lower(p_catalog_sha256)
           OR existing.catalog_unknown_relations <>
              COALESCE(p_catalog_unknown_relations, '{}'::text[])
        THEN RAISE EXCEPTION 'PURGE_INVENTORY_REPLAY_CONFLICT'; END IF;
    ELSE
        INSERT INTO public.data_purge_inventory_manifests (
            purge_request_id, resolver_version, dependency_manifest_sha256,
            subject_graph, subject_graph_sha256, target_manifest_sha256,
            catalog_sha256, catalog_unknown_relations
        ) VALUES (
            p_purge_request_id, p_resolver_version,
            lower(p_dependency_manifest_sha256), p_subject_graph,
            computed_subject_graph_sha256, computed_target_manifest_sha256,
            lower(p_catalog_sha256),
            COALESCE(p_catalog_unknown_relations, '{}'::text[])
        );
    END IF;

    FOR item IN SELECT value FROM jsonb_array_elements(p_targets) LOOP
        kind := COALESCE(item->>'target_kind', 'unknown');
        ref := COALESCE(NULLIF(item->>'target_ref', ''), 'unresolved');
        item_metadata := COALESCE(item->'metadata', '{}'::jsonb);
        IF kind NOT IN (
            'database_row', 'r2_object', 'supabase_object', 'transcript',
            'derived_feedback', 'processing_queue', 'provider_operation',
            'coach_packet', 'cache', 'dataset_lineage', 'model_lineage'
        ) THEN kind := 'unknown'; END IF;
        IF kind <> 'unknown' AND ref LIKE 'dependency:%' THEN
            locator_key := CASE item_metadata->>'locator_kind'
                WHEN 'principal' THEN 'principal_ids'
                WHEN 'user' THEN 'user_ids'
                WHEN 'project' THEN 'project_ids'
                WHEN 'take' THEN 'take_ids'
                WHEN 'recording' THEN 'recording_ids'
                WHEN 'snippet' THEN 'snippet_ids'
                WHEN 'permit' THEN 'permit_ids'
                WHEN 'job' THEN 'job_ids'
                WHEN 'speaker' THEN 'speaker_ids'
                WHEN 'practice' THEN 'practice_ids'
                WHEN 'practice_attempt' THEN 'practice_attempt_ids'
                WHEN 'exercise_audio_lineage' THEN 'exercise_audio_lineage_ids'
                WHEN 'exercise_blind_packet' THEN 'exercise_blind_packet_ids'
                WHEN 'delivery_job' THEN 'delivery_job_ids'
                ELSE NULL END;
            IF locator_key IS NULL
               OR length(COALESCE(item_metadata->>'dependency_code', '')) = 0
               OR ref <> ('dependency:' || (item_metadata->>'dependency_code'))
               OR length(COALESCE(item_metadata->>'relation', '')) = 0
               OR length(COALESCE(item_metadata->>'selector_column', '')) = 0
               OR jsonb_typeof(item_metadata->'locator_values') <> 'array'
               OR item_metadata->'locator_values' IS DISTINCT FROM
                  p_subject_graph->locator_key
            THEN RAISE EXCEPTION 'PURGE_DEPENDENCY_TARGET_GRAPH_MISMATCH'; END IF;
        ELSIF kind IN ('r2_object', 'supabase_object') THEN
            IF item_metadata->>'source_relation' = 'processing_audio_objects' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM public.processing_audio_objects object_row
                     WHERE object_row.id =
                           (item_metadata->>'source_id')::uuid
                       AND object_row.acquisition_principal_id =
                           req.acquisition_principal_id
                       AND object_row.storage_provider = item_metadata->>'provider'
                       AND object_row.bucket = item_metadata->>'bucket'
                       AND object_row.object_key = item_metadata->>'key'
                       AND object_row.exact_bytes_sha256 =
                           lower(item_metadata->>'sha256')
                ) THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_GRAPH_MISMATCH'; END IF;
            ELSIF item_metadata->>'source_relation' =
                  'processing_orphan_objects' THEN
                IF NOT EXISTS (
                    SELECT 1 FROM public.processing_orphan_objects object_row
                     WHERE object_row.id =
                           (item_metadata->>'source_id')::uuid
                       AND object_row.acquisition_principal_id =
                           req.acquisition_principal_id
                       AND object_row.storage_provider = item_metadata->>'provider'
                       AND object_row.bucket = item_metadata->>'bucket'
                       AND object_row.object_key = item_metadata->>'key'
                       AND object_row.exact_bytes_sha256 =
                           lower(item_metadata->>'sha256')
                ) THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_GRAPH_MISMATCH'; END IF;
            ELSIF item_metadata->>'source_relation' =
                  'processing_practice_objects' THEN
                -- B-4 (audit 2026-09-22). The orchestrator has emitted this
                -- relation since 0334 and this function never knew it, so a
                -- subject whose only stored audio is a practice recording
                -- could not be purged at all: the freeze raised
                -- SOURCE_INVALID and the request sat at 'requested'.
                -- Verified exactly as its two siblings are.
                IF NOT EXISTS (
                    SELECT 1 FROM public.processing_practice_objects object_row
                     WHERE object_row.id =
                           (item_metadata->>'source_id')::uuid
                       AND object_row.acquisition_principal_id =
                           req.acquisition_principal_id
                       AND object_row.storage_provider = item_metadata->>'provider'
                       AND object_row.bucket = item_metadata->>'bucket'
                       AND object_row.object_key = item_metadata->>'key'
                       AND object_row.exact_bytes_sha256 =
                           lower(item_metadata->>'sha256')
                ) THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_GRAPH_MISMATCH'; END IF;
            ELSE
                RAISE EXCEPTION 'PURGE_STORAGE_TARGET_SOURCE_INVALID';
            END IF;
            IF (kind = 'r2_object') IS DISTINCT FROM
               (item_metadata->>'provider' = 'r2')
            THEN RAISE EXCEPTION 'PURGE_STORAGE_TARGET_KIND_MISMATCH'; END IF;
        ELSIF kind = 'provider_operation' THEN
            IF NOT EXISTS (
                SELECT 1
                  FROM public.processing_provider_operations operation
                  JOIN public.processing_provider_permits permit
                    ON permit.id = operation.permit_id
                 WHERE operation.id =
                       (item_metadata->>'provider_operation_id')::uuid
                   AND permit.acquisition_principal_id =
                       req.acquisition_principal_id
                   AND permit.provider = item_metadata->>'provider'
                   AND permit.operation_kind = item_metadata->>'operation_kind'
                   AND operation.provider_operation_ref IS NOT DISTINCT FROM
                       item_metadata->>'provider_operation_ref'
            ) THEN RAISE EXCEPTION 'PURGE_PROVIDER_TARGET_GRAPH_MISMATCH'; END IF;
        ELSIF kind <> 'unknown' THEN
            RAISE EXCEPTION 'PURGE_TARGET_SOURCE_INVALID';
        END IF;
        item_state := CASE WHEN kind = 'unknown' THEN 'unknown' ELSE 'pending' END;
        INSERT INTO public.data_purge_targets (
            purge_request_id, target_kind, target_ref, resolver_version,
            state, initial_match_count, metadata
        ) VALUES (
            p_purge_request_id, kind, ref, p_resolver_version, item_state,
            GREATEST(0, COALESCE((item->>'initial_match_count')::integer, 0)),
            item_metadata
        ) ON CONFLICT (purge_request_id, target_kind, target_ref) DO NOTHING;
    END LOOP;
    FOREACH ref IN ARRAY COALESCE(p_catalog_unknown_relations, '{}'::text[]) LOOP
        INSERT INTO public.data_purge_targets (
            purge_request_id, target_kind, target_ref, resolver_version,
            state, metadata
        ) VALUES (
            p_purge_request_id, 'unknown', 'catalog:' || ref,
            p_resolver_version, 'unknown',
            jsonb_build_object('reason_code', 'UNCLASSIFIED_SUBJECT_RELATION')
        ) ON CONFLICT (purge_request_id, target_kind, target_ref) DO NOTHING;
    END LOOP;
    SELECT count(*) INTO unknown_count FROM public.data_purge_targets
     WHERE purge_request_id = p_purge_request_id AND state = 'unknown';
    UPDATE public.data_purge_requests
       SET state = CASE WHEN unknown_count > 0
                        THEN 'review_required' ELSE 'in_progress' END
     WHERE id = p_purge_request_id;
    RETURN jsonb_build_object(
        'purge_request_id', p_purge_request_id,
        'state', CASE WHEN unknown_count > 0
                      THEN 'review_required' ELSE 'in_progress' END,
        'unknown_target_count', unknown_count,
        'inventory_sha256', computed_target_manifest_sha256
    );
END;
$$;

REVOKE ALL ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) TO service_role;
