-- Transaction-scoped proof for the v3 dark write boundary.
BEGIN;

INSERT INTO public.recordings (id)
VALUES ('40000000-0000-4000-8000-000000000001');
INSERT INTO public.owner_principals (id)
VALUES ('30000000-0000-4000-8000-000000000001');
INSERT INTO public.v2_sessions (
    id, arc_id, owner_principal_id, user_id, recording_1_id, take_index,
    recording_kind
) VALUES (
    '10000000-0000-4000-8000-000000000001',
    'arc-v3-rehearsal',
    '30000000-0000-4000-8000-000000000001',
    '20000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000001',
    2,
    'spoken'
);
INSERT INTO public.snippets (
    id, session_id, recording_id, start_offset_ms, duration_ms
) VALUES (
    '50000000-0000-4000-8000-000000000001',
    '10000000-0000-4000-8000-000000000001',
    '40000000-0000-4000-8000-000000000001',
    1250,
    5000
);

DO $$
DECLARE
    frame JSONB := jsonb_build_object(
        'frame_hash', repeat('a', 64),
        'policy_version', 'take-feedback-policy-v3-dark-v2',
        'frame_schema_version', 'take-feedback-policy-v3-frame-v2',
        'take_id', '10000000-0000-4000-8000-000000000001',
        'recording_id', '40000000-0000-4000-8000-000000000001',
        'serves_user_feedback', false,
        'dataset_eligible', false,
        'implementation_versions', jsonb_build_object(
            'confidence_detector_version', 'voice-confidence-v2',
            'acoustic_feature_schema_version', 'acoustic-feature-schema-v1',
            'suggestion_generator_contract_version',
                'feedback-candidate-generator-v1',
            'observed_suggestion_generator_versions', '[]'::jsonb,
            'manager_rules_version', 'take-feedback-manager-v2',
            'manager_evidence_schema_version',
                'take-feedback-manager-evidence-v1',
            'source_code_sha256', repeat('b', 64)
        ),
        'blocks', jsonb_build_array(jsonb_build_object(
            'confidence_candidates', jsonb_build_array(jsonb_build_object(
                'candidate_id', 'relative-confidence:take:snippet',
                'snippet_id', '50000000-0000-4000-8000-000000000001',
                'eligibility', 'eligible',
                'exclusion_reason', null,
                'clip_identity', jsonb_build_object(
                    'take_id', '10000000-0000-4000-8000-000000000001',
                    'recording_id', '40000000-0000-4000-8000-000000000001',
                    'snippet_id', '50000000-0000-4000-8000-000000000001',
                    'start_offset_ms', 1250,
                    'duration_ms', 5000,
                    'clip_identity_sha256', repeat('c', 64)
                )
            ))
        ))
    );
    outcome JSONB;
BEGIN
    SELECT public.record_take_feedback_policy_v3_shadow_v2(
        'arc-v3-rehearsal',
        '10000000-0000-4000-8000-000000000001',
        '40000000-0000-4000-8000-000000000001',
        '30000000-0000-4000-8000-000000000001',
        '20000000-0000-4000-8000-000000000001',
        2,
        'take-feedback-policy-v3-dark-v2',
        frame,
        repeat('a', 64)
    ) INTO outcome;
    IF outcome ->> 'outcome' <> 'stored' THEN
        RAISE EXCEPTION 'valid exact-lineage frame was not stored: %', outcome;
    END IF;

    -- Idempotent replay is accepted, while altered content under the same
    -- Take/policy identity is a conflict.
    SELECT public.record_take_feedback_policy_v3_shadow_v2(
        'arc-v3-rehearsal',
        '10000000-0000-4000-8000-000000000001',
        '40000000-0000-4000-8000-000000000001',
        '30000000-0000-4000-8000-000000000001',
        '20000000-0000-4000-8000-000000000001',
        2,
        'take-feedback-policy-v3-dark-v2',
        frame,
        repeat('a', 64)
    ) INTO outcome;
    IF outcome ->> 'outcome' <> 'stored' THEN
        RAISE EXCEPTION 'idempotent replay failed: %', outcome;
    END IF;

    BEGIN
        PERFORM public.record_take_feedback_policy_v3_shadow_v2(
            'arc-v3-rehearsal',
            '10000000-0000-4000-8000-000000000001',
            '40000000-0000-4000-8000-000000000001',
            '30000000-0000-4000-8000-000000000001',
            '20000000-0000-4000-8000-000000000001',
            2,
            'take-feedback-policy-v3-dark-v2',
            jsonb_set(
                frame,
                '{blocks,0,confidence_candidates,0,clip_identity,duration_ms}',
                '4999'::jsonb
            ),
            repeat('a', 64)
        );
        RAISE EXCEPTION 'mismatched clip interval was accepted';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'mismatched clip interval was accepted' THEN RAISE; END IF;
    END;
END;
$$;

DO $$
BEGIN
    IF NOT has_table_privilege(
        'service_role', 'public.take_feedback_policy_v3_shadow_frames', 'SELECT'
    ) THEN
        RAISE EXCEPTION 'service role must retain read access';
    END IF;
    IF has_table_privilege(
        'service_role', 'public.take_feedback_policy_v3_shadow_frames', 'INSERT'
    ) OR has_table_privilege(
        'service_role', 'public.take_feedback_policy_v3_shadow_frames', 'UPDATE'
    ) OR has_table_privilege(
        'service_role', 'public.take_feedback_policy_v3_shadow_frames', 'DELETE'
    ) THEN
        RAISE EXCEPTION 'service role can bypass the validating RPC';
    END IF;
END;
$$;

DO $$
BEGIN
    BEGIN
        UPDATE public.take_feedback_policy_v3_shadow_frames
           SET frame_hash = repeat('d', 64);
        RAISE EXCEPTION 'immutable frame was mutable';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM = 'immutable frame was mutable' THEN RAISE; END IF;
    END;
END;
$$;

ROLLBACK;
