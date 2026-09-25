-- 0362 · An account deletion can start.
--
-- FOUNDER 2026-09-25, decision 6 ("fix it now"). Found in the E2 work.
--
-- WHAT WAS BROKEN. `services/data_purge.py` builds the subject graph from
-- `resolve_phase1_purge_subject_graph_v2` and, since 2026-09-19 (#559), adds
-- one key of its own: `delivery_job_ids`, the Feedback-language delivery jobs
-- the registry has addressed since 0327. `freeze_phase1_purge_inventory_v4`
-- recomputes the graph from v2 and requires the two to be IDENTICAL. v2 has no
-- `delivery_job_ids`, so every freeze raised PURGE_SUBJECT_GRAPH_MISMATCH —
-- even with the list empty, because the key itself differs. Every request sat
-- at `requested` with nothing erased. A second refusal waited behind it: the
-- freeze's locator map had no 'delivery_job' branch, so the registry's four
-- delivery-job dependencies would each have raised
-- PURGE_DEPENDENCY_TARGET_GRAPH_MISMATCH.
--
-- WHY IT WAS INVISIBLE. The rehearsal cases fed the freeze the graph the SQL
-- itself resolves, never the one the orchestrator sends. The new cases in
-- tests/test_account_deletion_starts_postgres.py run the orchestrator's own
-- freeze against the real schema, so the two halves are compared by the only
-- thing that decides: the freeze accepting them.
--
-- THE FIX HAS ONE SOURCE OF TRUTH. v3 is v2 plus `delivery_job_ids`, resolved
-- in SQL; the orchestrator now reads the whole graph from v3 instead of adding
-- a key of its own, so the two cannot drift apart this way again.
-- v2 is unchanged (the practice erasure of 0361 still reads it).
--
-- A THIRD REFUSAL, FOUND BY RUNNING IT. With the graph fixed, the rehearsal
-- froze — and put the request in `review_required` for a speaker with nothing
-- to review. The orchestrator counts a subject's rows in each registry
-- relation through PostgREST as service_role, and 0327 revoked service_role
-- from the coaching-bundle tables (writes go through their functions only).
-- Every count there failed, every failure became an `unknown` target, and an
-- `unknown` target stops the whole erasure. `count_phase1_purge_dependency_rows_v1`
-- counts instead, as its owner, and returns nothing but the number. The grant
-- posture of those tables is unchanged.
--
-- (A fourth, fixed in Python: fourteen registry entries carry a target kind
-- the freeze does not accept — storage_object, authorization_receipt,
-- provider_artifact — so each froze as `unknown` even at zero rows. The
-- orchestrator now files them as the database rows they are and keeps the
-- registry's label in the target's metadata.)
--
-- ADDITIVE AND IDEMPOTENT. Two new functions and one CREATE OR REPLACE whose
-- body is 0354's, byte for byte, but for the two commented lines. No table,
-- column or row is created, altered or dropped. Nothing runs on boot but the
-- definitions: a purge still starts only when an operator runs it.

CREATE OR REPLACE FUNCTION public.resolve_phase1_purge_subject_graph_v3(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    base_graph JSONB;
    principal_values TEXT[];
    delivery_job_values TEXT[];
BEGIN
    base_graph := public.resolve_phase1_purge_subject_graph_v2(
        p_acquisition_principal_id
    );
    SELECT ARRAY(SELECT jsonb_array_elements_text(base_graph->'principal_ids'))
      INTO principal_values;

    SELECT COALESCE(array_agg(value ORDER BY value COLLATE "C"), '{}'::text[])
      INTO delivery_job_values
      FROM (
          SELECT DISTINCT job.id::text AS value
            FROM public.feedback_language_delivery_materialization_jobs job
           WHERE job.acquisition_principal_id::text = ANY(principal_values)
      ) rows;

    RETURN base_graph || jsonb_build_object(
        'delivery_job_ids', to_jsonb(delivery_job_values)
    );
END;
$$;
REVOKE ALL ON FUNCTION public.resolve_phase1_purge_subject_graph_v3(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_purge_subject_graph_v3(UUID)
    TO service_role;

-- Counts one subject's rows in one relation, for the purge inventory only.
-- It returns a number and nothing else: no row, no column value. The relation
-- must be an ordinary table in `public` and the selector one of its live
-- columns; anything else raises rather than counting nothing, because a count
-- of zero is what lets the purge call a dependency clear.
CREATE OR REPLACE FUNCTION public.count_phase1_purge_dependency_rows_v1(
    p_relation TEXT,
    p_selector_column TEXT,
    p_values TEXT[]
) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    relation_oid OID;
    row_count BIGINT;
BEGIN
    IF p_values IS NULL OR cardinality(p_values) = 0 THEN
        RETURN 0;
    END IF;
    SELECT c.oid INTO relation_oid
      FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relname = p_relation
       AND c.relkind IN ('r', 'p');
    IF relation_oid IS NULL THEN
        RAISE EXCEPTION 'PURGE_COUNT_RELATION_INVALID';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_catalog.pg_attribute a
         WHERE a.attrelid = relation_oid AND a.attname = p_selector_column
           AND a.attnum > 0 AND NOT a.attisdropped
    ) THEN
        RAISE EXCEPTION 'PURGE_COUNT_SELECTOR_INVALID';
    END IF;
    EXECUTE format(
        'SELECT count(*) FROM public.%I WHERE %I::text = ANY($1)',
        p_relation, p_selector_column
    ) INTO row_count USING p_values;
    RETURN row_count;
END;
$$;
REVOKE ALL ON FUNCTION public.count_phase1_purge_dependency_rows_v1(TEXT,TEXT,TEXT[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.count_phase1_purge_dependency_rows_v1(TEXT,TEXT,TEXT[])
    TO service_role;

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
    -- 0362: the graph the orchestrator sends has carried delivery_job_ids
    -- since 2026-09-19; v2 never produced it, so no freeze could succeed.
    expected_subject_graph := public.resolve_phase1_purge_subject_graph_v3(
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
                -- 0362: the registry has addressed delivery jobs since 0327.
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

-- CREATE OR REPLACE keeps the ACL; restated so this file says who may call it.
REVOKE ALL ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) TO service_role;
