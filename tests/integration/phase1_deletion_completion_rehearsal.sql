\set ON_ERROR_STOP on

-- Disposable-only rehearsal. The surrounding transaction is always rolled
-- back; no production record or provider object is touched.
BEGIN;

\set principal_id '70000000-0000-0000-0000-000000000001'
\set purge_unknown '70000000-0000-0000-0000-000000000002'
\set purge_clean '70000000-0000-0000-0000-000000000003'
\set purge_duplicate '70000000-0000-0000-0000-000000000004'
\set legal_id '70000000-0000-0000-0000-000000000005'
\set policy_id '70000000-0000-0000-0000-000000000006'
\set receipt_id '70000000-0000-0000-0000-000000000007'
\set snapshot_id '70000000-0000-0000-0000-000000000008'
\set project_id '70000000-0000-0000-0000-000000000009'
\set attempt_id '70000000-0000-0000-0000-00000000000a'
\set audio_id '70000000-0000-0000-0000-00000000000b'
\set purge_audio '70000000-0000-0000-0000-00000000000c'

INSERT INTO public.owner_principals (id, guest_secret_hash)
VALUES ('70000000-0000-0000-0000-000000000001'::uuid, repeat('7', 64))
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.data_purge_requests (
    id, acquisition_principal_id, trigger_kind, idempotency_key
) VALUES
    ('70000000-0000-0000-0000-000000000002'::uuid,
     '70000000-0000-0000-0000-000000000001'::uuid,
     'lawful_deletion', 'purge-unknown'),
    ('70000000-0000-0000-0000-000000000003'::uuid,
     '70000000-0000-0000-0000-000000000001'::uuid,
     'lawful_deletion', 'purge-clean'),
    ('70000000-0000-0000-0000-000000000004'::uuid,
     '70000000-0000-0000-0000-000000000001'::uuid,
     'lawful_deletion', 'purge-duplicate'),
    ('70000000-0000-0000-0000-00000000000c'::uuid,
     '70000000-0000-0000-0000-000000000001'::uuid,
     'lawful_deletion', 'purge-audio')
ON CONFLICT (id) DO NOTHING;

-- Canonical audio acquisition remains immutable. Byte erasure is proven by a
-- separate append-only event whose coordinates and checksum must match.
INSERT INTO public.projects (
    id, owner_principal_id, display_name
) VALUES (
    '70000000-0000-0000-0000-000000000009'::uuid,
    '70000000-0000-0000-0000-000000000001'::uuid,
    'Synthetic purge project'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO public.processing_policy_versions (
    id, version, status, terms_version, terms_copy, terms_copy_sha256,
    privacy_version, privacy_copy, privacy_copy_sha256, ai_notice_version,
    ai_notice_copy, ai_notice_copy_sha256, agreement_copy,
    agreement_copy_sha256, allowed_countries, created_by
) VALUES (
    '70000000-0000-0000-0000-000000000006'::uuid,
    'synthetic-deletion-policy-v1', 'draft', 'terms-v1', 'terms',
    repeat('1', 64), 'privacy-v1', 'privacy', repeat('2', 64),
    'ai-v1', 'ai', repeat('3', 64), 'agreement', repeat('4', 64),
    ARRAY['PL'], 'synthetic-rehearsal'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO public.processing_authorization_receipts (
    id, acquisition_principal_id, policy_id, idempotency_key,
    explicit_action, age_18_attested, country_of_residence, locale,
    client_version, accepted_at, evidence_sha256
) VALUES (
    '70000000-0000-0000-0000-000000000007'::uuid,
    '70000000-0000-0000-0000-000000000001'::uuid,
    '70000000-0000-0000-0000-000000000006'::uuid,
    'synthetic-deletion-receipt', 'agree_and_continue', true, 'PL', 'en',
    'synthetic', now(), repeat('5', 64)
) ON CONFLICT (id) DO NOTHING;

INSERT INTO public.processing_authorization_snapshots (
    id, acquisition_principal_id, receipt_id, policy_id, purpose_id,
    operation_kind, source_recording_id, authority_evidence_sha256
) VALUES (
    '70000000-0000-0000-0000-000000000008'::uuid,
    '70000000-0000-0000-0000-000000000001'::uuid,
    '70000000-0000-0000-0000-000000000007'::uuid,
    '70000000-0000-0000-0000-000000000006'::uuid,
    'recording_voice_processing', 'recording_upload',
    '70000000-0000-0000-0000-00000000000a'::uuid, repeat('6', 64)
) ON CONFLICT (id) DO NOTHING;

INSERT INTO public.processing_recording_attempts (
    id, acquisition_principal_id, project_id, recording_id,
    upload_idempotency_key, authorization_snapshot_id
) VALUES (
    '70000000-0000-0000-0000-00000000000a'::uuid,
    '70000000-0000-0000-0000-000000000001'::uuid,
    '70000000-0000-0000-0000-000000000009'::uuid,
    '70000000-0000-0000-0000-00000000000a'::uuid,
    'synthetic-audio-attempt',
    '70000000-0000-0000-0000-000000000008'::uuid
) ON CONFLICT (id) DO NOTHING;

INSERT INTO public.processing_audio_objects (
    id, acquisition_principal_id, recording_attempt_id, storage_provider,
    bucket, object_key, byte_size, content_type, exact_bytes_sha256,
    verified_at, verification_method
) VALUES (
    '70000000-0000-0000-0000-00000000000b'::uuid,
    '70000000-0000-0000-0000-000000000001'::uuid,
    '70000000-0000-0000-0000-00000000000a'::uuid,
    'r2', 'synthetic-recordings', 'principal/take.wav', 21,
    'audio/wav', repeat('7', 64), now(), 'read_after_write_sha256'
) ON CONFLICT (id) DO NOTHING;

SELECT public.mark_phase1_storage_object_purged_v1(
    '70000000-0000-0000-0000-00000000000c'::uuid,
    'processing_audio_objects',
    '70000000-0000-0000-0000-00000000000b'::uuid,
    'r2', 'synthetic-recordings', 'principal/take.wav', repeat('7', 64)
);
-- Exact replay is idempotent and does not rewrite acquisition provenance.
SELECT public.mark_phase1_storage_object_purged_v1(
    '70000000-0000-0000-0000-00000000000c'::uuid,
    'processing_audio_objects',
    '70000000-0000-0000-0000-00000000000b'::uuid,
    'r2', 'synthetic-recordings', 'principal/take.wav', repeat('7', 64)
);

DO $$
BEGIN
    IF (SELECT count(*) FROM public.processing_audio_object_deletion_events
         WHERE audio_object_id =
               '70000000-0000-0000-0000-00000000000b'::uuid) <> 1
    THEN RAISE EXCEPTION 'audio deletion event was not exactly-once'; END IF;
    IF (SELECT deleted_at FROM public.processing_audio_objects
         WHERE id = '70000000-0000-0000-0000-00000000000b'::uuid) IS NOT NULL
    THEN RAISE EXCEPTION 'acquisition metadata was rewritten'; END IF;
    BEGIN
        PERFORM public.mark_phase1_storage_object_purged_v1(
            '70000000-0000-0000-0000-00000000000c'::uuid,
            'processing_audio_objects',
            '70000000-0000-0000-0000-00000000000b'::uuid,
            'r2', 'wrong-bucket', 'principal/take.wav', repeat('7', 64)
        );
        RAISE EXCEPTION 'PURGE_OBJECT_METADATA_MISMATCH missing';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%PURGE_OBJECT_METADATA_MISMATCH%' THEN RAISE; END IF;
    END;
END;
$$;

CREATE TABLE public.purge_unclassified_fixture (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL
);

DO $$
DECLARE allowlist TEXT[]; audit JSONB;
BEGIN
    SELECT COALESCE(array_agg(candidate.table_name ORDER BY candidate.table_name),
                    '{}'::text[])
      INTO allowlist
      FROM (
        SELECT DISTINCT c.table_name
          FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema AND t.table_name = c.table_name
         WHERE c.table_schema = 'public' AND t.table_type = 'BASE TABLE'
           AND c.column_name IN (
               'acquisition_principal_id', 'owner_principal_id', 'owner_user_id',
               'user_id', 'claimed_user_id', 'student_user_id', 'project_id',
               'arc_id', 'session_id', 'recording_session_id',
               'take_session_id', 'recording_id', 'snippet_id',
               'source_owner_principal_id', 'target_owner_principal_id',
               'processing_job_id', 'permit_id'
           )
           AND c.table_name <> 'purge_unclassified_fixture'
      ) candidate;
    audit := public.audit_phase1_purge_catalog_v1(allowlist);
    IF NOT (audit->'unknown_relations' ? 'purge_unclassified_fixture') THEN
        RAISE EXCEPTION 'UNCLASSIFIED_SUBJECT_RELATION was not detected: %', audit;
    END IF;
END;
$$;

SELECT public.freeze_phase1_purge_inventory_v2(
    '70000000-0000-0000-0000-000000000002'::uuid,
    'phase1-purge-resolver-v2', repeat('a', 64),
    jsonb_build_object('principal_ids', jsonb_build_array(
        '70000000-0000-0000-0000-000000000001'::uuid
    )),
    jsonb_build_array(jsonb_build_object(
        'target_kind', 'database_row', 'target_ref', 'synthetic:unknown',
        'initial_match_count', 0, 'metadata', '{}'::jsonb
    )), repeat('b', 64), ARRAY['purge_unclassified_fixture']
);

DO $$
DECLARE result JSONB;
BEGIN
    result := public.finalize_phase1_purge_v2(
        '70000000-0000-0000-0000-000000000002'::uuid, repeat('c', 64)
    );
    IF result->>'state' <> 'review_required'
       OR result->>'reason_code' <> 'UNCLASSIFIED_SUBJECT_RELATION'
    THEN RAISE EXCEPTION 'unknown catalog did not fail closed: %', result; END IF;
END;
$$;

DROP TABLE public.purge_unclassified_fixture;

SELECT public.freeze_phase1_purge_inventory_v2(
    '70000000-0000-0000-0000-000000000003'::uuid,
    'phase1-purge-resolver-v2', repeat('d', 64),
    jsonb_build_object('principal_ids', jsonb_build_array(
        '70000000-0000-0000-0000-000000000001'::uuid
    )),
    jsonb_build_array(jsonb_build_object(
        'target_kind', 'database_row', 'target_ref', 'synthetic:clean',
        'initial_match_count', 1,
        'metadata', jsonb_build_object('dependency_code', 'synthetic')
    )), repeat('e', 64), ARRAY[]::text[]
);

-- Exact replay is idempotent and uses server-computed JSONB hashes.
SELECT public.freeze_phase1_purge_inventory_v2(
    '70000000-0000-0000-0000-000000000003'::uuid,
    'phase1-purge-resolver-v2', repeat('d', 64),
    jsonb_build_object('principal_ids', jsonb_build_array(
        '70000000-0000-0000-0000-000000000001'::uuid
    )),
    jsonb_build_array(jsonb_build_object(
        'target_kind', 'database_row', 'target_ref', 'synthetic:clean',
        'initial_match_count', 1,
        'metadata', jsonb_build_object('dependency_code', 'synthetic')
    )), repeat('e', 64), ARRAY[]::text[]
);

DO $$
BEGIN
    BEGIN
        PERFORM public.freeze_phase1_purge_inventory_v2(
            '70000000-0000-0000-0000-000000000003'::uuid,
            'phase1-purge-resolver-v2', repeat('d', 64),
            jsonb_build_object('principal_ids', jsonb_build_array(
                '70000000-0000-0000-0000-000000000001'::uuid
            )),
            jsonb_build_array(jsonb_build_object(
                'target_kind', 'database_row', 'target_ref', 'synthetic:changed',
                'initial_match_count', 1, 'metadata', '{}'::jsonb
            )), repeat('e', 64), ARRAY[]::text[]
        );
        RAISE EXCEPTION 'PURGE_INVENTORY_REPLAY_CONFLICT was not raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%PURGE_INVENTORY_REPLAY_CONFLICT%' THEN RAISE; END IF;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        PERFORM public.freeze_phase1_purge_inventory_v2(
            '70000000-0000-0000-0000-000000000004'::uuid,
            'phase1-purge-resolver-v2', repeat('f', 64),
            jsonb_build_object('principal_ids', jsonb_build_array(
                '70000000-0000-0000-0000-000000000001'::uuid
            )),
            jsonb_build_array(
                jsonb_build_object('target_kind', 'database_row',
                                   'target_ref', 'synthetic:duplicate'),
                jsonb_build_object('target_kind', 'database_row',
                                   'target_ref', 'synthetic:duplicate')
            ), repeat('1', 64), ARRAY[]::text[]
        );
        RAISE EXCEPTION 'PURGE_MANIFEST_DUPLICATE_TARGET was not raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%PURGE_MANIFEST_DUPLICATE_TARGET%' THEN RAISE; END IF;
    END;
END;
$$;

DO $$
DECLARE target_id UUID;
BEGIN
    SELECT id INTO target_id FROM public.data_purge_targets
     WHERE purge_request_id = '70000000-0000-0000-0000-000000000003'::uuid
       AND target_ref = 'synthetic:clean';
    BEGIN
        PERFORM public.resolve_phase1_purge_target_v2(
            target_id, 'deleted', repeat('2', 64), 1
        );
        RAISE EXCEPTION 'PURGE_TARGET_STILL_PRESENT was not raised';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%PURGE_TARGET_STILL_PRESENT%' THEN RAISE; END IF;
    END;
    PERFORM public.resolve_phase1_purge_target_v2(
        target_id, 'deleted', repeat('3', 64), 0
    );
    IF EXISTS (
        SELECT 1 FROM public.data_purge_targets
         WHERE id = target_id AND remaining_match_count <> 0
    ) THEN RAISE EXCEPTION 'remaining_match_count was not sealed'; END IF;
END;
$$;

DO $$
DECLARE result JSONB;
BEGIN
    result := public.finalize_phase1_purge_v2(
        '70000000-0000-0000-0000-000000000003'::uuid, repeat('4', 64)
    );
    IF result->>'state' <> 'done' THEN
        RAISE EXCEPTION 'clean purge did not finalize: %', result;
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.data_purge_targets
         WHERE purge_request_id =
               '70000000-0000-0000-0000-000000000003'::uuid
           AND state IN ('pending', 'failed', 'unknown')
    ) THEN RAISE EXCEPTION 'unresolved target survived completion'; END IF;
END;
$$;

INSERT INTO public.processing_legal_artifacts (
    id, artifact_kind, version, approving_authority, approved_at,
    object_key, sha256
) VALUES (
    '70000000-0000-0000-0000-000000000005'::uuid,
    'processor_inventory', 'synthetic-delete-v1',
    'synthetic-reviewer', now(), 'synthetic/legal.json', repeat('5', 64)
);

SET LOCAL ROLE service_role;
SELECT public.register_phase1_provider_deletion_contract_v1(
    jsonb_build_object(
        'provider', 'openai', 'operation_kind', 'transcription',
        'contract_version', 'synthetic-v1',
        'resolution_mode', 'no_durable_provider_object',
        'legal_artifact_id',
        '70000000-0000-0000-0000-000000000005'::uuid,
        'evidence_sha256', repeat('6', 64),
        'reviewed_at', now()::text
    ), repeat('7', 64)
);
RESET ROLE;

DO $$
BEGIN
    IF has_table_privilege('service_role',
        'public.processing_provider_deletion_contracts', 'INSERT')
    THEN RAISE EXCEPTION 'service role can bypass provider contract RPC'; END IF;
    IF NOT has_table_privilege('service_role',
        'public.processing_provider_deletion_contracts', 'SELECT')
    THEN RAISE EXCEPTION 'service role cannot monitor provider contracts'; END IF;
END;
$$;

SET LOCAL ROLE service_role;
SELECT public.retire_phase1_provider_deletion_contract_v1(
    (
        SELECT id FROM public.processing_provider_deletion_contracts
         WHERE provider = 'openai' AND operation_kind = 'transcription'
           AND contract_version = 'synthetic-v1'
    ), repeat('8', 64)
);
RESET ROLE;

DO $$
BEGIN
    BEGIN
        PERFORM public.register_phase1_provider_deletion_contract_v1(
            jsonb_build_object(
                'provider', 'openai', 'operation_kind', 'transcription',
                'contract_version', 'synthetic-v1',
                'resolution_mode', 'api_delete',
                'provider_object_prefix', 'file-',
                'legal_artifact_id',
                '70000000-0000-0000-0000-000000000005'::uuid,
                'evidence_sha256', repeat('6', 64),
                'reviewed_at', now()::text
            ), repeat('7', 64)
        );
        RAISE EXCEPTION 'PROVIDER_DELETION_CONTRACT_REPLAY_CONFLICT missing';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%PROVIDER_DELETION_CONTRACT_REPLAY_CONFLICT%'
        THEN RAISE; END IF;
    END;
END;
$$;

DO $$
BEGIN
    BEGIN
        UPDATE public.data_purge_inventory_manifests SET resolver_version = 'x'
         WHERE purge_request_id =
               '70000000-0000-0000-0000-000000000003'::uuid;
        RAISE EXCEPTION 'Phase-1 evidence is append-only was not enforced';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%Phase-1 evidence is append-only%' THEN RAISE; END IF;
    END;
END;
$$;

ROLLBACK;
