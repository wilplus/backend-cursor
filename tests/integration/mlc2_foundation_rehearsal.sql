\set ON_ERROR_STOP on

-- Run only after migrations/add_mlc2_foundation.sql has been applied to an
-- isolated PostgreSQL database.  All fixture rows are rolled back.
BEGIN;

INSERT INTO public.owner_principals (id, guest_secret_hash) VALUES
    ('10000000-0000-0000-0000-000000000001', 'mlc2-rehearsal-owner'),
    ('10000000-0000-0000-0000-000000000002', 'mlc2-rehearsal-reviewer');

INSERT INTO public.projects (id, owner_principal_id, display_name) VALUES (
    '20000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    'MLC-2 rehearsal'
);

INSERT INTO public.recording_attempts (
    id, owner_principal_id, project_id
) VALUES (
    '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001'
);

INSERT INTO public.takes (
    id, owner_principal_id, project_id, recording_attempt_id
) VALUES (
    '30000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001'
);

INSERT INTO public.ml_product_legal_approvals (
    id, approval_reference, approved_copy_sha256, onboarding_copy,
    consent_policy_version, terms_version, privacy_policy_version,
    approving_authority, approved_at, jurisdictions, article_6_basis,
    article_9_treatment, evidence_object_key, evidence_sha256
) VALUES (
    '50000000-0000-0000-0000-000000000001',
    'MLC2-REHEARSAL-ONLY', repeat('c', 64), 'Rehearsal copy',
    'mlc2-rehearsal-v1', 'terms-rehearsal', 'privacy-rehearsal',
    'isolated-test', '2026-08-27T00:00:00Z', ARRAY['EU'], '6(1)(a)',
    '9(2)(a)_when_special_category', 'rehearsal/legal.json', repeat('d', 64)
);

INSERT INTO public.ml_consent_policies (
    version, product_legal_approval_id, required_for_service, bundled_ui,
    active_from
) VALUES (
    'mlc2-rehearsal-v1', '50000000-0000-0000-0000-000000000001',
    true, true, '2026-08-27T00:00:00Z'
);

SET ROLE service_role;

SELECT public.register_ml_speaker_principal_v1(
    '10000000-0000-0000-0000-000000000001', repeat('a', 64),
    'rehearsal-v1', 'initial', repeat('b', 64), 'rehearsal',
    'speaker-sha256-80-10-10-v1'
);

-- Registration and assignment are idempotent and stable.
SELECT public.register_ml_speaker_principal_v1(
    '10000000-0000-0000-0000-000000000001', repeat('a', 64),
    'rehearsal-v1', 'initial', repeat('b', 64), 'rehearsal',
    'speaker-sha256-80-10-10-v1'
);

SELECT public.record_mlc2_consent_grant_v1(
    '10000000-0000-0000-0000-000000000001', 'mlc2-rehearsal-v1',
    'EU', 'terms-rehearsal', 'privacy-rehearsal', '/rehearsal',
    'rehearsal-client',
    jsonb_build_object(
        'accepted', true,
        'copy_sha256', repeat('c', 64)
    ),
    '2026-08-27T12:00:00Z', true, 'rehearsal-consent-grant'
);

SELECT public.create_mlc2_consent_snapshot_v1(
    '10000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000001'
);

SELECT public.enqueue_mlc2_outbox_event_v1(
    'rehearsal-confidence-1', 'confidence_candidate_scored',
    'confidence_classification', 'take',
    '30000000-0000-0000-0000-000000000002',
    '{"payload_type":"confidence_event"}'::jsonb,
    '2026-08-27T12:01:00Z'
);

SELECT count(*) FROM public.claim_mlc2_outbox_events_v1(
    'rehearsal-worker', 1, 60
);

SELECT public.finalize_mlc2_outbox_event_v1(
    (SELECT id FROM public.ml_outbox_events
      WHERE idempotency_key = 'rehearsal-confidence-1'),
    'rehearsal-worker',
    jsonb_build_object(
        'event_id', '60000000-0000-0000-0000-000000000001',
        'idempotency_key', 'rehearsal-confidence-1',
        'learning_contract_version', 'MLC-2',
        'data_epoch', 1,
        'learning_surface_id', 'confidence_classification',
        'pipeline_stage_id', 'classify',
        'feedback_family_id', 'confident_voice',
        'acquisition_principal_id',
            '10000000-0000-0000-0000-000000000001',
        'speaker_id', (
            SELECT speaker_id::text FROM public.ml_speaker_principals
             WHERE acquisition_principal_id =
                '10000000-0000-0000-0000-000000000001'
        ),
        'consent_snapshot_id', (
            SELECT id::text FROM public.ml_consent_snapshots
             WHERE acquisition_principal_id =
                '10000000-0000-0000-0000-000000000001'
        ),
        'project_id', '20000000-0000-0000-0000-000000000001',
        'recording_attempt_id', '30000000-0000-0000-0000-000000000001',
        'take_id', '30000000-0000-0000-0000-000000000002',
        'clip_id', '40000000-0000-0000-0000-000000000001',
        'evidence_locator', jsonb_build_object('start_ms', 0, 'end_ms', 900),
        'execution_version', jsonb_build_object(
            'detector', 'rehearsal-v1',
            'policy', 'deterministic-policy-v1'
        ),
        'payload_type', 'confidence_event',
        'payload', jsonb_build_object('candidate_count', 1),
        'source_event_id', 'rehearsal-source-1',
        'occurred_at', '2026-08-27T12:01:00Z'
    )
);

-- A duplicate finalization returns the first canonical row.
SELECT public.finalize_mlc2_outbox_event_v1(
    (SELECT id FROM public.ml_outbox_events
      WHERE idempotency_key = 'rehearsal-confidence-1'),
    'another-worker', '{}'::jsonb
);

SELECT public.enqueue_mlc2_outbox_event_v1(
    'rehearsal-confidence-retry', 'confidence_candidate_scored',
    'confidence_classification', 'take',
    '30000000-0000-0000-0000-000000000002',
    '{"payload_type":"confidence_event"}'::jsonb,
    '2026-08-27T12:02:00Z'
);
SELECT count(*) FROM public.claim_mlc2_outbox_events_v1(
    'rehearsal-retry-worker', 1, 60
);
SELECT public.fail_mlc2_outbox_event_v1(
    (SELECT id FROM public.ml_outbox_events
      WHERE idempotency_key = 'rehearsal-confidence-retry'),
    'rehearsal-retry-worker', 'rehearsal_transient', 1
);

RESET ROLE;

INSERT INTO public.ml_object_artifacts (
    acquisition_principal_id, speaker_id, consent_snapshot_id, object_store,
    bucket, object_key, sha256, byte_size, content_type, artifact_kind,
    retention_status, created_by
) VALUES (
    '10000000-0000-0000-0000-000000000001',
    (SELECT speaker_id FROM public.ml_speaker_principals
      WHERE acquisition_principal_id =
        '10000000-0000-0000-0000-000000000001'),
    (SELECT id FROM public.ml_consent_snapshots
      WHERE acquisition_principal_id =
        '10000000-0000-0000-0000-000000000001'),
    'cloudflare_r2', 'rehearsal', 'rehearsal/audio.wav', repeat('e', 64),
    900, 'audio/wav', 'audio', 'eligible', 'rehearsal'
);

INSERT INTO public.ml_evidence_spans (
    canonical_event_id, acquisition_principal_id, speaker_id, project_id,
    recording_attempt_id, take_id, object_artifact_id, modality,
    coordinates, content_sha256, evidence_schema_version
) VALUES (
    (SELECT id FROM public.ml_canonical_events
      WHERE idempotency_key = 'rehearsal-confidence-1'),
    '10000000-0000-0000-0000-000000000001',
    (SELECT speaker_id FROM public.ml_speaker_principals
      WHERE acquisition_principal_id =
        '10000000-0000-0000-0000-000000000001'),
    '20000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000002',
    (SELECT id FROM public.ml_object_artifacts
      WHERE object_key = 'rehearsal/audio.wav'),
    'audio', '{"start_ms":0,"end_ms":900}'::jsonb, repeat('f', 64),
    'confidence-evidence-v1'
);

INSERT INTO public.ml_review_assignments (
    learning_surface_id, evidence_span_id, reviewer_principal_id,
    reviewer_role, blind_packet_sha256, taxonomy_version,
    blindness_policy_version, idempotency_key
) VALUES (
    'confidence_classification',
    (SELECT id FROM public.ml_evidence_spans LIMIT 1),
    '10000000-0000-0000-0000-000000000002', 'coach', repeat('1', 64),
    'confidence-five-state-v1', 'blind-before-submit-v1',
    'rehearsal-review-assignment'
);

INSERT INTO public.ml_review_assignment_events (
    review_assignment_id, event_kind, actor_principal_id, idempotency_key
) VALUES (
    (SELECT id FROM public.ml_review_assignments
      WHERE idempotency_key = 'rehearsal-review-assignment'),
    'assigned', '10000000-0000-0000-0000-000000000002',
    'rehearsal-review-assigned'
);

INSERT INTO public.ml_presentations (
    canonical_event_id, learning_surface_id, actor_principal_id, actor_role,
    delivery_mode, evaluation_only, visible_payload_sha256, idempotency_key
) VALUES
    ((SELECT id FROM public.ml_canonical_events
       WHERE idempotency_key = 'rehearsal-confidence-1'),
     'confidence_classification',
     '10000000-0000-0000-0000-000000000001', 'owner', 'production', false,
     repeat('2', 64), 'rehearsal-presentation-production'),
    ((SELECT id FROM public.ml_canonical_events
       WHERE idempotency_key = 'rehearsal-confidence-1'),
     'confidence_classification',
     '10000000-0000-0000-0000-000000000001', 'owner', 'shadow', true,
     repeat('3', 64), 'rehearsal-presentation-shadow');

SET ROLE service_role;

SELECT public.ack_mlc2_rendered_exposure_v1(
    p.id, p.acknowledgement_token,
    '10000000-0000-0000-0000-000000000001',
    '70000000-0000-0000-0000-000000000001',
    '2026-08-27T12:03:00Z', 'rehearsal-client', repeat('2', 64),
    'rehearsal-render-ack'
)
FROM public.ml_presentations p
WHERE p.idempotency_key = 'rehearsal-presentation-production';

DO $$
BEGIN
    BEGIN
        PERFORM public.ack_mlc2_rendered_exposure_v1(
            p.id, p.acknowledgement_token,
            '10000000-0000-0000-0000-000000000001',
            '70000000-0000-0000-0000-000000000002',
            '2026-08-27T12:03:00Z', 'rehearsal-client', repeat('3', 64),
            'rehearsal-shadow-render-ack'
        )
        FROM public.ml_presentations p
        WHERE p.idempotency_key = 'rehearsal-presentation-shadow';
        RAISE EXCEPTION 'shadow render acknowledgement unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'shadow render acknowledgement unexpectedly succeeded' THEN
            RAISE;
        END IF;
    END;

    BEGIN
        PERFORM public.reveal_ml_review_assignment_v1(
            (SELECT id FROM public.ml_review_assignments
              WHERE idempotency_key = 'rehearsal-review-assignment'),
            '10000000-0000-0000-0000-000000000002',
            'rehearsal-premature-reveal'
        );
        RAISE EXCEPTION 'blind reveal unexpectedly succeeded before submission';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'blind reveal unexpectedly succeeded before submission' THEN
            RAISE;
        END IF;
    END;
END;
$$;

RESET ROLE;

INSERT INTO public.ml_review_assignment_events (
    review_assignment_id, event_kind, actor_principal_id, idempotency_key
) VALUES (
    (SELECT id FROM public.ml_review_assignments
      WHERE idempotency_key = 'rehearsal-review-assignment'),
    'submitted', '10000000-0000-0000-0000-000000000002',
    'rehearsal-review-submitted'
);

SET ROLE service_role;
SELECT public.reveal_ml_review_assignment_v1(
    (SELECT id FROM public.ml_review_assignments
      WHERE idempotency_key = 'rehearsal-review-assignment'),
    '10000000-0000-0000-0000-000000000002',
    'rehearsal-review-revealed'
);

SELECT public.record_mlc2_consent_withdrawal_v1(
    '10000000-0000-0000-0000-000000000001',
    (SELECT id FROM public.ml_consent_events
      WHERE idempotency_key = 'rehearsal-consent-grant'),
    '/rehearsal/withdraw', 'rehearsal-client',
    '{"confirmed":true}'::jsonb, '2026-08-27T13:00:00Z',
    'rehearsal-consent-withdrawal'
);

DO $$
BEGIN
    BEGIN
        PERFORM public.create_mlc2_consent_snapshot_v1(
            '10000000-0000-0000-0000-000000000001',
            '30000000-0000-0000-0000-000000000001',
            '30000000-0000-0000-0000-000000000002',
            '20000000-0000-0000-0000-000000000001'
        );
        RAISE EXCEPTION 'snapshot unexpectedly succeeded after withdrawal';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'snapshot unexpectedly succeeded after withdrawal' THEN
            RAISE;
        END IF;
    END;
END;
$$;

DO $$
DECLARE
    ml_table_count integer;
    rls_table_count integer;
BEGIN
    SELECT count(*), count(*) FILTER (WHERE c.relrowsecurity)
      INTO ml_table_count, rls_table_count
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relkind IN ('r', 'p')
       AND c.relname LIKE 'ml_%';
    IF ml_table_count <> 29 OR rls_table_count <> 29 THEN
        RAISE EXCEPTION 'expected 29/29 MLC-2 tables with RLS, got %/%',
            ml_table_count, rls_table_count;
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name LIKE 'ml_%'
           AND grantee IN ('anon', 'authenticated')
    ) THEN
        RAISE EXCEPTION 'anon/authenticated unexpectedly has MLC-2 table grants';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.role_table_grants
         WHERE table_schema = 'public' AND table_name LIKE 'ml_%'
           AND grantee = 'service_role' AND privilege_type <> 'SELECT'
    ) THEN
        RAISE EXCEPTION 'service_role unexpectedly has direct MLC-2 writes';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.routine_privileges
         WHERE routine_schema = 'public' AND routine_name LIKE '%mlc2%'
           AND grantee = 'PUBLIC' AND privilege_type = 'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'PUBLIC unexpectedly has an MLC-2 RPC grant';
    END IF;
    IF (SELECT count(*) FROM public.ml_learning_surfaces) <> 7 THEN
        RAISE EXCEPTION 'canonical learning-surface registry is not exactly seven';
    END IF;
    IF (SELECT count(*) FROM public.ml_canonical_events
         WHERE idempotency_key = 'rehearsal-confidence-1') <> 1 THEN
        RAISE EXCEPTION 'outbox finalization was not effectively-once';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_review_assignment_events
         WHERE event_kind = 'revealed'
    ) THEN
        RAISE EXCEPTION 'blind assignment did not reveal after submission';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_purge_requests
         WHERE idempotency_key = 'rehearsal-consent-withdrawal:purge'
    ) THEN
        RAISE EXCEPTION 'withdrawal did not create a purge request';
    END IF;
END;
$$;

RESET ROLE;

DO $$
BEGIN
    BEGIN
        UPDATE public.ml_canonical_events
           SET source_event_id = 'mutation-must-fail'
         WHERE idempotency_key = 'rehearsal-confidence-1';
        RAISE EXCEPTION 'canonical mutation unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'canonical mutation unexpectedly succeeded' THEN
            RAISE;
        END IF;
    END;
END;
$$;

ROLLBACK;
