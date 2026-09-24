-- 0353 · Deletion reaches a practice recording.
--
-- B-4 (major), ML provenance audit 2026-09-22.
--
-- `services/data_purge.py:355` has emitted storage targets carrying
-- `source_relation = 'processing_practice_objects'` since migration 0334 gave
-- practice audio its own registry. Neither function that consumes those
-- targets knew the relation existed:
--
--   * `freeze_phase1_purge_inventory_v4` (0313) accepted only
--     `processing_audio_objects` and `processing_orphan_objects`; its ELSE
--     raised `PURGE_STORAGE_TARGET_SOURCE_INVALID`.
--   * `mark_phase1_storage_object_purged_v1` (0312) had the same two branches
--     and raised `PURGE_OBJECT_SOURCE_INVALID`.
--
-- So a subject whose only stored audio is a practice recording could not be
-- purged AT ALL. The request was written, the freeze refused, and the row sat
-- at `requested` for ever with nothing erased. Not a partial deletion — no
-- deletion, and a record saying one had been asked for.
--
-- WHY IT WAS INVISIBLE. With one speaker nobody ever asks to be erased, and
-- no rehearsal lane carried a `processing_practice_objects` row to purge. The
-- lane now builds one (tests/integration/confident_moment_rehearsal.sh) and a
-- unit-tier test asserts every relation the orchestrator can emit is one the
-- SQL knows, so the next table to get its own registry cannot drift the same
-- way.
--
-- THE TABLE WAS ALWAYS READY. 0334 gave it `deleted_at`, commented "stamped
-- by the purge once the object is gone from storage, mirrors the sibling
-- tables". Only the two functions were never told about it.
--
-- ADDITIVE AND IDEMPOTENT. Two `CREATE OR REPLACE FUNCTION`s and the restated
-- grants those two already carry: no table, column or row is created, altered
-- or dropped, and no role gains anything. Both bodies are their current
-- definitions with one branch added; every other path, check and error code is
-- byte-identical to what runs today. Replacing a function preserves its ACL,
-- so each REVOKE/GRANT pair below re-asserts the service_role-only grant its
-- function already has.
--
-- THIS OPENS NOTHING. It lets an erasure that is already authorised actually
-- complete. Every guard either function applied before, it applies now.

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
-- CREATE OR REPLACE preserves a function's ACL, so these restate the grants
-- 0313/0334 already made rather than changing them. They are here because a
-- migration that creates a function must say, in its own text, who may call
-- it — `tests/test_migration_security_rules.py` enforces that, and a reader
-- auditing this file should not have to go find another one to learn that the
-- erasure writers are service_role-only.
REVOKE ALL ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) TO service_role;

CREATE OR REPLACE FUNCTION public.mark_phase1_storage_object_purged_v1(
    p_purge_request_id UUID,
    p_source_relation TEXT,
    p_source_id UUID,
    p_storage_provider TEXT,
    p_bucket TEXT,
    p_object_key TEXT,
    p_exact_bytes_sha256 TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE req public.data_purge_requests; affected INTEGER;
BEGIN
    SELECT * INTO req FROM public.data_purge_requests
     WHERE id = p_purge_request_id FOR SHARE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    IF p_exact_bytes_sha256 !~ '^[0-9a-f]{64}$'
    THEN RAISE EXCEPTION 'PURGE_OBJECT_HASH_INVALID'; END IF;
    IF p_source_relation = 'processing_audio_objects' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.processing_audio_objects
             WHERE id = p_source_id
               AND acquisition_principal_id = req.acquisition_principal_id
               AND storage_provider = p_storage_provider AND bucket = p_bucket
               AND object_key = p_object_key
               AND exact_bytes_sha256 = lower(p_exact_bytes_sha256)
        ) THEN RAISE EXCEPTION 'PURGE_OBJECT_METADATA_MISMATCH'; END IF;
        INSERT INTO public.processing_audio_object_deletion_events (
            audio_object_id, purge_request_id, acquisition_principal_id,
            storage_provider, bucket, object_key, exact_bytes_sha256,
            evidence_sha256
        ) VALUES (
            p_source_id, req.id, req.acquisition_principal_id,
            p_storage_provider, p_bucket, p_object_key,
            lower(p_exact_bytes_sha256),
            encode(extensions.digest(concat_ws(':',
                req.id::text, p_source_id::text, p_storage_provider,
                p_bucket, p_object_key, lower(p_exact_bytes_sha256),
                'verified_deleted'
            ), 'sha256'), 'hex')
        ) ON CONFLICT (audio_object_id) DO NOTHING;
        SELECT count(*) INTO affected
          FROM public.processing_audio_object_deletion_events
         WHERE audio_object_id = p_source_id
           AND acquisition_principal_id = req.acquisition_principal_id
           AND storage_provider = p_storage_provider AND bucket = p_bucket
           AND object_key = p_object_key
           AND exact_bytes_sha256 = lower(p_exact_bytes_sha256);
    ELSIF p_source_relation = 'processing_orphan_objects' THEN
        UPDATE public.processing_orphan_objects SET
            status = 'deleted', deleted_at = now(), checked_at = now(),
            updated_at = now(), last_error_code = NULL
         WHERE id = p_source_id
           AND acquisition_principal_id = req.acquisition_principal_id
           AND storage_provider = p_storage_provider AND bucket = p_bucket
           AND object_key = p_object_key
           AND exact_bytes_sha256 = lower(p_exact_bytes_sha256)
           AND status NOT IN ('deleted', 'referenced');
        GET DIAGNOSTICS affected = ROW_COUNT;
    ELSIF p_source_relation = 'processing_practice_objects' THEN
        -- The column and its comment arrived with the table in 0334
        -- ("stamped by the purge once the object is gone from storage,
        -- mirrors the sibling tables"); only this function was never told.
        -- Guarded on deleted_at for the same reason the orphan branch
        -- guards on status: a second mark for an object already erased is
        -- a mismatch, not a no-op.
        UPDATE public.processing_practice_objects SET deleted_at = now()
         WHERE id = p_source_id
           AND acquisition_principal_id = req.acquisition_principal_id
           AND storage_provider = p_storage_provider AND bucket = p_bucket
           AND object_key = p_object_key
           AND exact_bytes_sha256 = lower(p_exact_bytes_sha256)
           AND deleted_at IS NULL;
        GET DIAGNOSTICS affected = ROW_COUNT;
    ELSE
        RAISE EXCEPTION 'PURGE_OBJECT_SOURCE_INVALID';
    END IF;
    IF affected <> 1 THEN RAISE EXCEPTION 'PURGE_OBJECT_METADATA_MISMATCH'; END IF;
    RETURN jsonb_build_object(
        'source_relation', p_source_relation, 'source_id', p_source_id,
        'deleted_at_recorded', true
    );
END;
$$;
REVOKE ALL ON FUNCTION public.mark_phase1_storage_object_purged_v1(
    UUID,TEXT,UUID,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.mark_phase1_storage_object_purged_v1(
    UUID,TEXT,UUID,TEXT,TEXT,TEXT,TEXT
) TO service_role;
