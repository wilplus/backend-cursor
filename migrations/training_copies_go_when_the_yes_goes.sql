-- Training copies go when the yes goes (SPEC-training-corpus §6.2, §6.3,
-- phase P4; founder locks C3, Q3, 2026-09-25).
--
-- 1. WITHDRAWAL. `record_mlc2_consent_withdrawal_v2` (0373) now also marks
--    every active copy of that person `purge_pending`, in the same
--    transaction as the withdrawal event. The corpus purge job erases them:
--    object deleted and verified absent, then the row. No retraining after
--    withdrawal; a model already trained is not un-trained (Q3).
--
-- 2. ACCOUNT ERASURE. The account purge now reaches the copies' audio:
--    `freeze_phase1_purge_inventory_v4` accepts `training_corpus_items` as a
--    storage-target source, and `mark_phase1_storage_object_purged_v1`
--    marks the copy `purged` once its object is verified gone. The registry
--    (services/data_purge_registry.py) moves the table from `external_review`
--    to `delete`, so the rows go with the account (C3: account erasure
--    always deletes them).
--
-- 3. NOT YET: `retain_while_training_consented`, which keeps copies through a
--    PROJECT delete for someone whose training yes is active. There is no
--    project-scoped purge to apply it to: `data_purge_requests` has no
--    project coordinate and no `project_deletion` trigger. It lands with
--    that purge (P1). Until then every purge that exists is principal-wide,
--    and for those the spec's answer is always delete.
--
-- THE D11 LOCK. `mark_phase1_storage_object_purged_v1` is a D11 writer whose
-- lock preamble lives only in the database (0327, 0365). Re-issuing it from
-- source drops the preamble, so this file ends with 0365's own re-injection
-- for that function, its registry entry byte-identical to 0327's
-- (tests/test_d11_writer_markers_survive_the_manifest.py checks).
--
-- The freeze and the mark are rebuilt from their current definitions (0362,
-- 0354) with one branch each added; nothing else in them changes.
--
-- Additive and idempotent. No table, column or row is dropped.

BEGIN;

CREATE OR REPLACE FUNCTION public.record_mlc2_consent_withdrawal_v2(
    p_acquisition_principal_id UUID,
    p_grant_event_id UUID,
    p_purpose TEXT,
    p_source_route TEXT,
    p_client_version TEXT,
    p_affirmative_action JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS public.ml_consent_events
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    grant_event public.ml_consent_events;
    policy public.ml_consent_policies;
    withdrawal public.ml_consent_events;
BEGIN
    IF p_purpose IS DISTINCT FROM 'pooled_model_improvement' THEN
        RAISE EXCEPTION 'WITHDRAWAL_PURPOSE_NOT_SUPPORTED';
    END IF;
    IF NULLIF(btrim(p_idempotency_key), '') IS NULL
       OR jsonb_typeof(p_affirmative_action) IS DISTINCT FROM 'object' THEN
        RAISE EXCEPTION 'TRAINING_WITHDRAWAL_INPUT_INVALID';
    END IF;
    SELECT * INTO grant_event FROM public.ml_consent_events
     WHERE id = p_grant_event_id
       AND acquisition_principal_id = p_acquisition_principal_id
       AND event_kind = 'grant';
    SELECT * INTO policy FROM public.ml_consent_policies
     WHERE version = grant_event.consent_policy_version;
    IF grant_event.id IS NULL OR policy.grant_scope IS DISTINCT FROM 'training_only'
       OR NOT EXISTS (SELECT 1 FROM public.ml_consent_event_purposes
                       WHERE consent_event_id = grant_event.id
                         AND purpose = p_purpose) THEN
        RAISE EXCEPTION 'TRAINING_GRANT_NOT_FOUND';
    END IF;
    IF p_occurred_at < grant_event.occurred_at THEN
        RAISE EXCEPTION 'WITHDRAWAL_CANNOT_PRECEDE_GRANT';
    END IF;

    INSERT INTO public.ml_consent_events (
        acquisition_principal_id, consent_policy_version,
        product_legal_approval_id, accepted_copy_sha256, event_kind,
        jurisdiction, terms_version, privacy_policy_version, source_route,
        client_version, affirmative_action, occurred_at, idempotency_key,
        supersedes_event_id
    ) VALUES (
        p_acquisition_principal_id, grant_event.consent_policy_version,
        grant_event.product_legal_approval_id, grant_event.accepted_copy_sha256,
        'withdraw', grant_event.jurisdiction, grant_event.terms_version,
        grant_event.privacy_policy_version, p_source_route, p_client_version,
        p_affirmative_action, p_occurred_at, p_idempotency_key, grant_event.id
    ) ON CONFLICT (idempotency_key) DO NOTHING;

    SELECT * INTO withdrawal FROM public.ml_consent_events
     WHERE idempotency_key = p_idempotency_key;
    IF withdrawal.supersedes_event_id IS DISTINCT FROM grant_event.id
       OR withdrawal.event_kind <> 'withdraw' THEN
        RAISE EXCEPTION 'TRAINING_WITHDRAWAL_IDEMPOTENCY_COLLISION';
    END IF;

    -- Only the withdrawn purpose; every other purpose stays as it was.
    INSERT INTO public.ml_consent_event_purposes (
        consent_event_id, purpose, article_6_basis, article_9_basis
    )
    SELECT withdrawal.id, purpose, article_6_basis, article_9_basis
      FROM public.ml_consent_event_purposes
     WHERE consent_event_id = grant_event.id AND purpose = p_purpose
    ON CONFLICT (consent_event_id, purpose) DO NOTHING;

    -- SPEC §6.3: every copy the person made for training is now due for
    -- erasure. The state moves forward only (0375's guard); the corpus purge
    -- (services/training_corpus.py purge_due_copies) deletes each object,
    -- verifies it is gone, and erases the row. Idempotent: a replay finds nothing active.
    UPDATE public.training_corpus_items SET
        state = 'purge_pending', state_changed_at = now()
     WHERE acquisition_principal_id = p_acquisition_principal_id
       AND state = 'active';
    RETURN withdrawal;
END;
$$;

REVOKE ALL ON FUNCTION public.record_mlc2_consent_withdrawal_v2(
    UUID, UUID, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_mlc2_consent_withdrawal_v2(
    UUID, UUID, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT) TO service_role;

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
            ELSIF item_metadata->>'source_relation' =
                  'training_corpus_items' THEN
                -- P4 (SPEC-training-corpus §6.2): a training copy's audio.
                -- Verified exactly as its siblings are; the key is always
                -- under training-corpus/, never a product object.
                IF NOT EXISTS (
                    SELECT 1 FROM public.training_corpus_items object_row
                     WHERE object_row.id =
                           (item_metadata->>'source_id')::uuid
                       AND object_row.acquisition_principal_id =
                           req.acquisition_principal_id
                       AND object_row.storage_provider = item_metadata->>'provider'
                       AND object_row.bucket = item_metadata->>'bucket'
                       AND object_row.storage_key = item_metadata->>'key'
                       AND object_row.object_sha256 =
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
    ELSIF p_source_relation = 'training_corpus_items' THEN
        -- P4: the copy's audio is gone from storage. The row moves to
        -- `purged` (forward only, 0375's guard); the purge's dependency step
        -- then deletes it with the rest of the subject's copies.
        UPDATE public.training_corpus_items SET
            state = 'purged', state_changed_at = now()
         WHERE id = p_source_id
           AND acquisition_principal_id = req.acquisition_principal_id
           AND storage_provider = p_storage_provider AND bucket = p_bucket
           AND storage_key = p_object_key
           AND object_sha256 = lower(p_exact_bytes_sha256)
           AND state <> 'purged';
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


DO $d11_writer_reclosure$
DECLARE
 spec jsonb;
 target regprocedure;
 definition text;
 injection text;
 openings integer;
 missing text;
BEGIN
 FOR spec IN SELECT value FROM jsonb_array_elements($registry$
 [
  {"signature":"public.mark_phase1_storage_object_purged_v1(uuid,text,uuid,text,text,text,text)","marker":"D11 writer: object purge","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||request.acquisition_principal_id::text,0)) FROM public.data_purge_requests request WHERE request.id=p_purge_request_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||project_row.id::text,0)) FROM public.projects project_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=project_row.owner_principal_id WHERE request.id=p_purge_request_id ORDER BY project_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||take_row.id::text,0)) FROM public.v2_sessions take_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=take_row.owner_principal_id WHERE request.id=p_purge_request_id ORDER BY take_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||membership.project_id::text||':'||membership.take_id::text,0)) FROM public.feedback_v3_memberships membership JOIN public.data_purge_requests request ON request.acquisition_principal_id=membership.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY membership.project_id,membership.take_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||object_row.recording_attempt_id::text,0)) FROM public.processing_audio_objects object_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=object_row.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY object_row.recording_attempt_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||object_row.id::text,0)) FROM public.processing_audio_objects object_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=object_row.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY object_row.id;\n"}
 ]$registry$::jsonb) LOOP
  target:=to_regprocedure(spec->>'signature');
  IF target IS NULL THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_REGISTRY_DRIFT: %',spec->>'signature';
  END IF;
  definition:=pg_get_functiondef(target);
  IF position(spec->>'marker' IN definition)=0 THEN
   -- Whole lines, newline-sensitive: counting E'\nBEGIN\n' substrings would
   -- read two adjacent BEGIN lines as one, since they share a newline.
   SELECT count(*) INTO openings FROM regexp_matches(definition,'^BEGIN$','gn');
   IF openings<>1 THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_BODY_DRIFT: % (% BEGIN lines)',spec->>'signature',openings;
   END IF;
   SELECT string_agg(DISTINCT used.name,',') INTO missing
     FROM (SELECT (regexp_matches(spec->>'sql','\m(p_[a-z0-9_]+)','g'))[1] AS name) used
     JOIN pg_proc procedure ON procedure.oid=target
    WHERE NOT used.name=ANY(COALESCE(procedure.proargnames,ARRAY[]::text[]));
   IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_BODY_DRIFT: % (no parameter %)',spec->>'signature',missing;
   END IF;
   injection:=' -- '||(spec->>'marker')||E'\n'||(spec->>'sql');
   definition:=regexp_replace(definition,E'\nBEGIN\n',E'\nBEGIN\n'||injection);
   EXECUTE definition;
   IF position(spec->>'marker' IN pg_get_functiondef(target))=0 THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_BODY_DRIFT: % (marker did not land)',spec->>'signature';
   END IF;
  END IF;
 END LOOP;
END
$d11_writer_reclosure$;

REVOKE ALL ON FUNCTION public.mark_phase1_storage_object_purged_v1(
    UUID,TEXT,UUID,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.mark_phase1_storage_object_purged_v1(
    UUID,TEXT,UUID,TEXT,TEXT,TEXT,TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_phase1_purge_inventory_v4(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) TO service_role;

COMMIT;
