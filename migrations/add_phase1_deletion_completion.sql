-- 0312 · Phase-1 deletion completion.
--
-- This migration adds the immutable inventory seal, provider-deletion
-- contracts and fail-closed catalog/finalization RPCs used by the deletion
-- orchestrator.  It does not seed a provider contract, retention rule or
-- legal conclusion, and it performs no deletion by itself.

BEGIN;

ALTER TABLE public.data_purge_targets
    ADD COLUMN IF NOT EXISTS initial_match_count INTEGER NOT NULL DEFAULT 0
        CHECK (initial_match_count >= 0),
    ADD COLUMN IF NOT EXISTS remaining_match_count INTEGER NULL
        CHECK (remaining_match_count IS NULL OR remaining_match_count >= 0),
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE TABLE IF NOT EXISTS public.data_purge_inventory_manifests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    purge_request_id UUID NOT NULL UNIQUE REFERENCES
        public.data_purge_requests(id) ON DELETE RESTRICT,
    resolver_version TEXT NOT NULL,
    dependency_manifest_sha256 TEXT NOT NULL CHECK (
        dependency_manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
    subject_graph JSONB NOT NULL,
    subject_graph_sha256 TEXT NOT NULL CHECK (
        subject_graph_sha256 ~ '^[0-9a-f]{64}$'
    ),
    target_manifest_sha256 TEXT NOT NULL CHECK (
        target_manifest_sha256 ~ '^[0-9a-f]{64}$'
    ),
    catalog_sha256 TEXT NOT NULL CHECK (catalog_sha256 ~ '^[0-9a-f]{64}$'),
    catalog_unknown_relations TEXT[] NOT NULL DEFAULT '{}'::text[],
    frozen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (jsonb_typeof(subject_graph) = 'object')
);

-- Canonical audio intake rows are append-only. Verified byte deletion is a
-- new immutable fact, never an UPDATE that rewrites acquisition provenance.
CREATE TABLE IF NOT EXISTS public.processing_audio_object_deletion_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    audio_object_id UUID NOT NULL UNIQUE REFERENCES
        public.processing_audio_objects(id) ON DELETE RESTRICT,
    purge_request_id UUID NOT NULL REFERENCES
        public.data_purge_requests(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    storage_provider TEXT NOT NULL,
    bucket TEXT NOT NULL,
    object_key TEXT NOT NULL,
    exact_bytes_sha256 TEXT NOT NULL CHECK (
        exact_bytes_sha256 ~ '^[0-9a-f]{64}$'
    ),
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    verified_deleted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- A provider operation can be resolved only when Product/legal and
-- Engineering have registered an exact reviewed deletion/retention contract.
-- Nothing is seeded here: absence must keep the purge in review_required.
CREATE TABLE IF NOT EXISTS public.processing_provider_deletion_contracts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider TEXT NOT NULL,
    operation_kind TEXT NOT NULL,
    contract_version TEXT NOT NULL,
    resolution_mode TEXT NOT NULL CHECK (resolution_mode IN (
        'no_durable_provider_object', 'api_delete', 'contractual_retention'
    )),
    provider_object_prefix TEXT,
    retention_rule_id UUID REFERENCES public.data_retention_rules(id)
        ON DELETE RESTRICT,
    legal_artifact_id UUID NOT NULL REFERENCES
        public.processing_legal_artifacts(id) ON DELETE RESTRICT,
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    reviewed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (provider, operation_kind, contract_version),
    CONSTRAINT provider_deletion_mode_fields CHECK (
        (resolution_mode = 'contractual_retention' AND retention_rule_id IS NOT NULL)
        OR (resolution_mode <> 'contractual_retention' AND retention_rule_id IS NULL)
    )
);

-- Activation and retirement are append-only facts. Keeping them separate
-- lets a later reviewed contract supersede an older one without mutating the
-- evidence that justified either contract.
CREATE TABLE IF NOT EXISTS public.processing_provider_deletion_contract_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_sequence BIGINT GENERATED ALWAYS AS IDENTITY UNIQUE,
    contract_id UUID NOT NULL REFERENCES
        public.processing_provider_deletion_contracts(id) ON DELETE RESTRICT,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('activated', 'retired')),
    evidence_sha256 TEXT NOT NULL CHECK (evidence_sha256 ~ '^[0-9a-f]{64}$'),
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (contract_id, event_kind)
);
ALTER TABLE public.processing_provider_deletion_contract_events
    ADD COLUMN IF NOT EXISTS event_sequence BIGINT GENERATED ALWAYS AS IDENTITY;
CREATE UNIQUE INDEX IF NOT EXISTS provider_deletion_contract_event_sequence_idx
    ON public.processing_provider_deletion_contract_events (event_sequence);

-- The service role has read-only table access. This RPC is the only reviewed
-- way to register and activate an immutable provider-deletion contract.
CREATE OR REPLACE FUNCTION public.register_phase1_provider_deletion_contract_v1(
    p_contract JSONB,
    p_activation_evidence_sha256 TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE existing public.processing_provider_deletion_contracts;
        activation public.processing_provider_deletion_contract_events;
        provider_value TEXT; operation_value TEXT; version_value TEXT;
        mode_value TEXT; prefix_value TEXT; contract_hash TEXT;
        legal_id UUID; retention_id UUID; reviewed_value TIMESTAMPTZ;
BEGIN
    IF jsonb_typeof(p_contract) <> 'object'
    THEN RAISE EXCEPTION 'PROVIDER_DELETION_CONTRACT_REQUIRED'; END IF;
    provider_value := btrim(COALESCE(p_contract->>'provider', ''));
    operation_value := btrim(COALESCE(p_contract->>'operation_kind', ''));
    version_value := btrim(COALESCE(p_contract->>'contract_version', ''));
    mode_value := btrim(COALESCE(p_contract->>'resolution_mode', ''));
    prefix_value := NULLIF(p_contract->>'provider_object_prefix', '');
    contract_hash := lower(COALESCE(p_contract->>'evidence_sha256', ''));
    legal_id := NULLIF(p_contract->>'legal_artifact_id', '')::uuid;
    retention_id := NULLIF(p_contract->>'retention_rule_id', '')::uuid;
    reviewed_value := NULLIF(p_contract->>'reviewed_at', '')::timestamptz;
    IF provider_value = '' OR operation_value = '' OR version_value = ''
       OR mode_value NOT IN (
           'no_durable_provider_object', 'api_delete', 'contractual_retention'
       ) OR contract_hash !~ '^[0-9a-f]{64}$'
       OR p_activation_evidence_sha256 !~ '^[0-9a-f]{64}$'
       OR legal_id IS NULL OR reviewed_value IS NULL
    THEN RAISE EXCEPTION 'PROVIDER_DELETION_CONTRACT_INVALID'; END IF;
    IF mode_value = 'api_delete' AND prefix_value IS NULL
    THEN RAISE EXCEPTION 'PROVIDER_OBJECT_PREFIX_REQUIRED'; END IF;
    IF (mode_value = 'contractual_retention') <> (retention_id IS NOT NULL)
    THEN RAISE EXCEPTION 'PROVIDER_RETENTION_RULE_INVALID'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_legal_artifacts WHERE id = legal_id
    ) THEN RAISE EXCEPTION 'PROVIDER_LEGAL_ARTIFACT_NOT_FOUND'; END IF;
    IF retention_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.data_retention_rules
         WHERE id = retention_id AND active
    ) THEN RAISE EXCEPTION 'PROVIDER_RETENTION_RULE_INACTIVE'; END IF;

    PERFORM pg_advisory_xact_lock(hashtext(concat_ws(
        ':', 'phase1-provider-deletion-contract', provider_value,
        operation_value, version_value
    )));
    SELECT * INTO existing
      FROM public.processing_provider_deletion_contracts
     WHERE provider = provider_value AND operation_kind = operation_value
       AND contract_version = version_value;
    IF existing.id IS NULL THEN
        INSERT INTO public.processing_provider_deletion_contracts (
            provider, operation_kind, contract_version, resolution_mode,
            provider_object_prefix, retention_rule_id, legal_artifact_id,
            evidence_sha256, reviewed_at
        ) VALUES (
            provider_value, operation_value, version_value, mode_value,
            prefix_value, retention_id, legal_id, contract_hash, reviewed_value
        ) RETURNING * INTO existing;
    ELSIF existing.resolution_mode <> mode_value
       OR existing.provider_object_prefix IS DISTINCT FROM prefix_value
       OR existing.retention_rule_id IS DISTINCT FROM retention_id
       OR existing.legal_artifact_id <> legal_id
       OR existing.evidence_sha256 <> contract_hash
       OR existing.reviewed_at <> reviewed_value
    THEN RAISE EXCEPTION 'PROVIDER_DELETION_CONTRACT_REPLAY_CONFLICT'; END IF;

    INSERT INTO public.processing_provider_deletion_contract_events (
        contract_id, event_kind, evidence_sha256
    ) VALUES (
        existing.id, 'activated', lower(p_activation_evidence_sha256)
    ) ON CONFLICT (contract_id, event_kind) DO NOTHING;
    SELECT * INTO activation
      FROM public.processing_provider_deletion_contract_events
     WHERE contract_id = existing.id AND event_kind = 'activated';
    IF activation.evidence_sha256 <> lower(p_activation_evidence_sha256)
    THEN RAISE EXCEPTION 'PROVIDER_DELETION_ACTIVATION_REPLAY_CONFLICT'; END IF;
    RETURN jsonb_build_object(
        'contract_id', existing.id, 'provider', existing.provider,
        'operation_kind', existing.operation_kind,
        'contract_version', existing.contract_version,
        'resolution_mode', existing.resolution_mode, 'active', true
    );
END;
$$;
REVOKE ALL ON FUNCTION public.register_phase1_provider_deletion_contract_v1(
    JSONB,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_phase1_provider_deletion_contract_v1(
    JSONB,TEXT
) TO service_role;

CREATE OR REPLACE FUNCTION public.retire_phase1_provider_deletion_contract_v1(
    p_contract_id UUID,
    p_retirement_evidence_sha256 TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE contract public.processing_provider_deletion_contracts;
        retirement public.processing_provider_deletion_contract_events;
BEGIN
    IF p_retirement_evidence_sha256 !~ '^[0-9a-f]{64}$'
    THEN RAISE EXCEPTION 'PROVIDER_RETIREMENT_EVIDENCE_INVALID'; END IF;
    SELECT * INTO contract FROM public.processing_provider_deletion_contracts
     WHERE id = p_contract_id FOR SHARE;
    IF contract.id IS NULL
    THEN RAISE EXCEPTION 'PROVIDER_DELETION_CONTRACT_NOT_FOUND'; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.processing_provider_deletion_contract_events
         WHERE contract_id = contract.id AND event_kind = 'activated'
    ) THEN RAISE EXCEPTION 'PROVIDER_DELETION_CONTRACT_NOT_ACTIVE'; END IF;
    INSERT INTO public.processing_provider_deletion_contract_events (
        contract_id, event_kind, evidence_sha256
    ) VALUES (
        contract.id, 'retired', lower(p_retirement_evidence_sha256)
    ) ON CONFLICT (contract_id, event_kind) DO NOTHING;
    SELECT * INTO retirement
      FROM public.processing_provider_deletion_contract_events
     WHERE contract_id = contract.id AND event_kind = 'retired';
    IF retirement.evidence_sha256 <> lower(p_retirement_evidence_sha256)
    THEN RAISE EXCEPTION 'PROVIDER_DELETION_RETIREMENT_REPLAY_CONFLICT'; END IF;
    RETURN jsonb_build_object(
        'contract_id', contract.id, 'provider', contract.provider,
        'operation_kind', contract.operation_kind,
        'contract_version', contract.contract_version, 'active', false
    );
END;
$$;
REVOKE ALL ON FUNCTION public.retire_phase1_provider_deletion_contract_v1(
    UUID,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.retire_phase1_provider_deletion_contract_v1(
    UUID,TEXT
) TO service_role;

-- Return every public base table carrying a subject-lineage coordinate that
-- the checked-in dependency manifest has not classified.  New tables fail
-- closed without granting the caller arbitrary catalog or row access.
CREATE OR REPLACE FUNCTION public.audit_phase1_purge_catalog_v1(
    p_allowlisted_relations TEXT[]
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE all_relations TEXT[]; unknown_relations TEXT[]; catalog_hash TEXT;
BEGIN
    IF p_allowlisted_relations IS NULL THEN
        RAISE EXCEPTION 'PURGE_ALLOWLIST_REQUIRED';
    END IF;
    SELECT COALESCE(array_agg(candidate.table_name ORDER BY candidate.table_name),
                    '{}'::text[])
      INTO all_relations
      FROM (
        SELECT DISTINCT column_name.table_name
          FROM information_schema.columns column_name
          JOIN information_schema.tables relation
            ON relation.table_schema = column_name.table_schema
           AND relation.table_name = column_name.table_name
         WHERE column_name.table_schema = 'public'
           AND relation.table_type = 'BASE TABLE'
           AND column_name.column_name IN (
               'acquisition_principal_id', 'owner_principal_id', 'owner_user_id',
               'user_id', 'claimed_user_id', 'student_user_id', 'project_id',
               'arc_id', 'session_id', 'recording_session_id',
               'take_session_id', 'recording_id', 'snippet_id',
               'source_owner_principal_id', 'target_owner_principal_id',
               'processing_job_id', 'permit_id'
           )
      ) candidate;
    SELECT COALESCE(array_agg(name ORDER BY name), '{}'::text[])
      INTO unknown_relations
      FROM unnest(all_relations) AS name
     WHERE NOT name = ANY(p_allowlisted_relations);
    catalog_hash := encode(extensions.digest(
        array_to_string(all_relations, E'\n'), 'sha256'
    ), 'hex');
    RETURN jsonb_build_object(
        'candidate_relations', to_jsonb(all_relations),
        'existing_allowlisted_relations', (
            SELECT COALESCE(jsonb_agg(name ORDER BY name), '[]'::jsonb)
              FROM unnest(p_allowlisted_relations) AS name
             WHERE to_regclass(format('public.%I', name)) IS NOT NULL
        ),
        'unknown_relations', to_jsonb(unknown_relations),
        'catalog_sha256', catalog_hash
    );
END;
$$;
REVOKE ALL ON FUNCTION public.audit_phase1_purge_catalog_v1(TEXT[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.audit_phase1_purge_catalog_v1(TEXT[])
    TO service_role;

-- Mark only the exact canonical metadata row after byte deletion succeeded.
-- The object coordinates and checksum are repeated deliberately: an ID alone
-- must not be enough to claim that a different object was erased.
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

-- Freeze the subject graph and every table/object/provider target together.
-- An exact replay is idempotent; a different replay is a hard conflict.
CREATE OR REPLACE FUNCTION public.freeze_phase1_purge_inventory_v2(
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
BEGIN
    SELECT * INTO req FROM public.data_purge_requests
     WHERE id = p_purge_request_id FOR UPDATE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    IF req.state = 'done' THEN RAISE EXCEPTION 'PURGE_ALREADY_FINALIZED'; END IF;
    IF jsonb_typeof(p_subject_graph) <> 'object'
       OR jsonb_typeof(p_targets) <> 'array'
       OR jsonb_array_length(p_targets) = 0
    THEN RAISE EXCEPTION 'PURGE_MANIFEST_INVALID'; END IF;
    IF EXISTS (
        SELECT 1 FROM jsonb_array_elements(p_targets) candidate
         GROUP BY COALESCE(candidate->>'target_kind', 'unknown'),
                  COALESCE(NULLIF(candidate->>'target_ref', ''), 'unresolved')
        HAVING count(*) > 1
    ) THEN RAISE EXCEPTION 'PURGE_MANIFEST_DUPLICATE_TARGET'; END IF;
    IF p_dependency_manifest_sha256 !~ '^[0-9a-f]{64}$'
       OR p_catalog_sha256 !~ '^[0-9a-f]{64}$'
    THEN RAISE EXCEPTION 'PURGE_MANIFEST_HASH_INVALID'; END IF;

    -- Seal the exact JSONB values that PostgreSQL persists. This avoids
    -- trusting a caller-side serializer to reproduce jsonb key ordering.
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
        IF kind NOT IN (
            'database_row', 'r2_object', 'supabase_object', 'transcript',
            'derived_feedback', 'processing_queue', 'provider_operation',
            'coach_packet', 'cache', 'dataset_lineage', 'model_lineage'
        ) THEN kind := 'unknown'; END IF;
        item_state := CASE WHEN kind = 'unknown' THEN 'unknown' ELSE 'pending' END;
        INSERT INTO public.data_purge_targets (
            purge_request_id, target_kind, target_ref, resolver_version,
            state, initial_match_count, metadata
        ) VALUES (
            p_purge_request_id, kind, ref, p_resolver_version, item_state,
            GREATEST(0, COALESCE((item->>'initial_match_count')::integer, 0)),
            COALESCE(item->'metadata', '{}'::jsonb)
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
REVOKE ALL ON FUNCTION public.freeze_phase1_purge_inventory_v2(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.freeze_phase1_purge_inventory_v2(
    UUID,TEXT,TEXT,JSONB,JSONB,TEXT,TEXT[]
) TO service_role;

CREATE OR REPLACE FUNCTION public.resolve_phase1_purge_target_v2(
    p_target_id UUID,
    p_state TEXT,
    p_evidence_sha256 TEXT,
    p_remaining_match_count INTEGER,
    p_last_error_code TEXT DEFAULT NULL,
    p_retention_rule_id UUID DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE target public.data_purge_targets;
BEGIN
    IF p_state NOT IN ('deleted', 'retained', 'failed', 'unknown', 'not_found')
    THEN RAISE EXCEPTION 'INVALID_PURGE_TARGET_STATE'; END IF;
    IF p_remaining_match_count IS NULL OR p_remaining_match_count < 0
    THEN RAISE EXCEPTION 'PURGE_REMAINING_COUNT_REQUIRED'; END IF;
    IF p_state IN ('deleted', 'not_found') AND p_remaining_match_count <> 0
    THEN RAISE EXCEPTION 'PURGE_TARGET_STILL_PRESENT'; END IF;
    IF p_state = 'retained' AND p_retention_rule_id IS NULL
    THEN RAISE EXCEPTION 'RETENTION_RULE_REQUIRED'; END IF;
    IF p_evidence_sha256 !~ '^[0-9a-f]{64}$'
    THEN RAISE EXCEPTION 'PURGE_EVIDENCE_HASH_INVALID'; END IF;

    UPDATE public.data_purge_targets
       SET state = p_state,
           evidence_sha256 = lower(p_evidence_sha256),
           remaining_match_count = p_remaining_match_count,
           last_error_code = p_last_error_code,
           retention_rule_id = p_retention_rule_id,
           resolved_at = now()
     WHERE id = p_target_id AND state IN ('pending', 'failed', 'unknown')
     RETURNING * INTO target;
    IF target.id IS NULL THEN RAISE EXCEPTION 'PURGE_TARGET_NOT_RESOLVABLE'; END IF;
    INSERT INTO public.data_purge_events (
        purge_request_id, target_id, event_kind, actor_kind,
        evidence_sha256, metadata
    ) VALUES (
        target.purge_request_id, target.id, 'target_' || p_state,
        'orchestrator', lower(p_evidence_sha256),
        jsonb_build_object(
            'error_code', p_last_error_code,
            'retention_rule_id', p_retention_rule_id,
            'initial_match_count', target.initial_match_count,
            'remaining_match_count', p_remaining_match_count
        )
    );
    RETURN jsonb_build_object(
        'target_id', target.id, 'state', target.state,
        'remaining_match_count', target.remaining_match_count
    );
END;
$$;
REVOKE ALL ON FUNCTION public.resolve_phase1_purge_target_v2(
    UUID,TEXT,TEXT,INTEGER,TEXT,UUID
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_purge_target_v2(
    UUID,TEXT,TEXT,INTEGER,TEXT,UUID
) TO service_role;

CREATE OR REPLACE FUNCTION public.finalize_phase1_purge_v2(
    p_purge_request_id UUID, p_evidence_sha256 TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE unresolved INTEGER; req public.data_purge_requests;
        manifest public.data_purge_inventory_manifests;
BEGIN
    SELECT * INTO req FROM public.data_purge_requests
     WHERE id = p_purge_request_id FOR UPDATE;
    IF req.id IS NULL THEN RAISE EXCEPTION 'PURGE_REQUEST_NOT_FOUND'; END IF;
    SELECT * INTO manifest FROM public.data_purge_inventory_manifests
     WHERE purge_request_id = req.id;
    IF manifest.id IS NULL THEN RAISE EXCEPTION 'PURGE_INVENTORY_NOT_SEALED'; END IF;
    IF cardinality(manifest.catalog_unknown_relations) <> 0 THEN
        UPDATE public.data_purge_requests SET state = 'review_required'
         WHERE id = req.id;
        RETURN jsonb_build_object(
            'purge_request_id', req.id, 'state', 'review_required',
            'reason_code', 'UNCLASSIFIED_SUBJECT_RELATION'
        );
    END IF;
    SELECT count(*) INTO unresolved FROM public.data_purge_targets
     WHERE purge_request_id = req.id
       AND (
           state IN ('pending', 'failed', 'unknown')
           OR (state IN ('deleted', 'not_found')
               AND COALESCE(remaining_match_count, 1) <> 0)
       );
    IF unresolved > 0 THEN
        UPDATE public.data_purge_requests SET state = 'review_required'
         WHERE id = req.id;
        RETURN jsonb_build_object(
            'purge_request_id', req.id, 'state', 'review_required',
            'unresolved_target_count', unresolved
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.data_purge_targets WHERE purge_request_id = req.id
    ) THEN RAISE EXCEPTION 'PURGE_INVENTORY_EMPTY'; END IF;
    UPDATE public.data_purge_requests SET state = 'done', completed_at = now()
     WHERE id = req.id;
    INSERT INTO public.data_purge_events (
        purge_request_id, event_kind, actor_kind, evidence_sha256, metadata
    ) VALUES (
        req.id, 'completed', 'orchestrator', lower(p_evidence_sha256),
        jsonb_build_object(
            'resolver_version', manifest.resolver_version,
            'inventory_sha256', manifest.target_manifest_sha256,
            'catalog_sha256', manifest.catalog_sha256
        )
    );
    RETURN jsonb_build_object('purge_request_id', req.id, 'state', 'done');
END;
$$;
REVOKE ALL ON FUNCTION public.finalize_phase1_purge_v2(UUID,TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_phase1_purge_v2(UUID,TEXT)
    TO service_role;

-- Keep these statements explicit. Besides being easier to audit, the security
-- gate verifies that every newly created public table enables RLS in the same
-- migration without having to execute dynamic SQL.
ALTER TABLE public.data_purge_inventory_manifests ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_audio_object_deletion_events
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_provider_deletion_contracts
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_provider_deletion_contract_events
    ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON public.data_purge_inventory_manifests
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.processing_audio_object_deletion_events
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.processing_provider_deletion_contracts
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON public.processing_provider_deletion_contract_events
    FROM PUBLIC, anon, authenticated, service_role;

GRANT SELECT ON public.data_purge_inventory_manifests TO service_role;
GRANT SELECT ON public.processing_audio_object_deletion_events TO service_role;
GRANT SELECT ON public.processing_provider_deletion_contracts TO service_role;
GRANT SELECT ON public.processing_provider_deletion_contract_events
    TO service_role;

DROP TRIGGER IF EXISTS data_purge_inventory_manifests_immutable
    ON public.data_purge_inventory_manifests;
CREATE TRIGGER data_purge_inventory_manifests_immutable
    BEFORE UPDATE OR DELETE ON public.data_purge_inventory_manifests
    FOR EACH ROW EXECUTE FUNCTION public.reject_phase1_immutable_mutation();

DROP TRIGGER IF EXISTS processing_audio_object_deletion_events_immutable
    ON public.processing_audio_object_deletion_events;
CREATE TRIGGER processing_audio_object_deletion_events_immutable
    BEFORE UPDATE OR DELETE ON public.processing_audio_object_deletion_events
    FOR EACH ROW EXECUTE FUNCTION public.reject_phase1_immutable_mutation();

DROP TRIGGER IF EXISTS processing_provider_deletion_contracts_immutable
    ON public.processing_provider_deletion_contracts;
CREATE TRIGGER processing_provider_deletion_contracts_immutable
    BEFORE UPDATE OR DELETE ON public.processing_provider_deletion_contracts
    FOR EACH ROW EXECUTE FUNCTION public.reject_phase1_immutable_mutation();

DROP TRIGGER IF EXISTS processing_provider_deletion_contract_events_immutable
    ON public.processing_provider_deletion_contract_events;
CREATE TRIGGER processing_provider_deletion_contract_events_immutable
    BEFORE UPDATE OR DELETE ON public.processing_provider_deletion_contract_events
    FOR EACH ROW EXECUTE FUNCTION public.reject_phase1_immutable_mutation();

COMMIT;
