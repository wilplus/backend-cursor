\set ON_ERROR_STOP on

-- Run only after 0302 and 0303 have been applied to the disposable rehearsal
-- schema.  Every fixture and contract exercise is transaction-scoped.
BEGIN;

INSERT INTO public.owner_principals (id, guest_secret_hash) VALUES (
    'a0000000-0000-0000-0000-000000000001', 'slice3-owner'
);
INSERT INTO public.projects (id, owner_principal_id, display_name) VALUES (
    'a1000000-0000-0000-0000-000000000001',
    'a0000000-0000-0000-0000-000000000001', 'Slice 3 rehearsal'
);
INSERT INTO public.recording_attempts (id, owner_principal_id, project_id) VALUES (
    'a2000000-0000-0000-0000-000000000001',
    'a0000000-0000-0000-0000-000000000001',
    'a1000000-0000-0000-0000-000000000001'
), (
    'a2000000-0000-0000-0000-000000000002',
    'a0000000-0000-0000-0000-000000000001',
    'a1000000-0000-0000-0000-000000000001'
);
INSERT INTO public.takes (
    id, owner_principal_id, project_id, recording_attempt_id
) VALUES (
    'a3000000-0000-0000-0000-000000000001',
    'a0000000-0000-0000-0000-000000000001',
    'a1000000-0000-0000-0000-000000000001',
    'a2000000-0000-0000-0000-000000000001'
), (
    'a3000000-0000-0000-0000-000000000002',
    'a0000000-0000-0000-0000-000000000001',
    'a1000000-0000-0000-0000-000000000001',
    'a2000000-0000-0000-0000-000000000002'
);

INSERT INTO public.ml_product_legal_approvals (
    id, approval_reference, approved_copy_sha256, onboarding_copy,
    consent_policy_version, terms_version, privacy_policy_version,
    approving_authority, approved_at, jurisdictions, article_6_basis,
    article_9_treatment, evidence_object_key, evidence_sha256
) VALUES (
    'a4000000-0000-0000-0000-000000000001',
    'SLICE3-REHEARSAL-ONLY', repeat('1', 64), 'Rehearsal copy',
    'slice3-consent-v1', 'terms-v1', 'privacy-v1', 'isolated-test',
    '2026-08-27T00:00:00Z', ARRAY['EU'], '6(1)(a)',
    '9(2)(a)_when_special_category', 'legal/slice3.json', repeat('2', 64)
);
INSERT INTO public.ml_consent_policies (
    version, product_legal_approval_id, required_for_service, bundled_ui,
    active_from
) VALUES (
    'slice3-consent-v1', 'a4000000-0000-0000-0000-000000000001',
    true, true, '2026-08-27T00:00:00Z'
);

SET ROLE service_role;

SELECT public.register_ml_speaker_principal_v1(
    'a0000000-0000-0000-0000-000000000001', repeat('3', 64),
    'speaker-resolution-v1', 'initial', repeat('4', 64), 'rehearsal',
    'speaker-sha256-80-10-10-v1'
);
SELECT public.record_mlc2_consent_grant_v1(
    'a0000000-0000-0000-0000-000000000001', 'slice3-consent-v1',
    'EU', 'terms-v1', 'privacy-v1', '/slice3', 'rehearsal-client',
    jsonb_build_object(
        'accepted', true, 'copy_sha256', repeat('1', 64),
        'purposes', jsonb_build_array(
            'personalized_coaching', 'pooled_model_improvement'
        )
    ), '2026-08-27T10:00:00Z', true, 'slice3-consent-grant'
);
SELECT public.create_mlc2_consent_snapshot_v1(
    'a0000000-0000-0000-0000-000000000001',
    'a2000000-0000-0000-0000-000000000001',
    'a3000000-0000-0000-0000-000000000001', NULL
);
SELECT public.create_mlc2_consent_snapshot_v1(
    'a0000000-0000-0000-0000-000000000001',
    'a2000000-0000-0000-0000-000000000002',
    'a3000000-0000-0000-0000-000000000002', NULL
);

SELECT public.enqueue_mlc2_outbox_event_v1(
    'slice3-confidence-frame-1', 'confidence_sampling_frame_finalized',
    'confidence_classification', 'take',
    'a3000000-0000-0000-0000-000000000001',
    '{"contract":"confidence-frame-v1"}'::jsonb,
    '2026-08-27T10:01:00Z'
);
SELECT count(*) FROM public.claim_mlc2_outbox_events_v1(
    'slice3-worker', 1, 60
);

SELECT public.finalize_mlc2_confidence_frame_v1(
    (SELECT id FROM public.ml_outbox_events
      WHERE idempotency_key = 'slice3-confidence-frame-1'),
    'slice3-worker',
    jsonb_build_object(
        'event_id', 'a5000000-0000-0000-0000-000000000001',
        'idempotency_key', 'slice3-confidence-frame-1',
        'learning_contract_version', 'MLC-2', 'data_epoch', 1,
        'learning_surface_id', 'confidence_classification',
        'pipeline_stage_id', 'classify',
        'feedback_family_id', 'confident_voice',
        'acquisition_principal_id', 'a0000000-0000-0000-0000-000000000001',
        'speaker_id', (SELECT speaker_id FROM public.ml_speaker_principals
                       WHERE acquisition_principal_id =
                       'a0000000-0000-0000-0000-000000000001'),
        'consent_snapshot_id', (SELECT id FROM public.ml_consent_snapshots
                                WHERE recording_attempt_id =
                                'a2000000-0000-0000-0000-000000000001'),
        'project_id', 'a1000000-0000-0000-0000-000000000001',
        'recording_attempt_id', 'a2000000-0000-0000-0000-000000000001',
        'take_id', 'a3000000-0000-0000-0000-000000000001',
        'evidence_locator', '{"scope":"complete_take_pool"}'::jsonb,
        'execution_version', '{"contract":"confidence-frame-v1"}'::jsonb,
        'payload_type', 'confidence_event',
        'payload', '{"frame_kind":"take_confidence_candidates"}'::jsonb,
        'source_event_id', 'recording-attempt:slice3:1',
        'occurred_at', '2026-08-27T10:01:00Z'
    ),
    jsonb_build_object(
        'classification_run', jsonb_build_object(
            'id', 'a6000000-0000-0000-0000-000000000001',
            'provider', 'openai', 'model_id', 'confidence-baseline-v1',
            'assignment_origin', 'foundation',
            'assignment_version', 'assignment-v1',
            'code_version', 'slice3-rehearsal', 'configuration', '{}'::jsonb,
            'request_sha256', repeat('5', 64),
            'started_at', '2026-08-27T10:00:00Z',
            'completed_at', '2026-08-27T10:00:01Z',
            'feature_schema_version', 'features-v1',
            'feature_extractor_version', 'extractor-v1',
            'detector_version', 'detector-v1',
            'threshold_version', 'threshold-v1',
            'taxonomy_version', 'confidence-five-state-v1',
            'threshold_snapshot', '{"confident":0.7}'::jsonb
        ),
        'selection_run', jsonb_build_object(
            'id', 'a6000000-0000-0000-0000-000000000002',
            'execution_kind', 'deterministic_policy',
            'selection_policy_version', 'confidence-selection-v1',
            'eligibility_policy_version', 'confidence-eligible-v1',
            'threshold_version', 'threshold-v1',
            'exploration_probability', 0.20,
            'rng_algorithm', 'hmac-sha256-counter-v1',
            'rng_seed', 'opaque-rehearsal-seed',
            'rng_draws', '[{"index":0,"value":0.42}]'::jsonb,
            'code_version', 'slice3-rehearsal', 'configuration', '{}'::jsonb,
            'request_sha256', repeat('6', 64),
            'started_at', '2026-08-27T10:00:01Z',
            'completed_at', '2026-08-27T10:00:02Z'
        ),
        'candidate_set', jsonb_build_object(
            'id', 'a7000000-0000-0000-0000-000000000001',
            'candidate_set_version', 'confidence-frame-v1',
            'candidates', jsonb_build_array(
                jsonb_build_object(
                    'id', 'a8000000-0000-0000-0000-000000000001',
                    'candidate_key', 'clip-1',
                    'clip_id', 'a9000000-0000-0000-0000-000000000001',
                    'evidence', jsonb_build_object(
                        'id', 'aa000000-0000-0000-0000-000000000001',
                        'coordinates', '{"start_ms":0,"end_ms":900}'::jsonb,
                        'content_sha256', repeat('7', 64),
                        'evidence_schema_version', 'audio-span-v1',
                        'object', jsonb_build_object(
                            'id', 'ab000000-0000-0000-0000-000000000001',
                            'bucket', 'mlc2-rehearsal',
                            'object_key', 'confidence/slice3-audio-1.m4a',
                            'sha256', repeat('8', 64), 'byte_size', 1024,
                            'content_type', 'audio/mp4'
                        )
                    ),
                    'prediction', jsonb_build_object(
                        'id', 'ac000000-0000-0000-0000-000000000001',
                        'predicted_value', 'confident',
                        'confidence_score', 0.91,
                        'probability_distribution',
                        '{"confident":0.91,"in_between":0.09}'::jsonb,
                        'raw_output', '{"logit":2.31}'::jsonb,
                        'output_schema_version', 'confidence-output-v1'
                    ),
                    'eligible', true, 'exclusion_reason_code', NULL,
                    'score', 0.91, 'rank', 1, 'selected', true,
                    'selection_mode', 'deterministic',
                    'selection_reason_code', 'highest_ranked_eligible',
                    'sampling_probability', 0.8, 'rng_draw_index', NULL
                ),
                jsonb_build_object(
                    'id', 'a8000000-0000-0000-0000-000000000002',
                    'candidate_key', 'clip-2',
                    'clip_id', 'a9000000-0000-0000-0000-000000000002',
                    'evidence', jsonb_build_object(
                        'id', 'aa000000-0000-0000-0000-000000000002',
                        'coordinates', '{"start_ms":1000,"end_ms":1400}'::jsonb,
                        'content_sha256', repeat('9', 64),
                        'evidence_schema_version', 'audio-span-v1',
                        'object', jsonb_build_object(
                            'id', 'ab000000-0000-0000-0000-000000000002',
                            'bucket', 'mlc2-rehearsal',
                            'object_key', 'confidence/slice3-audio-2.m4a',
                            'sha256', repeat('a', 64), 'byte_size', 512,
                            'content_type', 'audio/mp4'
                        )
                    ),
                    'eligible', false,
                    'exclusion_reason_code', 'audio_too_short',
                    'score', NULL, 'rank', NULL, 'selected', false,
                    'selection_mode', 'excluded',
                    'selection_reason_code', 'ineligible_audio_duration',
                    'sampling_probability', 0, 'rng_draw_index', NULL
                )
            )
        )
    )
);

RESET ROLE;

DO $$
BEGIN
    IF (SELECT count(*) FROM public.ml_model_runs) <> 2
       OR (SELECT count(*) FROM public.ml_classification_runs) <> 1
       OR (SELECT count(*) FROM public.ml_selection_runs) <> 1
       OR (SELECT count(*) FROM public.ml_machine_predictions) <> 1
       OR (SELECT count(*) FROM public.ml_candidate_sets) <> 1
       OR (SELECT count(*) FROM public.ml_candidates) <> 2 THEN
        RAISE EXCEPTION 'atomic confidence frame row counts are wrong';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_candidate_sets
         WHERE pool_size = 2 AND eligible_count = 1 AND excluded_count = 1
           AND selected_count = 1 AND length(immutable_pool_sha256) = 64
    ) THEN
        RAISE EXCEPTION 'complete pool counts or immutable hash are missing';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_candidates
         WHERE exclusion_reason_code = 'audio_too_short'
           AND sampling_probability = 0 AND selection_mode = 'excluded'
    ) THEN
        RAISE EXCEPTION 'excluded candidate was not frozen';
    END IF;
END;
$$;

-- At-least-once delivery produces one effectively-once frame.
SET ROLE service_role;
SELECT public.finalize_mlc2_confidence_frame_v1(
    (SELECT id FROM public.ml_outbox_events
      WHERE idempotency_key = 'slice3-confidence-frame-1'),
    'slice3-worker',
    (SELECT jsonb_build_object(
        'event_id', event_id, 'idempotency_key', idempotency_key,
        'learning_contract_version', learning_contract_version,
        'data_epoch', data_epoch, 'learning_surface_id', learning_surface_id,
        'pipeline_stage_id', pipeline_stage_id,
        'feedback_family_id', feedback_family_id,
        'acquisition_principal_id', acquisition_principal_id,
        'speaker_id', speaker_id, 'consent_snapshot_id', consent_snapshot_id,
        'project_id', project_id,
        'recording_attempt_id', recording_attempt_id, 'take_id', take_id,
        'evidence_locator', evidence_locator,
        'execution_version', execution_version, 'payload_type', payload_type,
        'payload', payload, 'source_event_id', source_event_id,
        'occurred_at', occurred_at
    ) FROM public.ml_canonical_events
      WHERE idempotency_key = 'slice3-confidence-frame-1'),
    (SELECT frame_manifest FROM public.ml_candidate_sets LIMIT 1)
);
RESET ROLE;

DO $$
BEGIN
    IF (SELECT count(*) FROM public.ml_canonical_events
         WHERE idempotency_key = 'slice3-confidence-frame-1') <> 1
       OR (SELECT count(*) FROM public.ml_candidate_sets) <> 1
       OR (SELECT count(*) FROM public.ml_candidates) <> 2 THEN
        RAISE EXCEPTION 'idempotent replay duplicated confidence provenance';
    END IF;
END;
$$;

-- A late candidate constraint failure rolls back the canonical event, model
-- runs, evidence and outbox completion together.
SET ROLE service_role;
SELECT public.enqueue_mlc2_outbox_event_v1(
    'slice3-confidence-frame-invalid', 'confidence_sampling_frame_finalized',
    'confidence_classification', 'take',
    'a3000000-0000-0000-0000-000000000001',
    '{"contract":"confidence-frame-v1"}'::jsonb,
    '2026-08-27T10:02:00Z'
);
SELECT count(*) FROM public.claim_mlc2_outbox_events_v1(
    'slice3-invalid-worker', 1, 60
);

DO $$
DECLARE
    source_frame JSONB;
    invalid_candidate JSONB;
    invalid_frame JSONB;
    invalid_event JSONB;
BEGIN
    SELECT frame_manifest INTO source_frame FROM public.ml_candidate_sets LIMIT 1;
    invalid_candidate :=
        (source_frame #> '{candidate_set,candidates,0}') - 'prediction';
    invalid_candidate := jsonb_set(
        invalid_candidate, '{id}',
        '"ad000000-0000-0000-0000-000000000001"'::jsonb
    );
    invalid_candidate := jsonb_set(
        invalid_candidate, '{evidence,id}',
        '"ae000000-0000-0000-0000-000000000001"'::jsonb
    );
    invalid_frame := jsonb_build_object(
        'classification_run', jsonb_set(
            source_frame -> 'classification_run', '{id}',
            '"af000000-0000-0000-0000-000000000001"'::jsonb
        ),
        'selection_run', jsonb_set(
            source_frame -> 'selection_run', '{id}',
            '"af000000-0000-0000-0000-000000000002"'::jsonb
        ),
        'candidate_set', jsonb_build_object(
            'id', 'af000000-0000-0000-0000-000000000003',
            'candidate_set_version', 'confidence-frame-v1',
            'candidates', jsonb_build_array(invalid_candidate)
        )
    );
    invalid_event := jsonb_build_object(
        'event_id', 'af000000-0000-0000-0000-000000000004',
        'idempotency_key', 'slice3-confidence-frame-invalid',
        'learning_contract_version', 'MLC-2', 'data_epoch', 1,
        'learning_surface_id', 'confidence_classification',
        'pipeline_stage_id', 'classify',
        'feedback_family_id', 'confident_voice',
        'acquisition_principal_id', 'a0000000-0000-0000-0000-000000000001',
        'speaker_id', (SELECT speaker_id FROM public.ml_speaker_principals
                       WHERE acquisition_principal_id =
                       'a0000000-0000-0000-0000-000000000001'),
        'consent_snapshot_id', (SELECT id FROM public.ml_consent_snapshots
                                WHERE recording_attempt_id =
                                'a2000000-0000-0000-0000-000000000001'),
        'project_id', 'a1000000-0000-0000-0000-000000000001',
        'recording_attempt_id', 'a2000000-0000-0000-0000-000000000001',
        'take_id', 'a3000000-0000-0000-0000-000000000001',
        'evidence_locator', '{"scope":"invalid-rehearsal"}'::jsonb,
        'execution_version', '{"contract":"confidence-frame-v1"}'::jsonb,
        'payload_type', 'confidence_event',
        'payload', '{"frame_kind":"invalid-rehearsal"}'::jsonb,
        'source_event_id', 'recording-attempt:slice3:invalid',
        'occurred_at', '2026-08-27T10:02:00Z'
    );
    BEGIN
        PERFORM public.finalize_mlc2_confidence_frame_v1(
            (SELECT id FROM public.ml_outbox_events
              WHERE idempotency_key = 'slice3-confidence-frame-invalid'),
            'slice3-invalid-worker', invalid_event, invalid_frame
        );
        RAISE EXCEPTION 'invalid confidence frame unexpectedly finalized';
    EXCEPTION WHEN check_violation THEN
        NULL;
    END;
END;
$$;
RESET ROLE;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM public.ml_canonical_events
         WHERE idempotency_key = 'slice3-confidence-frame-invalid'
    ) OR EXISTS (
        SELECT 1 FROM public.ml_model_runs
         WHERE id IN (
             'af000000-0000-0000-0000-000000000001',
             'af000000-0000-0000-0000-000000000002'
         )
    ) OR EXISTS (
        SELECT 1 FROM public.ml_outbox_events
         WHERE idempotency_key = 'slice3-confidence-frame-invalid'
           AND processed_at IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'failed frame left partial canonical provenance';
    END IF;
END;
$$;

-- The service role can inspect but cannot insert directly.
DO $$
BEGIN
    IF has_table_privilege('service_role', 'public.ml_candidate_sets', 'INSERT')
       OR NOT has_table_privilege(
           'service_role', 'public.ml_candidate_sets', 'SELECT'
       ) THEN
        RAISE EXCEPTION 'service-role table permissions are unsafe';
    END IF;
    IF has_table_privilege('anon', 'public.ml_candidates', 'SELECT')
       OR has_table_privilege('authenticated', 'public.ml_candidates', 'SELECT') THEN
        RAISE EXCEPTION 'client role can read blind selection metadata';
    END IF;
END;
$$;

-- Appended rows cannot be silently changed.
DO $$
BEGIN
    BEGIN
        UPDATE public.ml_candidates SET score = 0.01
         WHERE candidate_key = 'clip-1';
        RAISE EXCEPTION 'append-only mutation unexpectedly succeeded';
    EXCEPTION WHEN raise_exception THEN
        IF SQLERRM = 'append-only mutation unexpectedly succeeded' THEN RAISE; END IF;
    END;
END;
$$;

ROLLBACK;
