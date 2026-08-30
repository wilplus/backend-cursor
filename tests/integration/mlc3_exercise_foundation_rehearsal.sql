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
    :'evidence_span_id', :'reviewer_id', repeat('1', 64),
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

DO $$
DECLARE lineage_id UUID;
BEGIN
    SELECT id INTO lineage_id FROM public.exercise_audio_lineages LIMIT 1;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b0000000-0000-0000-0000-000000000002', lineage_id,
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1', repeat('f', 64),
            now() + interval '15 minutes', 2400, 'en', NULL, NULL,
            repeat('2', 64), 'blind-policy-v1', 'wrong-surface'
        );
        RAISE EXCEPTION 'wrong-surface blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'wrong-surface blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_ASSIGNMENT_SURFACE_INVALID' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b0000000-0000-0000-0000-000000000003', lineage_id,
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1', repeat('f', 64),
            now() + interval '15 minutes', 2400, 'en', NULL, NULL,
            repeat('3', 64), 'blind-policy-v1', 'wrong-evidence'
        );
        RAISE EXCEPTION 'unrelated-evidence blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'unrelated-evidence blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_LINEAGE_MISMATCH' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b0000000-0000-0000-0000-000000000001', lineage_id,
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1', repeat('f', 64),
            now() + interval '15 minutes', 2500, 'en', NULL, NULL,
            repeat('1', 64), 'blind-policy-v1', 'wrong-duration'
        );
        RAISE EXCEPTION 'wrong-duration blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'wrong-duration blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_DURATION_MISMATCH' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b0000000-0000-0000-0000-000000000001', lineage_id,
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v2', repeat('f', 64),
            now() + interval '15 minutes', 2400, 'en', NULL, NULL,
            repeat('1', 64), 'blind-policy-v1', 'wrong-taxonomy'
        );
        RAISE EXCEPTION 'wrong-taxonomy blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'wrong-taxonomy blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_TAXONOMY_MISMATCH' THEN RAISE; END IF;
    END;
    BEGIN
        PERFORM public.register_exercise_blind_packet_v1(
            'b0000000-0000-0000-0000-000000000001', lineage_id,
            '10000000-0000-0000-0000-000000000002',
            'confidence-exercise-blind-packet-v1',
            'confidence-five-state-v1', repeat('f', 64),
            now() + interval '15 minutes', 2400, 'en', NULL, NULL,
            repeat('9', 64), 'blind-policy-v1', 'wrong-payload-hash'
        );
        RAISE EXCEPTION 'wrong-payload blind packet unexpectedly succeeded';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'wrong-payload blind packet unexpectedly succeeded' THEN RAISE; END IF;
        IF SQLERRM <> 'EXERCISE_BLIND_PACKET_PAYLOAD_HASH_MISMATCH' THEN RAISE; END IF;
    END;
END;
$$;

SET ROLE service_role;
SELECT public.register_exercise_blind_packet_v1(
    :'review_assignment_id',
    (SELECT id FROM public.exercise_audio_lineages LIMIT 1), :'reviewer_id',
    'confidence-exercise-blind-packet-v1', 'confidence-five-state-v1',
    repeat('f', 64), now() + interval '15 minutes', 2400, 'en', NULL, NULL,
    repeat('1', 64), 'blind-policy-v1', 'blind-packet-1'
);
RESET ROLE;

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
