\set ON_ERROR_STOP on

BEGIN;

\set principal_id '10000000-0000-0000-0000-000000000001'
\set project_id   '20000000-0000-0000-0000-000000000001'
\set attempt_id   '30000000-0000-0000-0000-000000000001'
\set recording_id '40000000-0000-0000-0000-000000000001'
\set audio_sha 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
\set object_sha 'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
\set evidence_sha 'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc'

INSERT INTO public.owner_principals (id, guest_secret_hash)
VALUES (:'principal_id', repeat('d', 64));
INSERT INTO public.projects (id, owner_principal_id)
VALUES (:'project_id', :'principal_id');

SELECT encode(extensions.digest('Terms rehearsal', 'sha256'), 'hex')
           AS terms_hash,
       encode(extensions.digest('Privacy rehearsal', 'sha256'), 'hex')
           AS privacy_hash,
       encode(extensions.digest('AI notice rehearsal', 'sha256'), 'hex')
           AS ai_hash,
       encode(extensions.digest('I am 18+ and accept the rehearsal policy.',
                                'sha256'), 'hex') AS agreement_hash
\gset

SET ROLE service_role;

DO $$
DECLARE status JSONB;
BEGIN
    status := public.get_phase1_processing_authorization_v1(
        '10000000-0000-0000-0000-000000000001'::uuid
    );
    IF COALESCE((status->>'authorized')::boolean, false) THEN
        RAISE EXCEPTION 'passive authorization check created acceptance';
    END IF;
END;
$$;

SELECT public.register_phase1_policy_v1(
    jsonb_build_object(
        'version', 'phase1-rehearsal-v1',
        'terms_version', 'terms-r1', 'terms_copy', 'Terms rehearsal',
        'terms_copy_sha256', :'terms_hash',
        'privacy_version', 'privacy-r1', 'privacy_copy', 'Privacy rehearsal',
        'privacy_copy_sha256', :'privacy_hash',
        'ai_notice_version', 'ai-r1', 'ai_notice_copy', 'AI notice rehearsal',
        'ai_notice_copy_sha256', :'ai_hash',
        'agreement_copy', 'I am 18+ and accept the rehearsal policy.',
        'agreement_copy_sha256', :'agreement_hash',
        'allowed_countries', jsonb_build_array('pl', 'fr')
    ),
    jsonb_build_object(
        'artifact_kind', 'product_legal_approval', 'version', 'legal-r1',
        'approving_authority', 'rehearsal-only',
        'approved_at', '2026-08-29T10:00:00Z',
        'object_key', 'rehearsal/legal-r1', 'sha256', repeat('1', 64),
        'metadata', '{}'::jsonb
    ),
    jsonb_build_object(
        'artifact_kind', 'power_score_classification', 'version', 'power-r1',
        'approving_authority', 'rehearsal-only',
        'approved_at', '2026-08-29T10:00:00Z',
        'object_key', 'rehearsal/power-r1', 'sha256', repeat('2', 64),
        'metadata', jsonb_build_object(
            'biometric_identification', false,
            'sex_gender_inference', false,
            'emotion_intention_inference', false,
            'pipeline_version', 'voice-confidence-universal-v3'
        )
    ),
    jsonb_build_object(
        'artifact_kind', 'article_50_assessment', 'version', 'article50-r1',
        'approving_authority', 'rehearsal-only',
        'approved_at', '2026-08-29T10:00:00Z',
        'object_key', 'rehearsal/article50-r1', 'sha256', repeat('3', 64),
        'metadata', '{}'::jsonb
    ),
    jsonb_build_array(
        jsonb_build_object(
            'purpose_id', 'recording_voice_processing',
            'lawful_basis_code', 'rehearsal-only',
            'required_for_core_service', true,
            'capability_version', 'phase1-r1',
            'reviewed_at', '2026-08-29T10:00:00Z',
            'retention_control_version', 'ret-r1',
            'deletion_control_version', 'del-r1',
            'rights_control_version', 'rights-r1'
        ),
        jsonb_build_object(
            'purpose_id', 'transcription_feedback',
            'lawful_basis_code', 'rehearsal-only',
            'required_for_core_service', true,
            'capability_version', 'phase1-r1',
            'reviewed_at', '2026-08-29T10:00:00Z',
            'retention_control_version', 'ret-r1',
            'deletion_control_version', 'del-r1',
            'rights_control_version', 'rights-r1'
        ),
        jsonb_build_object(
            'purpose_id', 'individual_learning_profile',
            'lawful_basis_code', 'rehearsal-only',
            'required_for_core_service', true,
            'capability_version', 'phase1-r1',
            'reviewed_at', '2026-08-29T10:00:00Z',
            'retention_control_version', 'ret-r1',
            'deletion_control_version', 'del-r1',
            'rights_control_version', 'rights-r1'
        ),
        jsonb_build_object(
            'purpose_id', 'coach_review',
            'lawful_basis_code', 'rehearsal-only',
            'required_for_core_service', true,
            'capability_version', 'phase1-r1',
            'reviewed_at', '2026-08-29T10:00:00Z',
            'retention_control_version', 'ret-r1',
            'deletion_control_version', 'del-r1',
            'rights_control_version', 'rights-r1'
        )
    ),
    'rehearsal-engineer'
);

-- Exact replay must not add or mutate policy/artifact rows.
SELECT public.register_phase1_policy_v1(
    jsonb_build_object(
        'version', 'phase1-rehearsal-v1',
        'terms_version', 'terms-r1', 'terms_copy', 'Terms rehearsal',
        'terms_copy_sha256', :'terms_hash',
        'privacy_version', 'privacy-r1', 'privacy_copy', 'Privacy rehearsal',
        'privacy_copy_sha256', :'privacy_hash',
        'ai_notice_version', 'ai-r1', 'ai_notice_copy', 'AI notice rehearsal',
        'ai_notice_copy_sha256', :'ai_hash',
        'agreement_copy', 'I am 18+ and accept the rehearsal policy.',
        'agreement_copy_sha256', :'agreement_hash',
        'allowed_countries', jsonb_build_array('pl', 'fr')
    ),
    jsonb_build_object(
        'artifact_kind', 'product_legal_approval', 'version', 'legal-r1',
        'approving_authority', 'rehearsal-only',
        'approved_at', '2026-08-29T10:00:00Z',
        'object_key', 'rehearsal/legal-r1', 'sha256', repeat('1', 64),
        'metadata', '{}'::jsonb
    ),
    jsonb_build_object(
        'artifact_kind', 'power_score_classification', 'version', 'power-r1',
        'approving_authority', 'rehearsal-only',
        'approved_at', '2026-08-29T10:00:00Z',
        'object_key', 'rehearsal/power-r1', 'sha256', repeat('2', 64),
        'metadata', jsonb_build_object(
            'biometric_identification', false,
            'sex_gender_inference', false,
            'emotion_intention_inference', false,
            'pipeline_version', 'voice-confidence-universal-v3'
        )
    ),
    jsonb_build_object(
        'artifact_kind', 'article_50_assessment', 'version', 'article50-r1',
        'approving_authority', 'rehearsal-only',
        'approved_at', '2026-08-29T10:00:00Z',
        'object_key', 'rehearsal/article50-r1', 'sha256', repeat('3', 64),
        'metadata', '{}'::jsonb
    ),
    (SELECT jsonb_agg(jsonb_build_object(
        'purpose_id', id, 'lawful_basis_code', 'rehearsal-only',
        'required_for_core_service', true,
        'capability_version', 'phase1-r1',
        'reviewed_at', '2026-08-29T10:00:00Z',
        'retention_control_version', 'ret-r1',
        'deletion_control_version', 'del-r1',
        'rights_control_version', 'rights-r1'
    ) ORDER BY id) FROM public.processing_purpose_registry
      WHERE phase = 'phase1'),
    'rehearsal-engineer'
);

SELECT public.activate_phase1_policy_v1(
    'phase1-rehearsal-v1', 'rehearsal-engineer', :'evidence_sha'
);

DO $$
DECLARE status JSONB;
BEGIN
    status := public.get_phase1_processing_authorization_v1(
        '10000000-0000-0000-0000-000000000001'::uuid
    );
    IF status->>'code' <> 'PROCESSING_AUTHORIZATION_REQUIRED' THEN
        RAISE EXCEPTION 'activation created acceptance';
    END IF;
END;
$$;

SELECT public.accept_phase1_processing_authorization_v1(
    :'principal_id', 'phase1-rehearsal-v1', :'terms_hash', :'privacy_hash',
    :'ai_hash', :'agreement_hash', 'agree_and_continue', true, 'PL',
    'en-GB', 'rehearsal-client', '2026-08-29T10:05:00Z', 'accept-r1-0001'
);
SELECT public.accept_phase1_processing_authorization_v1(
    :'principal_id', 'phase1-rehearsal-v1', :'terms_hash', :'privacy_hash',
    :'ai_hash', :'agreement_hash', 'agree_and_continue', true, 'PL',
    'en-GB', 'rehearsal-client', '2026-08-29T10:05:00Z', 'accept-r1-0001'
);

DO $$
DECLARE status JSONB; receipt_count INTEGER;
BEGIN
    status := public.get_phase1_processing_authorization_v1(
        '10000000-0000-0000-0000-000000000001'::uuid
    );
    IF NOT (status->>'authorized')::boolean
       OR (status->>'pooled_learning_eligible')::boolean THEN
        RAISE EXCEPTION 'Phase-1 authorization invariant failed';
    END IF;
    SELECT count(*) INTO receipt_count
      FROM public.processing_authorization_receipts
     WHERE acquisition_principal_id =
           '10000000-0000-0000-0000-000000000001'::uuid;
    IF receipt_count <> 1 THEN
        RAISE EXCEPTION 'acceptance replay was not idempotent';
    END IF;
END;
$$;

SELECT public.finalize_phase1_recording_intake_v1(
    :'attempt_id', :'principal_id', :'project_id', :'recording_id',
    'upload-r1-0001', 'r2', 'lab-audio', 'takes/rehearsal.webm',
    4096, 'audio/webm', :'audio_sha', 'read_after_write_sha256'
);
SELECT public.finalize_phase1_recording_intake_v1(
    :'attempt_id', :'principal_id', :'project_id', :'recording_id',
    'upload-r1-0001', 'r2', 'lab-audio', 'takes/rehearsal.webm',
    4096, 'audio/webm', :'audio_sha', 'read_after_write_sha256'
);

DO $$
BEGIN
    IF (SELECT count(*) FROM public.processing_recording_attempts) <> 1
       OR (SELECT count(*) FROM public.processing_audio_objects) <> 1
       OR (SELECT count(*) FROM public.phase1_processing_jobs) <> 1
       OR (SELECT count(*) FROM public.phase1_processing_outbox) <> 1 THEN
        RAISE EXCEPTION 'recording boundary replay duplicated canonical rows';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.processing_authorization_snapshots
         WHERE pooled_learning_eligible
    ) THEN RAISE EXCEPTION 'Phase-1 snapshot became pooled eligible'; END IF;
END;
$$;

SELECT public.issue_phase1_provider_permit_v1(
    :'principal_id', :'attempt_id', :'recording_id', 'openai',
    'transcription', repeat('e', 64),
    '{"content":["audio_bytes"],"purpose":"transcription_feedback"}',
    'provider-r1-0001', 900
) AS permit \gset

DO $$
DECLARE permit_id UUID;
BEGIN
    SELECT id INTO permit_id FROM public.processing_provider_permits
     WHERE idempotency_key = 'provider-r1-0001';
    PERFORM public.record_phase1_provider_operation_v1(
        permit_id, 'started', NULL, NULL, '{}'::jsonb
    );
    PERFORM public.record_phase1_provider_operation_v1(
        permit_id, 'completed', 'provider-op-rehearsal', NULL, '{}'::jsonb
    );
END;
$$;

SELECT public.queue_phase1_orphan_audio_v1(
    :'principal_id', 'r2', 'lab-audio', 'takes/orphan.webm',
    :'object_sha', 'INTAKE_TRANSACTION_FAILED'
);
RESET ROLE;
UPDATE public.processing_orphan_objects SET not_before = now() - interval '1 minute'
 WHERE object_key = 'takes/orphan.webm';
SET ROLE service_role;

DO $$
DECLARE claimed JSONB; orphan_id UUID;
BEGIN
    claimed := public.claim_phase1_orphan_audio_v1(10);
    IF jsonb_array_length(claimed) <> 1 THEN
        RAISE EXCEPTION 'orphan cleanup did not claim the exact unreferenced object';
    END IF;
    orphan_id := (claimed->0->>'id')::uuid;
    PERFORM public.resolve_phase1_orphan_audio_v1(
        orphan_id, 'deleted', NULL
    );
END;
$$;

SELECT public.request_phase1_purge_v1(
    :'principal_id', 'service_termination', 'purge-r1-0001',
    'REHEARSAL_TERMINATION'
);

DO $$
DECLARE status JSONB;
BEGIN
    status := public.get_phase1_processing_authorization_v1(
        '10000000-0000-0000-0000-000000000001'::uuid
    );
    IF status->>'code' <> 'PROCESSING_SERVICE_BLOCKED' THEN
        RAISE EXCEPTION 'termination did not block processing immediately';
    END IF;
    BEGIN
        UPDATE public.processing_authorization_receipts SET locale = 'xx';
        RAISE EXCEPTION 'append-only evidence mutation unexpectedly succeeded';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
    IF has_table_privilege('service_role',
                           'public.processing_authorization_receipts',
                           'INSERT,UPDATE,DELETE') THEN
        RAISE EXCEPTION 'service_role has direct evidence write access';
    END IF;
    IF has_table_privilege('authenticated',
                           'public.processing_authorization_receipts',
                           'SELECT') THEN
        RAISE EXCEPTION 'browser role can read authorization evidence';
    END IF;
END;
$$;

ROLLBACK;
