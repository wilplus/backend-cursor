\set ON_ERROR_STOP on

-- Run after 0302, 0303 and 0304 in a disposable PostgreSQL database.  This
-- invokes the dark producer RPC directly; no application flag is changed.
BEGIN;

INSERT INTO public.owner_principals (id, guest_secret_hash) VALUES
    ('b0000000-0000-0000-0000-000000000001', 'slice4-owner'),
    ('b0000000-0000-0000-0000-000000000002', 'slice4-reviewer');
INSERT INTO public.projects (id, owner_principal_id, display_name) VALUES (
    'b1000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001', 'Slice 4 rehearsal'
);
INSERT INTO public.recording_attempts (
    id, owner_principal_id, project_id, upload_idempotency_key,
    recording_id, storage_bucket, storage_key, recording_kind, status
) VALUES (
    'b2000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001',
    'b1000000-0000-0000-0000-000000000001', 'slice4-upload-1',
    'b2100000-0000-0000-0000-000000000001', 'mlc2-rehearsal',
    'confidence/slice4-source.webm', 'spoken', 'processing'
);
INSERT INTO public.ml_product_legal_approvals (
    id, approval_reference, approved_copy_sha256, onboarding_copy,
    consent_policy_version, terms_version, privacy_policy_version,
    approving_authority, approved_at, jurisdictions, article_6_basis,
    article_9_treatment, evidence_object_key, evidence_sha256
) VALUES (
    'b3000000-0000-0000-0000-000000000001',
    'SLICE4-REHEARSAL-ONLY', repeat('1', 64), 'Rehearsal copy',
    'slice4-consent-v1', 'terms-v1', 'privacy-v1', 'isolated-test',
    '2026-08-27T00:00:00Z', ARRAY['EU'], '6(1)(a)',
    '9(2)(a)_when_special_category', 'legal/slice4.json', repeat('2', 64)
);
INSERT INTO public.ml_consent_policies (
    version, product_legal_approval_id, required_for_service, bundled_ui,
    active_from
) VALUES (
    'slice4-consent-v1', 'b3000000-0000-0000-0000-000000000001',
    true, true, '2026-08-27T00:00:00Z'
);

SET ROLE service_role;

SELECT public.register_ml_speaker_principal_v1(
    'b0000000-0000-0000-0000-000000000001', repeat('3', 64),
    'speaker-resolution-v1', 'initial', repeat('4', 64), 'rehearsal',
    'speaker-sha256-80-10-10-v1'
);

-- Product Take promotion and producer enqueue must both roll back when the
-- acquisition principal has no immutable consent snapshot.
DO $$
BEGIN
    PERFORM public.promote_recording_attempt_with_mlc2_confidence_v1(
        'b2000000-0000-0000-0000-000000000001', repeat('5', 64), NULL,
        1, repeat('6', 64), repeat('7', 64), 'slice4-promotion-1',
        jsonb_build_object(
            'source_schema_version', 'confidence-source-audio-v1',
            'audio', jsonb_build_object(
                'object_store', 'cloudflare_r2',
                'bucket', 'mlc2-rehearsal',
                'object_key', 'confidence/slice4-source.webm',
                'sha256', repeat('8', 64), 'byte_size', 4096,
                'content_type', 'audio/webm'
            )
        )
    );
    RAISE EXCEPTION 'producer unexpectedly promoted without consent';
EXCEPTION WHEN OTHERS THEN
    IF SQLERRM = 'producer unexpectedly promoted without consent' THEN
        RAISE;
    END IF;
END;
$$;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.takes WHERE id =
               'b2000000-0000-0000-0000-000000000001')
       OR EXISTS (SELECT 1 FROM public.ml_outbox_events WHERE aggregate_id =
                  'b2000000-0000-0000-0000-000000000001')
       OR EXISTS (SELECT 1 FROM public.ml_confidence_producer_receipts WHERE
                  take_id = 'b2000000-0000-0000-0000-000000000001') THEN
        RAISE EXCEPTION 'failed producer left partial product or outbox state';
    END IF;
END;
$$;

SELECT public.record_mlc2_consent_grant_v1(
    'b0000000-0000-0000-0000-000000000001', 'slice4-consent-v1',
    'EU', 'terms-v1', 'privacy-v1', '/slice4', 'rehearsal-client',
    jsonb_build_object(
        'accepted', true, 'copy_sha256', repeat('1', 64),
        'purposes', jsonb_build_array(
            'personalized_coaching', 'pooled_model_improvement'
        )
    ), '2026-08-27T10:00:00Z', true, 'slice4-consent-grant'
);
SELECT public.create_mlc2_consent_snapshot_v1(
    'b0000000-0000-0000-0000-000000000001',
    'b2000000-0000-0000-0000-000000000001', NULL, NULL
);

SELECT public.promote_recording_attempt_with_mlc2_confidence_v1(
    'b2000000-0000-0000-0000-000000000001', repeat('5', 64), NULL,
    1, repeat('6', 64), repeat('7', 64), 'slice4-promotion-1',
    jsonb_build_object(
        'source_schema_version', 'confidence-source-audio-v1',
        'audio', jsonb_build_object(
            'object_store', 'cloudflare_r2',
            'bucket', 'mlc2-rehearsal',
            'object_key', 'confidence/slice4-source.webm',
            'sha256', repeat('8', 64), 'byte_size', 4096,
            'content_type', 'audio/webm'
        )
    )
);
SELECT public.promote_recording_attempt_with_mlc2_confidence_v1(
    'b2000000-0000-0000-0000-000000000001', repeat('5', 64), NULL,
    1, repeat('6', 64), repeat('7', 64), 'slice4-promotion-1',
    jsonb_build_object(
        'source_schema_version', 'confidence-source-audio-v1',
        'audio', jsonb_build_object(
            'object_store', 'cloudflare_r2',
            'bucket', 'mlc2-rehearsal',
            'object_key', 'confidence/slice4-source.webm',
            'sha256', repeat('8', 64), 'byte_size', 4096,
            'content_type', 'audio/webm'
        )
    )
);
DO $$
BEGIN
    IF (SELECT count(*) FROM public.takes WHERE id =
        'b2000000-0000-0000-0000-000000000001') <> 1
       OR (SELECT count(*) FROM public.ml_confidence_producer_receipts WHERE
           take_id = 'b2000000-0000-0000-0000-000000000001') <> 1
       OR (SELECT count(*) FROM public.ml_outbox_events WHERE aggregate_id =
           'b2000000-0000-0000-0000-000000000001') <> 1 THEN
        RAISE EXCEPTION 'producer replay was not effectively-once';
    END IF;
END;
$$;

-- A different surface is present but the confidence claim must not lease it.
SELECT public.enqueue_mlc2_outbox_event_v1(
    'slice4-other-surface', 'praise_ready', 'praise_generation', 'take',
    'b2000000-0000-0000-0000-000000000001', '{}'::jsonb,
    '2026-08-27T10:01:00Z'
);
SELECT count(*) FROM public.claim_mlc2_confidence_outbox_v1(
    'slice4-worker', 5, 60
);
DO $$
BEGIN
    IF (SELECT count(*) FROM public.ml_outbox_events
         WHERE locked_by = 'slice4-worker') <> 1
       OR EXISTS (SELECT 1 FROM public.ml_outbox_events
                   WHERE idempotency_key = 'slice4-other-surface'
                     AND locked_by IS NOT NULL) THEN
        RAISE EXCEPTION 'confidence worker leased another surface';
    END IF;
END;
$$;

SELECT public.finalize_mlc2_confidence_frame_v1(
    (SELECT outbox_event_id FROM public.ml_confidence_producer_receipts
      WHERE take_id = 'b2000000-0000-0000-0000-000000000001'),
    'slice4-worker',
    (SELECT jsonb_build_object(
        'event_id', payload ->> 'event_id',
        'idempotency_key', payload ->> 'idempotency_key',
        'learning_contract_version', 'MLC-2', 'data_epoch', 1,
        'learning_surface_id', 'confidence_classification',
        'pipeline_stage_id', 'classify',
        'feedback_family_id', 'confident_voice',
        'acquisition_principal_id', payload ->> 'acquisition_principal_id',
        'speaker_id', payload ->> 'speaker_id',
        'consent_snapshot_id', payload ->> 'consent_snapshot_id',
        'project_id', payload ->> 'project_id',
        'recording_attempt_id', payload ->> 'recording_attempt_id',
        'take_id', payload ->> 'take_id',
        'evidence_locator', jsonb_build_object(
            'scope', 'complete_take_pool',
            'source_manifest_sha256', payload ->> 'source_manifest_sha256'
        ),
        'execution_version', jsonb_build_object(
            'producer_contract_version', 'confidence-producer-v1',
            'worker_version', 'slice4-rehearsal'
        ),
        'payload_type', 'confidence_event',
        'payload', payload -> 'payload',
        'source_event_id', payload ->> 'source_event_id',
        'occurred_at', payload ->> 'occurred_at'
    ) FROM public.ml_outbox_events WHERE id = (
        SELECT outbox_event_id FROM public.ml_confidence_producer_receipts
         WHERE take_id = 'b2000000-0000-0000-0000-000000000001'
    )),
    jsonb_build_object(
        'classification_run', jsonb_build_object(
            'id', 'b4000000-0000-0000-0000-000000000001',
            'provider', 'openai', 'model_id', 'confidence-baseline-v1',
            'assignment_origin', 'foundation',
            'assignment_version', 'assignment-v1',
            'code_version', 'slice4-rehearsal', 'configuration', '{}'::jsonb,
            'request_sha256', repeat('9', 64),
            'started_at', '2026-08-27T10:01:00Z',
            'completed_at', '2026-08-27T10:01:01Z',
            'feature_schema_version', 'features-v1',
            'feature_extractor_version', 'extractor-v1',
            'detector_version', 'detector-v1',
            'threshold_version', 'threshold-v1',
            'taxonomy_version', 'confidence-five-state-v1',
            'threshold_snapshot', '{"confident":0.7}'::jsonb
        ),
        'selection_run', jsonb_build_object(
            'id', 'b4000000-0000-0000-0000-000000000002',
            'execution_kind', 'deterministic_policy',
            'selection_policy_version', 'confidence-selection-v1',
            'eligibility_policy_version', 'confidence-eligible-v1',
            'threshold_version', 'threshold-v1',
            'exploration_probability', 0.20,
            'rng_algorithm', 'hmac-sha256-counter-v1',
            'rng_seed', 'opaque-rehearsal-seed',
            'rng_draws', '[{"index":0,"value":0.42}]'::jsonb,
            'provider', 'deterministic_policy',
            'model_id', 'confidence-selection-v1',
            'assignment_origin', 'deterministic_policy',
            'assignment_version', 'confidence-selection-v1',
            'code_version', 'slice4-rehearsal', 'configuration', '{}'::jsonb,
            'request_sha256', repeat('a', 64),
            'started_at', '2026-08-27T10:01:01Z',
            'completed_at', '2026-08-27T10:01:02Z'
        ),
        'candidate_set', jsonb_build_object(
            'id', 'b5000000-0000-0000-0000-000000000001',
            'candidate_set_version', 'confidence-frame-v1',
            'candidates', jsonb_build_array(jsonb_build_object(
                'id', 'b6000000-0000-0000-0000-000000000001',
                'candidate_key', 'clip-1',
                'clip_id', 'b7000000-0000-0000-0000-000000000001',
                'evidence', jsonb_build_object(
                    'id', 'b8000000-0000-0000-0000-000000000001',
                    'coordinates', '{"start_ms":100,"end_ms":900}'::jsonb,
                    'content_sha256', repeat('b', 64),
                    'evidence_schema_version', 'audio-span-v1',
                    'object', jsonb_build_object(
                        'id', 'b9000000-0000-0000-0000-000000000001',
                        'bucket', 'mlc2-rehearsal',
                        'object_key', 'confidence/slice4-source.webm',
                        'sha256', repeat('8', 64), 'byte_size', 4096,
                        'content_type', 'audio/webm'
                    )
                ),
                'prediction', jsonb_build_object(
                    'id', 'ba000000-0000-0000-0000-000000000001',
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
            ))
        )
    )
);

SELECT public.create_mlc2_confidence_blind_packet_v1(
    'b6000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000002', 'coach',
    'confidence-five-state-v1', 'blind-confidence-v1', 'canary',
    'slice4-blind-packet-1'
);
DO $$
DECLARE packet JSONB;
BEGIN
    SELECT visible_packet INTO packet FROM public.ml_confidence_blind_packets
     WHERE candidate_id = 'b6000000-0000-0000-0000-000000000001';
    IF packet ?| ARRAY[
        'transcript', 'text', 'score', 'rank', 'model', 'prediction',
        'threshold', 'selection_reason', 'sampling_probability', 'rng',
        'user_label', 'coach_label', 'peer_label', 'judgment'
    ] OR (packet -> 'clip') ?| ARRAY['transcript', 'score', 'rank'] THEN
        RAISE EXCEPTION 'blind packet leaked answer or selection hints';
    END IF;
    IF packet #> '{taxonomy,choices}' IS DISTINCT FROM jsonb_build_array(
        'rating_yes', 'rating_in_between', 'rating_no',
        'rating_not_sure', 'rating_audio_unclear'
    ) THEN
        RAISE EXCEPTION 'blind packet taxonomy drifted';
    END IF;
END;
$$;

SELECT public.ack_mlc2_rendered_exposure_v1(
    packet.presentation_id, presentation.acknowledgement_token,
    packet.reviewer_principal_id,
    'bb000000-0000-0000-0000-000000000001',
    '2026-08-27T10:02:00Z', 'slice4-client',
    packet.visible_packet_sha256, 'slice4-render-1'
)
FROM public.ml_confidence_blind_packets packet
JOIN public.ml_presentations presentation ON presentation.id = packet.presentation_id
WHERE packet.candidate_id = 'b6000000-0000-0000-0000-000000000001';

DO $$
DECLARE assignment_id UUID;
BEGIN
    SELECT review_assignment_id INTO assignment_id
      FROM public.ml_confidence_blind_packets
     WHERE candidate_id = 'b6000000-0000-0000-0000-000000000001';
    PERFORM public.reveal_mlc2_confidence_review_v1(
        assignment_id, 'b0000000-0000-0000-0000-000000000002',
        'slice4-reveal-too-early'
    );
    RAISE EXCEPTION 'blind reveal unexpectedly succeeded before judgment';
EXCEPTION WHEN OTHERS THEN
    IF SQLERRM = 'blind reveal unexpectedly succeeded before judgment' THEN
        RAISE;
    END IF;
END;
$$;

SELECT public.submit_mlc2_confidence_blind_judgment_v1(
    packet.review_assignment_id, packet.reviewer_principal_id,
    exposure.id, 'rating_in_between', '2026-08-27T10:03:00Z',
    'slice4-judgment-1'
)
FROM public.ml_confidence_blind_packets packet
JOIN public.ml_rendered_exposures exposure
  ON exposure.presentation_id = packet.presentation_id
WHERE packet.candidate_id = 'b6000000-0000-0000-0000-000000000001';

SELECT public.reveal_mlc2_confidence_review_v1(
    packet.review_assignment_id, packet.reviewer_principal_id,
    'slice4-reveal-1'
)
FROM public.ml_confidence_blind_packets packet
WHERE packet.candidate_id = 'b6000000-0000-0000-0000-000000000001';

DO $$
DECLARE health JSONB;
BEGIN
    health := public.get_mlc2_confidence_slice4_health_v1();
    IF health ->> 'producer_activation' <> 'disabled_in_application_config'
       OR (health ->> 'receipt_without_outbox_count')::integer <> 0
       OR (health ->> 'processed_without_frame_count')::integer <> 0
       OR (health ->> 'blind_assignment_without_packet_count')::integer <> 0
       OR (health ->> 'revealed_without_judgment_count')::integer <> 0
       OR (health ->> 'dataset_creation_enabled')::boolean
       OR (health ->> 'training_enabled')::boolean
       OR (health ->> 'promotion_enabled')::boolean THEN
        RAISE EXCEPTION 'slice4 health reports an unsafe state: %', health;
    END IF;
END;
$$;

DO $$
BEGIN
    UPDATE public.ml_confidence_blind_packets SET packet_version = 'changed'
     WHERE candidate_id = 'b6000000-0000-0000-0000-000000000001';
    RAISE EXCEPTION 'append-only packet unexpectedly updated';
EXCEPTION WHEN OTHERS THEN
    IF SQLERRM = 'append-only packet unexpectedly updated' THEN RAISE; END IF;
END;
$$;

RESET ROLE;
SET ROLE authenticated;
DO $$
BEGIN
    PERFORM 1 FROM public.ml_confidence_blind_packets LIMIT 1;
    RAISE EXCEPTION 'authenticated unexpectedly read blind packets';
EXCEPTION WHEN insufficient_privilege THEN NULL;
END;
$$;
RESET ROLE;

ROLLBACK;
