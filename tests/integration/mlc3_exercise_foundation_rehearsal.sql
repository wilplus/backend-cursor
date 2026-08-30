\set ON_ERROR_STOP on

-- Run after disposable prerequisites and migration 0313.  Every row rolls back.
BEGIN;

\set owner_id '10000000-0000-0000-0000-000000000001'
\set reviewer_id '10000000-0000-0000-0000-000000000002'
\set speaker_id '20000000-0000-0000-0000-000000000001'
\set project_id '30000000-0000-0000-0000-000000000001'
\set take_id '40000000-0000-0000-0000-000000000001'
\set recording_id '50000000-0000-0000-0000-000000000001'
\set snippet_id '60000000-0000-0000-0000-000000000001'
\set policy_id '70000000-0000-0000-0000-000000000001'
\set receipt_id '80000000-0000-0000-0000-000000000001'
\set auth_snapshot_id '90000000-0000-0000-0000-000000000001'
\set audio_object_id 'a0000000-0000-0000-0000-000000000001'
\set evidence_object_id 'a1000000-0000-0000-0000-000000000001'
\set evidence_span_id 'b1000000-0000-0000-0000-000000000001'
\set review_assignment_id 'b0000000-0000-0000-0000-000000000001'
\set blind_packet_id 'b2000000-0000-0000-0000-000000000001'
\set playback_reference_id 'b4000000-0000-0000-0000-000000000001'

INSERT INTO public.owner_principals (id, user_id) VALUES
    (:'owner_id', '11000000-0000-0000-0000-000000000001'),
    (:'reviewer_id', '11000000-0000-0000-0000-000000000002');
INSERT INTO public.projects (id, owner_principal_id)
VALUES (:'project_id', :'owner_id');
INSERT INTO public.v2_sessions (
    id, user_id, owner_principal_id, project_id, recording_1_id
) VALUES (
    :'take_id', '11000000-0000-0000-0000-000000000001', :'owner_id',
    :'project_id', :'recording_id'
);
INSERT INTO public.recording_attempts (id, owner_principal_id, project_id)
VALUES (:'take_id', :'owner_id', :'project_id');
INSERT INTO public.takes (
    id, recording_attempt_id, owner_principal_id, project_id
) VALUES (:'take_id', :'take_id', :'owner_id', :'project_id');
INSERT INTO public.snippets (
    id, session_id, recording_id, start_offset_ms, duration_ms
) VALUES (:'snippet_id', :'take_id', :'recording_id', 1250, 2400);

INSERT INTO public.processing_policy_versions (
    id, version, status, activated_at
) VALUES (:'policy_id', 'phase2-rehearsal-v1', 'active', now() - interval '1 hour');
INSERT INTO public.processing_policy_purposes (policy_id, purpose_id)
VALUES (:'policy_id', 'personalized_exercise_recommendation');
INSERT INTO public.processing_authorization_receipts (
    id, acquisition_principal_id, policy_id
) VALUES (:'receipt_id', :'owner_id', :'policy_id');
INSERT INTO public.processing_authorization_receipt_purposes (
    receipt_id, purpose_id
) VALUES (:'receipt_id', 'personalized_exercise_recommendation');
INSERT INTO public.processing_authorization_snapshots (
    id, acquisition_principal_id, receipt_id, policy_id, purpose_id
) VALUES (
    :'auth_snapshot_id', :'owner_id', :'receipt_id', :'policy_id',
    'personalized_exercise_recommendation'
);
INSERT INTO public.processing_recording_attempts (
    id, acquisition_principal_id, project_id, recording_id
) VALUES (:'take_id', :'owner_id', :'project_id', :'recording_id');
INSERT INTO public.processing_audio_objects (
    id, acquisition_principal_id, recording_attempt_id, storage_provider,
    bucket, object_key, byte_size, content_type, exact_bytes_sha256,
    verification_method
) VALUES (
    :'audio_object_id', :'owner_id', :'take_id', 'r2', 'recordings',
    'm3/rehearsal.wav', 1024, 'audio/wav', repeat('a', 64),
    'read_after_write_sha256'
);
INSERT INTO public.ml_speakers (id) VALUES (:'speaker_id');
INSERT INTO public.ml_speaker_principals (
    speaker_id, acquisition_principal_id
) VALUES (:'speaker_id', :'owner_id');
INSERT INTO public.ml_object_artifacts (
    id, acquisition_principal_id, speaker_id, object_store, bucket,
    object_key, sha256, byte_size, content_type, artifact_kind
) VALUES (
    :'evidence_object_id', :'owner_id', :'speaker_id', 'cloudflare_r2',
    'recordings', 'm3/rehearsal.wav', repeat('a', 64), 1024,
    'audio/wav', 'audio'
);
INSERT INTO public.ml_evidence_spans (
    id, acquisition_principal_id, speaker_id, project_id,
    recording_attempt_id, take_id, object_artifact_id, coordinates
) VALUES (
    :'evidence_span_id', :'owner_id', :'speaker_id', :'project_id',
    :'take_id', :'take_id', :'evidence_object_id',
    '{"start_ms":1250,"end_ms":3650}'::jsonb
);

-- Purpose exists but cannot authorize until it is operational.
SET ROLE service_role;
SELECT public.record_exercise_authorization_check_v1(
    :'owner_id', :'auth_snapshot_id', 'source_audio_lineage', 'auth-denied'
);
DO $$
BEGIN
    IF (SELECT authorized FROM public.exercise_authorization_checks
         WHERE idempotency_key = 'auth-denied') THEN
        RAISE EXCEPTION 'inactive exercise purpose unexpectedly authorized';
    END IF;
END;
$$;
RESET ROLE;

UPDATE public.processing_purpose_registry
   SET operational = true, authorizes_processing = true
 WHERE id = 'personalized_exercise_recommendation';

SET ROLE service_role;
SELECT public.record_exercise_authorization_check_v1(
    :'owner_id', :'auth_snapshot_id', 'source_audio_lineage', 'auth-allowed'
);
SELECT public.record_exercise_authorization_check_v1(
    :'owner_id', :'auth_snapshot_id', 'profile_identity', 'profile-auth-allowed'
);
SELECT public.record_exercise_authorization_check_v1(
    :'owner_id', :'auth_snapshot_id', 'blind_review_preparation',
    'blind-review-auth-allowed'
);
SELECT public.ensure_learning_profile_v1(
    :'speaker_id', :'owner_id',
    (SELECT id FROM public.exercise_authorization_checks
      WHERE idempotency_key = 'profile-auth-allowed'),
    'exercise-profile-v1', 'profile-owner'
);
SELECT public.register_exercise_audio_lineage_v1(
    :'owner_id', :'speaker_id',
    (SELECT id FROM public.learning_profiles WHERE speaker_id = :'speaker_id'),
    (SELECT id FROM public.exercise_authorization_checks
      WHERE idempotency_key = 'auth-allowed'),
    :'audio_object_id', :'project_id', :'take_id', :'take_id',
    :'recording_id', :'snippet_id', 1250, 2400,
    'exercise-audio-lineage-v1', 'lineage-owner-clip'
);

-- Exact replay succeeds; a changed interval under the same key fails.
SELECT public.register_exercise_audio_lineage_v1(
    :'owner_id', :'speaker_id',
    (SELECT id FROM public.learning_profiles WHERE speaker_id = :'speaker_id'),
    (SELECT id FROM public.exercise_authorization_checks
      WHERE idempotency_key = 'auth-allowed'),
    :'audio_object_id', :'project_id', :'take_id', :'take_id',
    :'recording_id', :'snippet_id', 1250, 2400,
    'exercise-audio-lineage-v1', 'lineage-owner-clip'
);
DO $$
BEGIN
    BEGIN
        PERFORM public.register_exercise_audio_lineage_v1(
            '10000000-0000-0000-0000-000000000001'::uuid,
            '20000000-0000-0000-0000-000000000001'::uuid,
            (SELECT id FROM public.learning_profiles LIMIT 1),
            (SELECT id FROM public.exercise_authorization_checks
              WHERE idempotency_key = 'auth-allowed'),
            'a0000000-0000-0000-0000-000000000001'::uuid,
            '30000000-0000-0000-0000-000000000001'::uuid,
            '40000000-0000-0000-0000-000000000001'::uuid,
            '40000000-0000-0000-0000-000000000001'::uuid,
            '50000000-0000-0000-0000-000000000001'::uuid,
            '60000000-0000-0000-0000-000000000001'::uuid,
            1250, 2500, 'exercise-audio-lineage-v1', 'lineage-owner-clip'
        );
        RAISE EXCEPTION 'changed exact lineage replay unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'changed exact lineage replay unexpectedly succeeded' THEN
            RAISE;
        END IF;
        IF SQLERRM <> 'EXERCISE_AUDIO_LINEAGE_SNIPPET_INTERVAL_MISMATCH' THEN
            RAISE;
        END IF;
    END;
END;
$$;

-- No acoustic need is implicitly approved. An active version needs explicit
-- ML/data approval evidence, reviewed safety, and verified media bytes.
SELECT (public.register_exercise_need_contract_v1(
    'pace_space', 1, 'approved',
    '{"purpose":"practice pacing without emotion inference"}'::jsonb,
    ARRAY['syllables_per_second','pause_ratio'],
    ARRAY['syllables_per_second'], ARRAY['audio_unclear','insufficient_span'],
    '[]'::jsonb, 'acoustic-features-v1', 'MLC3-REHEARSAL-ONLY',
    repeat('b', 64), 'rehearsal'
)).* \gset need_
SELECT (public.register_exercise_media_object_v1(
    'exercise-media', 'pace-space/v1.mp4', repeat('c', 64), 2048,
    'video/mp4', 'read_after_write_sha256', now(),
    'rehearsal-content-authority', 'rehearsal'
)).* \gset media_
SELECT public.register_exercise_version_v1(
    'pace-space', 'willab_library', NULL, 'en', 1,
    :'need_id', :'media_id', 'Give each phrase enough room.',
    'approved', 'active', 'rehearsal'
);
SELECT public.finalize_exercise_catalog_snapshot_v1(
    'catalog-policy-v1', 'en', now(), 'catalog-en-v1', 'rehearsal'
);
DO $$
BEGIN
    IF (SELECT version_count FROM public.exercise_catalog_snapshots
         WHERE idempotency_key = 'catalog-en-v1') <> 1
       OR (SELECT count(*) FROM public.exercise_catalog_snapshot_items) <> 1 THEN
        RAISE EXCEPTION 'catalog snapshot did not freeze the complete universe';
    END IF;
END;
$$;

-- service_role can use reviewed RPCs but cannot bypass them with table writes.
DO $$
BEGIN
    BEGIN
        INSERT INTO public.exercise_versions (
            exercise_definition_id, version_number, need_contract_id,
            media_object_id, instruction_text, instruction_sha256,
            safety_state, catalogue_state, version_sha256, created_by
        ) SELECT exercise_definition_id, 99, need_contract_id,
                 media_object_id, 'bypass', repeat('d', 64), 'approved',
                 'active', repeat('e', 64), 'bypass'
            FROM public.exercise_versions LIMIT 1;
        RAISE EXCEPTION 'service role direct catalogue write unexpectedly succeeded';
    EXCEPTION WHEN insufficient_privilege THEN NULL;
    END;
END;
$$;
RESET ROLE;

-- Blind packets must be bound to the assignment's exact immutable evidence.
INSERT INTO public.ml_review_assignments (
    id, learning_surface_id, evidence_span_id, reviewer_principal_id,
    blind_packet_sha256, taxonomy_version
) VALUES (
    :'review_assignment_id', 'confidence_classification',
    :'evidence_span_id', :'reviewer_id', encode(extensions.digest(convert_to(
        public.build_exercise_blind_visible_payload_v1(
            :'blind_packet_id', :'review_assignment_id',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1', :'playback_reference_id',
            2400, 'en', 'Measured passage.'
        )::TEXT, 'UTF8'
    ), 'sha256'), 'hex'),
    'confidence-five-state-v1'
);
INSERT INTO public.ml_review_assignments (
    id, learning_surface_id, evidence_span_id, reviewer_principal_id,
    blind_packet_sha256, taxonomy_version
) VALUES (
    'b0000000-0000-0000-0000-000000000002', 'praise_generation',
    :'evidence_span_id', :'reviewer_id', repeat('2', 64),
    'confidence-five-state-v1'
);
INSERT INTO public.ml_evidence_spans (
    id, acquisition_principal_id, speaker_id, project_id,
    recording_attempt_id, take_id, object_artifact_id, coordinates
) VALUES (
    'b1000000-0000-0000-0000-000000000002', :'owner_id', :'speaker_id',
    :'project_id', :'take_id', :'take_id', :'evidence_object_id',
    '{"start_ms":1500,"end_ms":3900}'::jsonb
);
INSERT INTO public.ml_review_assignments (
    id, learning_surface_id, evidence_span_id, reviewer_principal_id,
    blind_packet_sha256, taxonomy_version
) VALUES (
    'b0000000-0000-0000-0000-000000000003',
    'confidence_classification',
    'b1000000-0000-0000-0000-000000000002', :'reviewer_id',
    repeat('3', 64), 'confidence-five-state-v1'
);
INSERT INTO public.ml_review_assignments (
    id, learning_surface_id, evidence_span_id, reviewer_principal_id,
    blind_packet_sha256, taxonomy_version
) VALUES (
    'b0000000-0000-0000-0000-000000000004',
    'confidence_classification', :'evidence_span_id', :'reviewer_id',
    encode(extensions.digest(convert_to(
        public.build_exercise_blind_visible_payload_v1(
            'b2000000-0000-0000-0000-000000000006',
            'b0000000-0000-0000-0000-000000000004',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1',
            'b4000000-0000-0000-0000-000000000006',
            2400, 'en', 'Measured passage.'
        )::TEXT, 'UTF8'
    ), 'sha256'), 'hex'), 'confidence-five-state-v1'
);

DO $$
DECLARE lineage_id UUID;
BEGIN
    SELECT id INTO lineage_id FROM public.exercise_audio_lineages LIMIT 1;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b2000000-0000-0000-0000-000000000002',
            'b0000000-0000-0000-0000-000000000002', lineage_id,
            (SELECT id FROM public.exercise_authorization_checks
              WHERE idempotency_key = 'blind-review-auth-allowed'),
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1',
            'b4000000-0000-0000-0000-000000000002',
            '2099-01-01T00:00:00Z'::timestamptz, 2400, 'en', NULL,
            'blind-policy-v1', 'wrong-surface'
        );
        RAISE EXCEPTION 'wrong-surface blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'wrong-surface blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_ASSIGNMENT_SURFACE_INVALID' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b2000000-0000-0000-0000-000000000003',
            'b0000000-0000-0000-0000-000000000003', lineage_id,
            (SELECT id FROM public.exercise_authorization_checks
              WHERE idempotency_key = 'blind-review-auth-allowed'),
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1',
            'b4000000-0000-0000-0000-000000000003',
            '2099-01-01T00:00:00Z'::timestamptz, 2400, 'en', NULL,
            'blind-policy-v1', 'wrong-evidence'
        );
        RAISE EXCEPTION 'unrelated-evidence blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'unrelated-evidence blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_LINEAGE_MISMATCH' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b2000000-0000-0000-0000-000000000004',
            'b0000000-0000-0000-0000-000000000001', lineage_id,
            (SELECT id FROM public.exercise_authorization_checks
              WHERE idempotency_key = 'blind-review-auth-allowed'),
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1',
            'b4000000-0000-0000-0000-000000000004',
            '2099-01-01T00:00:00Z'::timestamptz, 2500, 'en', NULL,
            'blind-policy-v1', 'wrong-duration'
        );
        RAISE EXCEPTION 'wrong-duration blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'wrong-duration blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_DURATION_MISMATCH' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b2000000-0000-0000-0000-000000000005',
            'b0000000-0000-0000-0000-000000000001', lineage_id,
            (SELECT id FROM public.exercise_authorization_checks
              WHERE idempotency_key = 'blind-review-auth-allowed'),
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v2',
            'b4000000-0000-0000-0000-000000000005',
            '2099-01-01T00:00:00Z'::timestamptz, 2400, 'en', NULL,
            'blind-policy-v1', 'wrong-taxonomy'
        );
        RAISE EXCEPTION 'wrong-taxonomy blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'wrong-taxonomy blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_TAXONOMY_MISMATCH' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b2000000-0000-0000-0000-000000000009',
            'b0000000-0000-0000-0000-000000000001', lineage_id,
            (SELECT id FROM public.exercise_authorization_checks
              WHERE idempotency_key = 'blind-review-auth-allowed'),
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1',
            'b4000000-0000-0000-0000-000000000009',
            '2099-01-01T00:00:00Z'::timestamptz, 2400, 'en',
            'Measured passage.', 'blind-policy-v1', 'wrong-payload-hash'
        );
        RAISE EXCEPTION 'wrong-payload blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'wrong-payload blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_PAYLOAD_HASH_MISMATCH' THEN RAISE; END IF;
    END;
END;
$$;

-- A privileged writer still cannot persist a payload assembled by the caller
-- or a transcript hash that was not derived from the stored transcript.
DO $$
DECLARE
    lineage_id UUID;
    auth_id UUID;
    canonical_payload JSONB;
    canonical_payload_hash TEXT;
    playback_reference_hash TEXT;
BEGIN
    SELECT id INTO lineage_id FROM public.exercise_audio_lineages LIMIT 1;
    SELECT id INTO auth_id FROM public.exercise_authorization_checks
     WHERE idempotency_key = 'blind-review-auth-allowed';
    canonical_payload := public.build_exercise_blind_visible_payload_v1(
        'b2000000-0000-0000-0000-000000000006',
        'b0000000-0000-0000-0000-000000000004',
        'confidence-exercise-blind-packet-v1',
        'confidence-five-state-v1',
        'b4000000-0000-0000-0000-000000000006',
        2400, 'en', 'Measured passage.'
    );
    canonical_payload_hash := encode(extensions.digest(
        convert_to(canonical_payload::TEXT, 'UTF8'), 'sha256'
    ), 'hex');
    playback_reference_hash := encode(extensions.digest(convert_to(
        'b4000000-0000-0000-0000-000000000006', 'UTF8'
    ), 'sha256'), 'hex');

    BEGIN
        INSERT INTO public.exercise_blind_packets (
            id, review_assignment_id, audio_lineage_id,
            authorization_check_id, reviewer_principal_id,
            packet_schema_version, confidence_taxonomy_version,
            playback_token_sha256, playback_expires_at, clip_duration_ms,
            language_code, asr_transcript, asr_transcript_sha256,
            visible_payload, visible_payload_sha256, idempotency_key
        ) VALUES (
            'b2000000-0000-0000-0000-000000000006',
            'b0000000-0000-0000-0000-000000000004', lineage_id, auth_id,
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1', playback_reference_hash,
            '2099-01-01T00:00:00Z', 2400, 'en', 'Measured passage.',
            encode(extensions.digest(
                convert_to('Measured passage.', 'UTF8'), 'sha256'
            ), 'hex'), canonical_payload || '{"machine_score":0.99}'::jsonb,
            canonical_payload_hash, 'caller-built-payload'
        );
        RAISE EXCEPTION 'caller-built payload unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'caller-built payload unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_PAYLOAD_NOT_CANONICAL' THEN RAISE; END IF;
    END;

    BEGIN
        INSERT INTO public.exercise_blind_packets (
            id, review_assignment_id, audio_lineage_id,
            authorization_check_id, reviewer_principal_id,
            packet_schema_version, confidence_taxonomy_version,
            playback_token_sha256, playback_expires_at, clip_duration_ms,
            language_code, asr_transcript, asr_transcript_sha256,
            visible_payload, visible_payload_sha256, idempotency_key
        ) VALUES (
            'b2000000-0000-0000-0000-000000000006',
            'b0000000-0000-0000-0000-000000000004', lineage_id, auth_id,
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1', playback_reference_hash,
            '2099-01-01T00:00:00Z', 2400, 'en', 'Measured passage.',
            repeat('9', 64), canonical_payload, canonical_payload_hash,
            'caller-built-transcript-hash'
        );
        RAISE EXCEPTION 'caller transcript hash unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'caller transcript hash unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_TRANSCRIPT_HASH_MISMATCH' THEN RAISE; END IF;
    END;
END;
$$;

SET ROLE service_role;
SELECT public.register_exercise_blind_packet_v1(
    :'blind_packet_id', :'review_assignment_id',
    (SELECT id FROM public.exercise_audio_lineages LIMIT 1),
    (SELECT id FROM public.exercise_authorization_checks
      WHERE idempotency_key = 'blind-review-auth-allowed'), :'reviewer_id',
    'confidence-exercise-blind-packet-v1', 'confidence-five-state-v1',
    :'playback_reference_id', '2099-01-01T00:00:00Z'::timestamptz, 2400, 'en',
    'Measured passage.', 'blind-policy-v1', 'blind-packet-1'
);

-- An exact retry is a replay, not a second packet or a unique-key error.
SELECT public.register_exercise_blind_packet_v1(
    :'blind_packet_id', :'review_assignment_id',
    (SELECT id FROM public.exercise_audio_lineages LIMIT 1),
    (SELECT id FROM public.exercise_authorization_checks
      WHERE idempotency_key = 'blind-review-auth-allowed'), :'reviewer_id',
    'confidence-exercise-blind-packet-v1', 'confidence-five-state-v1',
    :'playback_reference_id', '2099-01-01T00:00:00Z', 2400, 'en',
    'Measured passage.', 'blind-policy-v1', 'blind-packet-1'
);
RESET ROLE;

DO $$
BEGIN
    IF (SELECT count(*) FROM public.exercise_blind_packets
         WHERE idempotency_key = 'blind-packet-1') <> 1
       OR (SELECT asr_transcript_sha256 FROM public.exercise_blind_packets
            WHERE idempotency_key = 'blind-packet-1') <>
          encode(extensions.digest(
              convert_to('Measured passage.', 'UTF8'), 'sha256'
          ), 'hex')
       OR (SELECT visible_payload_sha256 FROM public.exercise_blind_packets
            WHERE idempotency_key = 'blind-packet-1') <>
          encode(extensions.digest(convert_to(
              (SELECT visible_payload::TEXT
                 FROM public.exercise_blind_packets
                WHERE idempotency_key = 'blind-packet-1'),
              'UTF8'
          ), 'sha256'), 'hex') THEN
        RAISE EXCEPTION 'server-derived packet or exact replay is invalid';
    END IF;
END;
$$;

-- A previously valid authorization cannot be replayed after live authority is
-- blocked.  The exception subtransaction rolls the synthetic block back.
DO $$
BEGIN
    BEGIN
        INSERT INTO public.processing_service_blocks (
            acquisition_principal_id, effective_at
        ) VALUES (
            '10000000-0000-0000-0000-000000000001', now()
        );
        PERFORM public.register_exercise_blind_packet_v1(
            'b2000000-0000-0000-0000-000000000001',
            'b0000000-0000-0000-0000-000000000001',
            (SELECT id FROM public.exercise_audio_lineages LIMIT 1),
            (SELECT id FROM public.exercise_authorization_checks
              WHERE idempotency_key = 'blind-review-auth-allowed'),
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1',
            'b4000000-0000-0000-0000-000000000001',
            '2099-01-01T00:00:00Z', 2400, 'en', 'Measured passage.',
            'blind-policy-v1', 'blind-packet-1'
        );
        RAISE EXCEPTION 'revoked blind packet replay unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'revoked blind packet replay unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_CURRENT_AUTHORIZATION_REVOKED' THEN RAISE; END IF;
    END;
END;
$$;

-- Policy-purpose membership and receipt/policy consistency are live gates,
-- not facts trusted from the historical authorization check.
DO $$
BEGIN
    BEGIN
        DELETE FROM public.processing_policy_purposes
         WHERE policy_id = '70000000-0000-0000-0000-000000000001'
           AND purpose_id = 'personalized_exercise_recommendation';
        PERFORM public.register_exercise_blind_packet_v1(
            'b2000000-0000-0000-0000-000000000001',
            'b0000000-0000-0000-0000-000000000001',
            (SELECT id FROM public.exercise_audio_lineages LIMIT 1),
            (SELECT id FROM public.exercise_authorization_checks
              WHERE idempotency_key = 'blind-review-auth-allowed'),
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1',
            'b4000000-0000-0000-0000-000000000001',
            '2099-01-01T00:00:00Z', 2400, 'en', 'Measured passage.',
            'blind-policy-v1', 'blind-packet-1'
        );
        RAISE EXCEPTION 'missing policy purpose unexpectedly authorized replay';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'missing policy purpose unexpectedly authorized replay' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_CURRENT_AUTHORIZATION_REVOKED' THEN RAISE; END IF;
    END;

    BEGIN
        INSERT INTO public.processing_policy_versions (
            id, version, status, activated_at
        ) VALUES (
            '70000000-0000-0000-0000-000000000002',
            'unrelated-policy-v1', 'active', now() - interval '1 hour'
        );
        UPDATE public.processing_authorization_receipts
           SET policy_id = '70000000-0000-0000-0000-000000000002'
         WHERE id = '80000000-0000-0000-0000-000000000001';
        PERFORM public.register_exercise_blind_packet_v1(
            'b2000000-0000-0000-0000-000000000001',
            'b0000000-0000-0000-0000-000000000001',
            (SELECT id FROM public.exercise_audio_lineages LIMIT 1),
            (SELECT id FROM public.exercise_authorization_checks
              WHERE idempotency_key = 'blind-review-auth-allowed'),
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1',
            'b4000000-0000-0000-0000-000000000001',
            '2099-01-01T00:00:00Z', 2400, 'en', 'Measured passage.',
            'blind-policy-v1', 'blind-packet-1'
        );
        RAISE EXCEPTION 'receipt policy mismatch unexpectedly authorized replay';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'receipt policy mismatch unexpectedly authorized replay' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_CURRENT_AUTHORIZATION_REVOKED' THEN RAISE; END IF;
    END;
END;
$$;

-- A blind judgment attached to the assignment but pointing at another evidence
-- span cannot unlock reveal or enter the review sequence.
INSERT INTO public.ml_judgments (
    id, review_assignment_id, learning_surface_id, evidence_span_id,
    actor_provenance
) VALUES (
    'b3000000-0000-0000-0000-000000000001', :'review_assignment_id',
    'confidence_classification',
    'b1000000-0000-0000-0000-000000000002', 'blind_coach'
);
DO $$
BEGIN
    BEGIN
        INSERT INTO public.exercise_blind_packet_events (
            blind_packet_id, review_assignment_id, event_kind, judgment_id,
            blindness_policy_version, idempotency_key, occurred_at
        ) VALUES (
            (SELECT id FROM public.exercise_blind_packets
              WHERE idempotency_key = 'blind-packet-1'),
            'b0000000-0000-0000-0000-000000000001',
            'blind_judgment_submitted',
            'b3000000-0000-0000-0000-000000000001', 'blind-policy-v1',
            'wrong-judgment-evidence', now()
        );
        RAISE EXCEPTION 'wrong-evidence blind judgment unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'wrong-evidence blind judgment unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_JUDGMENT_EVIDENCE_MISMATCH' THEN RAISE; END IF;
    END;
END;
$$;

-- Blind reveal cannot be recorded before an exact immutable blind judgment.
DO $$
BEGIN
    BEGIN
        INSERT INTO public.exercise_blind_packet_events (
            blind_packet_id, review_assignment_id, event_kind,
            blindness_policy_version, idempotency_key, occurred_at
        ) VALUES (
            (SELECT id FROM public.exercise_blind_packets
              WHERE idempotency_key = 'blind-packet-1'),
            'b0000000-0000-0000-0000-000000000001',
            'post_judgment_reveal_granted', 'blind-policy-v1',
            'illegal-reveal', now()
        );
        RAISE EXCEPTION 'reveal before judgment unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'reveal before judgment unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_REVEAL_REQUIRES_JUDGMENT' THEN RAISE; END IF;
    END;
END;
$$;

-- The repaired graph reaches practice -> attempts -> Album and M3 lineage.
INSERT INTO public.confident_voice_practice (id, owner_user_id, take_session_id)
VALUES (
    'c0000000-0000-0000-0000-000000000001',
    '11000000-0000-0000-0000-000000000001', :'take_id'
);
INSERT INTO public.confident_voice_practice_attempt (id, practice_id)
VALUES (
    'c1000000-0000-0000-0000-000000000001',
    'c0000000-0000-0000-0000-000000000001'
);
INSERT INTO public.voice_album_practice (arc_id, practice_attempt_id)
VALUES (
    :'project_id', 'c1000000-0000-0000-0000-000000000001'
);
DO $$
DECLARE graph JSONB;
BEGIN
    graph := public.resolve_phase1_purge_subject_graph_v2(
        '10000000-0000-0000-0000-000000000001'
    );
    IF NOT graph->'practice_ids' ? 'c0000000-0000-0000-0000-000000000001'
       OR NOT graph->'practice_attempt_ids' ?
              'c1000000-0000-0000-0000-000000000001'
       OR jsonb_array_length(graph->'exercise_audio_lineage_ids') <> 1
       OR jsonb_array_length(graph->'exercise_blind_packet_ids') <> 1 THEN
        RAISE EXCEPTION 'repaired purge graph omitted exact practice lineage';
    END IF;
END;
$$;

DO $$
DECLARE health JSONB;
BEGIN
    health := public.get_mlc3_exercise_foundation_health_v1();
    IF COALESCE((health->>'producer_integration')::boolean, true)
       OR COALESCE((health->>'serves_user')::boolean, true)
       OR COALESCE((health->>'dataset_creation_enabled')::boolean, true)
       OR COALESCE((health->>'training_enabled')::boolean, true)
       OR COALESCE((health->>'promotion_enabled')::boolean, true) THEN
        RAISE EXCEPTION 'M3-2 dark boundary is not fail closed';
    END IF;
END;
$$;

ROLLBACK;
