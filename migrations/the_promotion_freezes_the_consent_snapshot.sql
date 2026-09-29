-- 0392 · The promotion freezes the consent snapshot (Q1, founder 2026-09-29).
--
-- promote_recording_attempt_with_mlc2_confidence_v1 looked up a per-attempt
-- ml_consent_snapshots row and raised when none existed, but nothing in the
-- application created that row: the only creator had no caller. The first
-- founder-canary Take would therefore have failed at promotion. This
-- migration replaces the function with one that takes the snapshot itself,
-- from the current bundled grant, inside the same transaction as the Take
-- promotion and the outbox event. A pre-made snapshot (the rehearsal makes
-- one) is honoured unchanged; a missing grant still fails the promotion.
--
-- Additive: one function body replaced, same signature, same grants, the
-- search path 0307 set. No table changes, no rows touched, no environment
-- variable, no learning writer activated: the function stays unreachable
-- while MLC2_CONFIDENCE_CUTOVER_MODE is "dark".

BEGIN;

CREATE OR REPLACE FUNCTION public.promote_recording_attempt_with_mlc2_confidence_v1(
    p_recording_attempt_id UUID,
    p_completion_hash TEXT,
    p_processing_job_id UUID,
    p_attempt_count INTEGER,
    p_input_hash TEXT,
    p_output_hash TEXT,
    p_idempotency_key TEXT,
    p_source_manifest JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = extensions, public
AS $$
DECLARE
    promotion       JSONB;
    attempt         public.recording_attempts%ROWTYPE;
    speaker_id      UUID;
    consent_id      UUID;
    outbox_key      TEXT;
    outbox_event    public.ml_outbox_events;
    receipt         public.ml_confidence_producer_receipts;
    manifest_hash   TEXT;
    event_id        UUID := gen_random_uuid();
    event_payload   JSONB;
    replayed        BOOLEAN := false;
BEGIN
    IF jsonb_typeof(p_source_manifest) <> 'object'
       OR p_source_manifest ->> 'source_schema_version'
          IS DISTINCT FROM 'confidence-source-audio-v1'
       OR jsonb_typeof(p_source_manifest -> 'audio') <> 'object'
       OR p_source_manifest #>> '{audio,object_store}'
          IS DISTINCT FROM 'cloudflare_r2'
       OR NULLIF(btrim(p_source_manifest #>> '{audio,bucket}'), '') IS NULL
       OR NULLIF(btrim(p_source_manifest #>> '{audio,object_key}'), '') IS NULL
       OR length(COALESCE(p_source_manifest #>> '{audio,sha256}', '')) <> 64
       OR COALESCE((p_source_manifest #>> '{audio,byte_size}')::bigint, 0) <= 0
       OR p_source_manifest #>> '{audio,content_type}' NOT LIKE 'audio/%' THEN
        RAISE EXCEPTION 'confidence producer requires immutable R2 source audio';
    END IF;

    manifest_hash := encode(
        digest(convert_to(p_source_manifest::text, 'UTF8'), 'sha256'), 'hex'
    );
    promotion := public.promote_recording_attempt_to_take_v1(
        p_recording_attempt_id, p_completion_hash, p_processing_job_id,
        p_attempt_count, p_input_hash, p_output_hash, p_idempotency_key
    );
    replayed := COALESCE((promotion ->> 'replayed')::boolean, false);

    SELECT * INTO attempt FROM public.recording_attempts row
     WHERE row.id = p_recording_attempt_id FOR SHARE;
    SELECT principal.speaker_id INTO speaker_id
      FROM public.ml_speaker_principals principal
     WHERE principal.acquisition_principal_id = attempt.owner_principal_id;
    IF speaker_id IS NULL THEN
        RAISE EXCEPTION 'confidence producer requires a resolved speaker';
    END IF;

    SELECT * INTO receipt
      FROM public.ml_confidence_producer_receipts row
     WHERE row.take_id = p_recording_attempt_id;
    IF replayed AND receipt.id IS NULL THEN
        RAISE EXCEPTION 'cannot attach canonical producer to a pre-cutover Take';
    END IF;
    IF receipt.id IS NOT NULL THEN
        IF receipt.source_manifest_sha256 <> manifest_hash
           OR receipt.acquisition_principal_id <> attempt.owner_principal_id
           OR receipt.speaker_id <> speaker_id THEN
            RAISE EXCEPTION 'confidence producer idempotency conflict';
        END IF;
        RETURN promotion || jsonb_build_object(
            'producer_receipt_id', receipt.id,
            'outbox_event_id', receipt.outbox_event_id,
            'source_manifest_sha256', receipt.source_manifest_sha256,
            'producer_replayed', true
        );
    END IF;

    -- Q1 (founder, 2026-09-29). The promotion freezes the consent state it
    -- runs under: when no snapshot exists for this attempt yet, one is taken
    -- now from the current bundled grant. Without a grant the snapshot RPC
    -- raises and the whole promotion rolls back with it, so a Take is never
    -- promoted canonically without the consent it needs.
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_consent_snapshots snapshot
         WHERE snapshot.recording_attempt_id = attempt.id
           AND snapshot.acquisition_principal_id = attempt.owner_principal_id
    ) THEN
        PERFORM public.create_mlc2_consent_snapshot_v1(
            attempt.owner_principal_id, attempt.id, NULL, attempt.project_id
        );
    END IF;

    SELECT snapshot.id INTO consent_id
      FROM public.ml_consent_snapshots snapshot
     WHERE snapshot.recording_attempt_id = attempt.id
       AND snapshot.acquisition_principal_id = attempt.owner_principal_id
       AND snapshot.retention_state = 'eligible'
       AND snapshot.purpose_state #>>
           '{pooled_model_improvement,authorized}' = 'true'
       AND NOT EXISTS (
           SELECT 1 FROM public.ml_consent_events withdrawal
            WHERE withdrawal.event_kind = 'withdraw'
              AND withdrawal.supersedes_event_id = snapshot.grant_event_id
       )
     ORDER BY snapshot.captured_at DESC, snapshot.id DESC
     LIMIT 1;
    IF consent_id IS NULL THEN
        RAISE EXCEPTION 'confidence producer lacks current model-improvement consent';
    END IF;

    outbox_key := 'mlc2-confidence-take:' || p_recording_attempt_id::text
                  || ':' || p_completion_hash;
    event_payload := jsonb_build_object(
        'producer_contract_version', 'confidence-producer-v1',
        'event_id', event_id,
        'idempotency_key', outbox_key,
        'learning_contract_version', 'MLC-2',
        'data_epoch', 1,
        'learning_surface_id', 'confidence_classification',
        'pipeline_stage_id', 'classify',
        'feedback_family_id', 'confident_voice',
        'acquisition_principal_id', attempt.owner_principal_id,
        'speaker_id', speaker_id,
        'consent_snapshot_id', consent_id,
        'project_id', attempt.project_id,
        'recording_attempt_id', attempt.id,
        'take_id', attempt.id,
        'source_event_id', 'recording-attempt:' || attempt.id::text
                           || ':successful-take',
        'occurred_at', now(),
        'source_manifest', p_source_manifest,
        'source_manifest_sha256', manifest_hash,
        'payload_type', 'confidence_event',
        'payload', jsonb_build_object(
            'frame_kind', 'take_confidence_candidates',
            'source_manifest_sha256', manifest_hash
        )
    );
    SELECT * INTO outbox_event FROM public.enqueue_mlc2_outbox_event_v1(
        outbox_key, 'confidence_take_ready', 'confidence_classification',
        'take', attempt.id, event_payload, now()
    );

    INSERT INTO public.ml_confidence_producer_receipts (
        take_id, recording_attempt_id, acquisition_principal_id, speaker_id,
        consent_snapshot_id, outbox_event_id, source_manifest,
        source_manifest_sha256, producer_contract_version
    ) VALUES (
        attempt.id, attempt.id, attempt.owner_principal_id, speaker_id,
        consent_id, outbox_event.id, p_source_manifest, manifest_hash,
        'confidence-producer-v1'
    ) RETURNING * INTO receipt;

    RETURN promotion || jsonb_build_object(
        'producer_receipt_id', receipt.id,
        'outbox_event_id', receipt.outbox_event_id,
        'source_manifest_sha256', receipt.source_manifest_sha256,
        'producer_replayed', false
    );
END;
$$;

REVOKE ALL ON FUNCTION public.promote_recording_attempt_with_mlc2_confidence_v1(
    UUID, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.promote_recording_attempt_with_mlc2_confidence_v1(
    UUID, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, JSONB
) TO service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
