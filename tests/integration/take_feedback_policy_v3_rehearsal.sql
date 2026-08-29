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
) VALUES
    (
        '50000000-0000-4000-8000-000000000001',
        '10000000-0000-4000-8000-000000000001',
        '40000000-0000-4000-8000-000000000001', 1250, 5000
    ),
    (
        '50000000-0000-4000-8000-000000000002',
        '10000000-0000-4000-8000-000000000001',
        '40000000-0000-4000-8000-000000000001', 7000, 4000
    );

DO $$
DECLARE
    legacy_frame JSONB := jsonb_build_object(
        'frame_hash', repeat('9', 64),
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
            'source_code_sha256', repeat('8', 64)
        ),
        'blocks', jsonb_build_array(jsonb_build_object(
            'confidence_candidates', jsonb_build_array(
                jsonb_build_object(
                    'candidate_id', 'relative-confidence:legacy:one',
                    'snippet_id', '50000000-0000-4000-8000-000000000001',
                    'eligibility', 'eligible',
                    'machine_version', 'voice-confidence-v2',
                    'clip_identity', jsonb_build_object(
                        'take_id', '10000000-0000-4000-8000-000000000001',
                        'recording_id', '40000000-0000-4000-8000-000000000001',
                        'snippet_id', '50000000-0000-4000-8000-000000000001',
                        'start_offset_ms', 1250, 'duration_ms', 5000,
                        'clip_identity_sha256', repeat('c', 64)
                    )
                ),
                jsonb_build_object(
                    'candidate_id', 'relative-confidence:legacy:two',
                    'snippet_id', '50000000-0000-4000-8000-000000000002',
                    'eligibility', 'eligible',
                    'machine_version', 'voice-confidence-v2',
                    'clip_identity', jsonb_build_object(
                        'take_id', '10000000-0000-4000-8000-000000000001',
                        'recording_id', '40000000-0000-4000-8000-000000000001',
                        'snippet_id', '50000000-0000-4000-8000-000000000002',
                        'start_offset_ms', 7000, 'duration_ms', 4000,
                        'clip_identity_sha256', repeat('d', 64)
                    )
                )
            )
        ))
    );
    frame JSONB := jsonb_build_object(
        'frame_hash', repeat('a', 64),
        'policy_version', 'take-feedback-policy-v3-universal-dark-v3',
        'frame_schema_version', 'take-feedback-policy-v3-frame-v3',
        'take_id', '10000000-0000-4000-8000-000000000001',
        'recording_id', '40000000-0000-4000-8000-000000000001',
        'serves_user_feedback', false,
        'dataset_eligible', false,
        'implementation_versions', jsonb_build_object(
            'confidence_detector_version', 'voice-confidence-universal-v3',
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
            'selected_candidate_id', 'relative-confidence:take:snippet',
            'confidence_candidates', jsonb_build_array(
                jsonb_build_object(
                    'candidate_id', 'relative-confidence:take:snippet',
                    'snippet_id', '50000000-0000-4000-8000-000000000001',
                    'eligibility', 'eligible',
                    'exclusion_reason', null,
                    'machine_version', 'voice-confidence-universal-v3',
                    'clip_identity', jsonb_build_object(
                        'take_id', '10000000-0000-4000-8000-000000000001',
                        'recording_id', '40000000-0000-4000-8000-000000000001',
                        'snippet_id', '50000000-0000-4000-8000-000000000001',
                        'start_offset_ms', 1250,
                        'duration_ms', 5000,
                        'clip_identity_sha256', repeat('c', 64)
                    )
                ),
                jsonb_build_object(
                    'candidate_id', 'relative-confidence:legacy:snippet',
                    'snippet_id', '50000000-0000-4000-8000-000000000002',
                    'eligibility', 'excluded',
                    'exclusion_reason', 'incompatible_detector_version',
                    'machine_version', 'voice-confidence-v2',
                    'clip_identity', jsonb_build_object(
                        'take_id', '10000000-0000-4000-8000-000000000001',
                        'recording_id', '40000000-0000-4000-8000-000000000001',
                        'snippet_id', '50000000-0000-4000-8000-000000000002',
                        'start_offset_ms', 7000,
                        'duration_ms', 4000,
                        'clip_identity_sha256', repeat('d', 64)
                    )
                )
            )
        ))
    );
    outcome JSONB;
BEGIN
    -- The database owner seeds a historical row to simulate data written
    -- before 0311. Service-role execution of the old writer is revoked.
    INSERT INTO public.take_feedback_policy_v3_shadow_frames (
        take_session_id, recording_id, policy_version, arc_id,
        acquisition_principal_id, owner_user_id, take_index, frame, frame_hash
    ) VALUES (
        '10000000-0000-4000-8000-000000000001',
        '40000000-0000-4000-8000-000000000001',
        'take-feedback-policy-v3-dark-v2', 'arc-v3-rehearsal',
        '30000000-0000-4000-8000-000000000001',
        '20000000-0000-4000-8000-000000000001', 2,
        legacy_frame, repeat('9', 64)
    );

    SELECT public.record_take_feedback_policy_v3_shadow_v3(
        'arc-v3-rehearsal',
        '10000000-0000-4000-8000-000000000001',
        '40000000-0000-4000-8000-000000000001',
        '30000000-0000-4000-8000-000000000001',
        '20000000-0000-4000-8000-000000000001',
        2,
        'take-feedback-policy-v3-universal-dark-v3',
        frame,
        repeat('a', 64)
    ) INTO outcome;
    IF outcome ->> 'outcome' <> 'stored' THEN
        RAISE EXCEPTION 'valid exact-lineage frame was not stored: %', outcome;
    END IF;

    -- Idempotent replay is accepted, while altered content under the same
    -- Take/policy identity is a conflict.
    SELECT public.record_take_feedback_policy_v3_shadow_v3(
        'arc-v3-rehearsal',
        '10000000-0000-4000-8000-000000000001',
        '40000000-0000-4000-8000-000000000001',
        '30000000-0000-4000-8000-000000000001',
        '20000000-0000-4000-8000-000000000001',
        2,
        'take-feedback-policy-v3-universal-dark-v3',
        frame,
        repeat('a', 64)
    ) INTO outcome;
    IF outcome ->> 'outcome' <> 'stored' THEN
        RAISE EXCEPTION 'idempotent replay failed: %', outcome;
    END IF;

    SELECT public.record_take_feedback_policy_v3_shadow_v3(
        'arc-v3-rehearsal',
        '10000000-0000-4000-8000-000000000001',
        '40000000-0000-4000-8000-000000000001',
        '30000000-0000-4000-8000-000000000001',
        '20000000-0000-4000-8000-000000000001',
        2,
        'take-feedback-policy-v3-universal-dark-v3',
        jsonb_set(
            jsonb_set(frame, '{frame_hash}', to_jsonb(repeat('d', 64))),
            '{comparison_nonce}', '"changed"'::jsonb
        ),
        repeat('d', 64)
    ) INTO outcome;
    IF outcome ->> 'outcome' <> 'conflict' THEN
        RAISE EXCEPTION 'changed replay was not rejected: %', outcome;
    END IF;

    BEGIN
        PERFORM public.record_take_feedback_policy_v3_shadow_v3(
            'arc-v3-rehearsal',
            '10000000-0000-4000-8000-000000000001',
            '40000000-0000-4000-8000-000000000001',
            '30000000-0000-4000-8000-000000000001',
            '20000000-0000-4000-8000-000000000001',
            2,
            'take-feedback-policy-v3-universal-dark-v3',
            jsonb_set(
                frame,
                '{blocks,0,confidence_candidates,0,clip_identity,duration_ms}',
                '4999'::jsonb
            ),
            repeat('a', 64)
        );
        RAISE EXCEPTION 'mismatched clip interval was accepted';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%universal-v3 confidence clip lineage mismatch%'
        THEN RAISE; END IF;
    END;

    IF (SELECT count(*) FROM public.take_feedback_detector_reconciliation row
         WHERE row.take_session_id =
               '10000000-0000-4000-8000-000000000001'
           AND row.outcome = 'incompatible_detector_version') <> 2 THEN
        RAISE EXCEPTION 'exact incompatible clip inventory was not preserved';
    END IF;
    IF (SELECT count(*) FROM public.take_feedback_detector_reconciliation row
         WHERE row.take_session_id =
               '10000000-0000-4000-8000-000000000001'
           AND row.outcome = 'recomputed') <> 1 THEN
        RAISE EXCEPTION 'recomputation was not limited to the exact matching clip';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.take_feedback_detector_reconciliation row
         WHERE row.snippet_id = '50000000-0000-4000-8000-000000000002'
           AND row.outcome = 'recomputed'
    ) THEN
        RAISE EXCEPTION 'unrecomputed v2 clip was falsely marked recomputed';
    END IF;

    -- An old detector result cannot enter the universal contract as an
    -- eligible/unmeasured candidate.
    BEGIN
        PERFORM public.record_take_feedback_policy_v3_shadow_v3(
            'arc-v3-rehearsal',
            '10000000-0000-4000-8000-000000000001',
            '40000000-0000-4000-8000-000000000001',
            '30000000-0000-4000-8000-000000000001',
            '20000000-0000-4000-8000-000000000001',
            2, 'take-feedback-policy-v3-universal-dark-v3',
            jsonb_set(
                jsonb_set(frame,
                    '{blocks,0,confidence_candidates,0,machine_version}',
                    '"voice-confidence-v2"'::jsonb),
                '{blocks,0,confidence_candidates,0,eligibility}',
                '"eligible"'::jsonb
            ), repeat('a', 64)
        );
        RAISE EXCEPTION 'incompatible detector artifact was accepted as eligible';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE
           '%invalid universal-v3 detector transition inventory%'
        THEN RAISE; END IF;
    END;

    -- Exclusion changes eligibility, not provenance. An incompatible v2 clip
    -- with altered coordinates must still be rejected.
    BEGIN
        PERFORM public.record_take_feedback_policy_v3_shadow_v3(
            'arc-v3-rehearsal',
            '10000000-0000-4000-8000-000000000001',
            '40000000-0000-4000-8000-000000000001',
            '30000000-0000-4000-8000-000000000001',
            '20000000-0000-4000-8000-000000000001',
            2, 'take-feedback-policy-v3-universal-dark-v3',
            jsonb_set(
                frame,
                '{blocks,0,confidence_candidates,1,clip_identity,duration_ms}',
                '3999'::jsonb
            ), repeat('a', 64)
        );
        RAISE EXCEPTION 'excluded incompatible clip bypassed exact lineage';
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT LIKE '%universal-v3 confidence clip lineage mismatch%'
        THEN RAISE; END IF;
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
    IF has_function_privilege(
        'service_role',
        'public.record_take_feedback_policy_v3_shadow_v2(text,uuid,uuid,uuid,uuid,integer,text,jsonb,text)',
        'EXECUTE'
    ) THEN
        RAISE EXCEPTION 'service role can still write historical v2 frames';
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
