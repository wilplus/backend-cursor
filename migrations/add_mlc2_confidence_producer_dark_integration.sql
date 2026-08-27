-- 0304 · MLC-2 Confidence Classification dark producer integration.
--
-- This slice connects the already-approved Attempt -> Take transaction to a
-- typed confidence outbox, adds a surface-filtered worker lease, and freezes
-- blind review packets.  The application cutover flag remains hard-disabled;
-- no producer, review route or legacy cutover is activated by this migration.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ml_confidence_producer_receipts (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    take_id                  UUID NOT NULL UNIQUE
        REFERENCES public.takes(id) ON DELETE RESTRICT,
    recording_attempt_id     UUID NOT NULL UNIQUE
        REFERENCES public.recording_attempts(id) ON DELETE RESTRICT,
    acquisition_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    speaker_id               UUID NOT NULL
        REFERENCES public.ml_speakers(id) ON DELETE RESTRICT,
    consent_snapshot_id      UUID NOT NULL
        REFERENCES public.ml_consent_snapshots(id) ON DELETE RESTRICT,
    outbox_event_id          UUID NOT NULL UNIQUE
        REFERENCES public.ml_outbox_events(id) ON DELETE RESTRICT,
    source_manifest          JSONB NOT NULL CHECK (
        jsonb_typeof(source_manifest) = 'object'
    ),
    source_manifest_sha256   TEXT NOT NULL CHECK (
        length(source_manifest_sha256) = 64
    ),
    producer_contract_version TEXT NOT NULL CHECK (
        producer_contract_version = 'confidence-producer-v1'
    ),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_confidence_receipt_attempt_take_check CHECK (
        take_id = recording_attempt_id
    ),
    CONSTRAINT ml_confidence_receipt_speaker_principal_fk FOREIGN KEY (
        speaker_id, acquisition_principal_id
    ) REFERENCES public.ml_speaker_principals(
        speaker_id, acquisition_principal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ml_confidence_receipt_consent_principal_fk FOREIGN KEY (
        consent_snapshot_id, acquisition_principal_id
    ) REFERENCES public.ml_consent_snapshots(
        id, acquisition_principal_id
    ) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS ml_confidence_producer_created_idx
    ON public.ml_confidence_producer_receipts(created_at, id);

CREATE TABLE IF NOT EXISTS public.ml_confidence_blind_packets (
    id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    review_assignment_id     UUID NOT NULL UNIQUE
        REFERENCES public.ml_review_assignments(id) ON DELETE RESTRICT,
    presentation_id          UUID NOT NULL UNIQUE
        REFERENCES public.ml_presentations(id) ON DELETE RESTRICT,
    candidate_id             UUID NOT NULL
        REFERENCES public.ml_candidates(id) ON DELETE RESTRICT,
    reviewer_principal_id    UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    reviewer_role            TEXT NOT NULL CHECK (reviewer_role IN (
        'coach', 'peer'
    )),
    packet_version           TEXT NOT NULL CHECK (
        packet_version = 'confidence-blind-packet-v1'
    ),
    visible_packet           JSONB NOT NULL CHECK (
        jsonb_typeof(visible_packet) = 'object'
    ),
    visible_packet_sha256    TEXT NOT NULL CHECK (
        length(visible_packet_sha256) = 64
    ),
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ml_confidence_packet_assignment_actor_fk FOREIGN KEY (
        review_assignment_id, reviewer_principal_id
    ) REFERENCES public.ml_review_assignments(
        id, reviewer_principal_id
    ) ON DELETE RESTRICT,
    CONSTRAINT ml_confidence_packet_presentation_actor_hash_fk FOREIGN KEY (
        presentation_id, reviewer_principal_id, visible_packet_sha256
    ) REFERENCES public.ml_presentations(
        id, actor_principal_id, visible_payload_sha256
    ) ON DELETE RESTRICT,
    UNIQUE (candidate_id, reviewer_principal_id)
);

CREATE INDEX IF NOT EXISTS ml_confidence_blind_packet_candidate_idx
    ON public.ml_confidence_blind_packets(candidate_id, created_at);

-- Promotion and outbox insertion share one PostgreSQL transaction.  Calling
-- this RPC is the future application cutover branch; Slice 4 leaves that
-- branch unreachable through Config.MLC2_CONFIDENCE_CANONICAL_WRITES_ENABLED.
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
SET search_path = public
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

CREATE OR REPLACE FUNCTION public.claim_mlc2_confidence_outbox_v1(
    p_worker_id TEXT,
    p_limit INTEGER DEFAULT 25,
    p_lease_seconds INTEGER DEFAULT 60
) RETURNS SETOF public.ml_outbox_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF NULLIF(btrim(p_worker_id), '') IS NULL
       OR p_limit < 1 OR p_limit > 100 OR p_lease_seconds < 10 THEN
        RAISE EXCEPTION 'invalid confidence outbox claim bounds';
    END IF;
    RETURN QUERY
    WITH claimable AS (
        SELECT event.id FROM public.ml_outbox_events event
         WHERE event.processed_at IS NULL
           AND event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.available_at <= now()
           AND (event.lease_expires_at IS NULL
                OR event.lease_expires_at <= now())
         ORDER BY event.available_at, event.created_at, event.id
         FOR UPDATE SKIP LOCKED
         LIMIT p_limit
    )
    UPDATE public.ml_outbox_events event
       SET locked_by = p_worker_id,
           lease_expires_at = now() + make_interval(secs => p_lease_seconds),
           processing_started_at = now(),
           attempt_count = event.attempt_count + 1,
           last_error_code = NULL,
           last_error_at = NULL
      FROM claimable
     WHERE event.id = claimable.id
    RETURNING event.*;
END;
$$;

-- Packet content is assembled server-side from immutable candidate evidence.
-- No caller can add transcript, score, rank, threshold, model, policy,
-- probability, RNG, user answer or another rater's judgment.
CREATE OR REPLACE FUNCTION public.create_mlc2_confidence_blind_packet_v1(
    p_candidate_id UUID,
    p_reviewer_principal_id UUID,
    p_reviewer_role TEXT,
    p_taxonomy_version TEXT,
    p_blindness_policy_version TEXT,
    p_delivery_mode TEXT,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    candidate       public.ml_candidates%ROWTYPE;
    candidate_set   public.ml_candidate_sets%ROWTYPE;
    evidence        public.ml_evidence_spans%ROWTYPE;
    object_row      public.ml_object_artifacts%ROWTYPE;
    assignment      public.ml_review_assignments%ROWTYPE;
    presentation    public.ml_presentations%ROWTYPE;
    packet_row      public.ml_confidence_blind_packets%ROWTYPE;
    packet          JSONB;
    packet_hash     TEXT;
BEGIN
    IF p_reviewer_role NOT IN ('coach', 'peer')
       OR NULLIF(btrim(p_taxonomy_version), '') IS NULL
       OR NULLIF(btrim(p_blindness_policy_version), '') IS NULL
       OR p_delivery_mode NOT IN ('canary', 'production')
       OR NULLIF(btrim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'blind confidence assignment payload is incomplete';
    END IF;
    SELECT * INTO candidate FROM public.ml_candidates row
     WHERE row.id = p_candidate_id AND row.selected AND row.eligible;
    IF candidate.id IS NULL THEN
        RAISE EXCEPTION 'blind packet requires a selected eligible candidate';
    END IF;
    SELECT * INTO candidate_set FROM public.ml_candidate_sets row
     WHERE row.id = candidate.candidate_set_id;
    SELECT * INTO evidence FROM public.ml_evidence_spans row
     WHERE row.id = candidate.evidence_span_id;
    SELECT * INTO object_row FROM public.ml_object_artifacts row
     WHERE row.id = evidence.object_artifact_id
       AND row.artifact_kind = 'audio'
       AND row.retention_status = 'eligible';
    IF object_row.id IS NULL
       OR p_reviewer_principal_id = candidate_set.acquisition_principal_id THEN
        RAISE EXCEPTION 'blind packet evidence or independent reviewer rejected';
    END IF;

    packet := jsonb_build_object(
        'packet_version', 'confidence-blind-packet-v1',
        'clip', jsonb_build_object(
            'clip_id', candidate.clip_id,
            'audio_object_id', object_row.id,
            'audio_sha256', object_row.sha256,
            'start_ms', (evidence.coordinates ->> 'start_ms')::integer,
            'end_ms', (evidence.coordinates ->> 'end_ms')::integer
        ),
        'taxonomy', jsonb_build_object(
            'version', p_taxonomy_version,
            'choices', jsonb_build_array(
                'rating_yes', 'rating_in_between', 'rating_no',
                'rating_not_sure', 'rating_audio_unclear'
            )
        )
    );
    packet_hash := encode(
        digest(convert_to(packet::text, 'UTF8'), 'sha256'), 'hex'
    );

    SELECT persisted_packet.* INTO packet_row
      FROM public.ml_confidence_blind_packets persisted_packet
      JOIN public.ml_review_assignments existing_assignment
        ON existing_assignment.id = persisted_packet.review_assignment_id
     WHERE existing_assignment.idempotency_key = p_idempotency_key;
    IF packet_row.id IS NOT NULL THEN
        IF packet_row.candidate_id <> p_candidate_id
           OR packet_row.reviewer_principal_id <> p_reviewer_principal_id
           OR packet_row.reviewer_role <> p_reviewer_role
           OR packet_row.visible_packet_sha256 <> packet_hash THEN
            RAISE EXCEPTION 'blind packet idempotency conflict';
        END IF;
        SELECT * INTO presentation FROM public.ml_presentations row
         WHERE row.id = packet_row.presentation_id;
        RETURN jsonb_build_object(
            'review_assignment_id', packet_row.review_assignment_id,
            'presentation_id', packet_row.presentation_id,
            'acknowledgement_token', presentation.acknowledgement_token,
            'visible_packet', packet_row.visible_packet,
            'visible_packet_sha256', packet_row.visible_packet_sha256,
            'replayed', true
        );
    END IF;

    INSERT INTO public.ml_review_assignments (
        learning_surface_id, evidence_span_id, reviewer_principal_id,
        reviewer_role, blind_packet_sha256, taxonomy_version,
        blindness_policy_version, idempotency_key
    ) VALUES (
        'confidence_classification', evidence.id, p_reviewer_principal_id,
        p_reviewer_role, packet_hash, p_taxonomy_version,
        p_blindness_policy_version, p_idempotency_key
    ) RETURNING * INTO assignment;
    INSERT INTO public.ml_review_assignment_events (
        review_assignment_id, event_kind, actor_principal_id,
        idempotency_key, metadata
    ) VALUES (
        assignment.id, 'assigned', NULL, p_idempotency_key || ':assigned',
        jsonb_build_object('packet_version', 'confidence-blind-packet-v1')
    );
    INSERT INTO public.ml_presentations (
        canonical_event_id, learning_surface_id, review_assignment_id,
        actor_principal_id, actor_role, delivery_mode, evaluation_only,
        visible_payload_sha256, idempotency_key
    ) VALUES (
        candidate_set.canonical_event_id, 'confidence_classification',
        assignment.id, p_reviewer_principal_id, p_reviewer_role,
        p_delivery_mode, false, packet_hash, p_idempotency_key || ':presentation'
    ) RETURNING * INTO presentation;
    INSERT INTO public.ml_confidence_blind_packets (
        review_assignment_id, presentation_id, candidate_id,
        reviewer_principal_id, reviewer_role, packet_version,
        visible_packet, visible_packet_sha256
    ) VALUES (
        assignment.id, presentation.id, candidate.id,
        p_reviewer_principal_id, p_reviewer_role,
        'confidence-blind-packet-v1', packet, packet_hash
    ) RETURNING * INTO packet_row;

    RETURN jsonb_build_object(
        'review_assignment_id', assignment.id,
        'presentation_id', presentation.id,
        'acknowledgement_token', presentation.acknowledgement_token,
        'visible_packet', packet,
        'visible_packet_sha256', packet_hash,
        'replayed', false
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.submit_mlc2_confidence_blind_judgment_v1(
    p_review_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_exposure_id UUID,
    p_decision TEXT,
    p_decided_at TIMESTAMPTZ,
    p_idempotency_key TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    assignment public.ml_review_assignments%ROWTYPE;
    exposure   public.ml_rendered_exposures%ROWTYPE;
    judgment   public.ml_judgments%ROWTYPE;
    provenance TEXT;
    was_replay BOOLEAN := false;
BEGIN
    IF p_decision NOT IN (
        'rating_yes', 'rating_in_between', 'rating_no',
        'rating_not_sure', 'rating_audio_unclear'
    ) OR p_decided_at IS NULL
      OR NULLIF(btrim(p_idempotency_key), '') IS NULL THEN
        RAISE EXCEPTION 'invalid blind confidence judgment';
    END IF;
    SELECT * INTO assignment FROM public.ml_review_assignments row
     WHERE row.id = p_review_assignment_id
       AND row.learning_surface_id = 'confidence_classification'
       AND row.reviewer_principal_id = p_reviewer_principal_id
     FOR SHARE;
    IF assignment.id IS NULL OR EXISTS (
        SELECT 1 FROM public.ml_review_assignment_events event
         WHERE event.review_assignment_id = assignment.id
           AND event.event_kind = 'revealed'
    ) THEN
        RAISE EXCEPTION 'blind judgment assignment rejected';
    END IF;
    SELECT rendered.* INTO exposure
      FROM public.ml_rendered_exposures rendered
      JOIN public.ml_presentations presentation
        ON presentation.id = rendered.presentation_id
     WHERE rendered.id = p_exposure_id
       AND rendered.actor_principal_id = p_reviewer_principal_id
       AND presentation.review_assignment_id = assignment.id;
    IF exposure.id IS NULL THEN
        RAISE EXCEPTION 'blind judgment requires authenticated rendered exposure';
    END IF;
    provenance := CASE assignment.reviewer_role
        WHEN 'coach' THEN 'blind_coach' ELSE 'blind_peer' END;

    SELECT * INTO judgment FROM public.ml_judgments row
     WHERE row.idempotency_key = p_idempotency_key;
    IF judgment.id IS NULL THEN
        INSERT INTO public.ml_judgments (
            learning_surface_id, feedback_family_id, evidence_span_id,
            exposure_id, review_assignment_id, actor_principal_id,
            actor_provenance, decision, training_eligibility,
            idempotency_key, decided_at
        ) VALUES (
            'confidence_classification', 'confident_voice',
            assignment.evidence_span_id, exposure.id, assignment.id,
            p_reviewer_principal_id, provenance, p_decision,
            'potentially_eligible', p_idempotency_key, p_decided_at
        ) RETURNING * INTO judgment;
        INSERT INTO public.ml_review_assignment_events (
            review_assignment_id, event_kind, actor_principal_id,
            idempotency_key
        ) VALUES (
            assignment.id, 'submitted', p_reviewer_principal_id,
            p_idempotency_key || ':submitted'
        );
    ELSE
        was_replay := true;
        IF judgment.review_assignment_id <> assignment.id
          OR judgment.actor_principal_id <> p_reviewer_principal_id
          OR judgment.exposure_id <> exposure.id
          OR judgment.decision <> p_decision THEN
            RAISE EXCEPTION 'blind judgment idempotency conflict';
        END IF;
    END IF;
    RETURN jsonb_build_object(
        'judgment_id', judgment.id,
        'review_assignment_id', assignment.id,
        'decision', judgment.decision,
        'replayed', was_replay
    );
END;
$$;

CREATE OR REPLACE FUNCTION public.reveal_mlc2_confidence_review_v1(
    p_review_assignment_id UUID,
    p_reviewer_principal_id UUID,
    p_idempotency_key TEXT
) RETURNS public.ml_review_assignment_events
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    reveal_event public.ml_review_assignment_events;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_judgments judgment
         WHERE judgment.review_assignment_id = p_review_assignment_id
           AND judgment.actor_principal_id = p_reviewer_principal_id
           AND judgment.actor_provenance IN ('blind_coach', 'blind_peer')
    ) THEN
        RAISE EXCEPTION 'blind comparison requires an immutable judgment';
    END IF;
    SELECT * INTO reveal_event FROM public.reveal_ml_review_assignment_v1(
        p_review_assignment_id, p_reviewer_principal_id, p_idempotency_key
    );
    RETURN reveal_event;
END;
$$;

CREATE OR REPLACE FUNCTION public.get_mlc2_confidence_slice4_health_v1()
RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
SELECT jsonb_build_object(
    'learning_surface', 'confidence_classification',
    'producer_contract_version', 'confidence-producer-v1',
    'producer_activation', 'disabled_in_application_config',
    'pending_confidence_outbox_count', (
        SELECT count(*) FROM ml_outbox_events
         WHERE learning_surface_id = 'confidence_classification'
           AND event_type = 'confidence_take_ready'
           AND processed_at IS NULL
    ),
    'failed_confidence_outbox_count', (
        SELECT count(*) FROM ml_outbox_events
         WHERE learning_surface_id = 'confidence_classification'
           AND event_type = 'confidence_take_ready'
           AND processed_at IS NULL AND last_error_code IS NOT NULL
    ),
    'oldest_pending_confidence_outbox_at', (
        SELECT min(created_at) FROM ml_outbox_events
         WHERE learning_surface_id = 'confidence_classification'
           AND event_type = 'confidence_take_ready'
           AND processed_at IS NULL
    ),
    'receipt_without_outbox_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
         WHERE NOT EXISTS (
             SELECT 1 FROM ml_outbox_events event
              WHERE event.id = receipt.outbox_event_id
         )
    ),
    'processed_without_frame_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
        JOIN ml_outbox_events event ON event.id = receipt.outbox_event_id
         WHERE event.processed_at IS NOT NULL
           AND NOT EXISTS (
               SELECT 1 FROM ml_canonical_events canonical
               JOIN ml_candidate_sets candidate_set
                 ON candidate_set.canonical_event_id = canonical.id
                WHERE canonical.source_outbox_event_id = event.id
           )
    ),
    'blind_assignment_without_packet_count', (
        SELECT count(*) FROM ml_review_assignments assignment
         WHERE assignment.learning_surface_id = 'confidence_classification'
           AND NOT EXISTS (
               SELECT 1 FROM ml_confidence_blind_packets packet
                WHERE packet.review_assignment_id = assignment.id
           )
    ),
    'revealed_without_judgment_count', (
        SELECT count(*) FROM ml_review_assignment_events event
         WHERE event.event_kind = 'revealed'
           AND NOT EXISTS (
               SELECT 1 FROM ml_judgments judgment
                WHERE judgment.review_assignment_id = event.review_assignment_id
           )
    ),
    'dataset_creation_enabled', false,
    'training_enabled', false,
    'promotion_enabled', false
);
$$;

ALTER TABLE public.ml_confidence_producer_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ml_confidence_blind_packets ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.ml_confidence_producer_receipts
    FROM anon, authenticated;
REVOKE ALL ON TABLE public.ml_confidence_blind_packets
    FROM anon, authenticated;
GRANT SELECT ON TABLE public.ml_confidence_producer_receipts TO service_role;
GRANT SELECT ON TABLE public.ml_confidence_blind_packets TO service_role;

DROP TRIGGER IF EXISTS ml_confidence_producer_receipts_append_only
    ON public.ml_confidence_producer_receipts;
CREATE TRIGGER ml_confidence_producer_receipts_append_only
    BEFORE UPDATE OR DELETE ON public.ml_confidence_producer_receipts
    FOR EACH ROW EXECUTE FUNCTION public.reject_mlc2_immutable_mutation();
DROP TRIGGER IF EXISTS ml_confidence_blind_packets_append_only
    ON public.ml_confidence_blind_packets;
CREATE TRIGGER ml_confidence_blind_packets_append_only
    BEFORE UPDATE OR DELETE ON public.ml_confidence_blind_packets
    FOR EACH ROW EXECUTE FUNCTION public.reject_mlc2_immutable_mutation();

REVOKE ALL ON FUNCTION public.promote_recording_attempt_with_mlc2_confidence_v1(
    UUID, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, JSONB
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.promote_recording_attempt_with_mlc2_confidence_v1(
    UUID, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, JSONB
) TO service_role;
REVOKE ALL ON FUNCTION public.claim_mlc2_confidence_outbox_v1(
    TEXT, INTEGER, INTEGER
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_mlc2_confidence_outbox_v1(
    TEXT, INTEGER, INTEGER
) TO service_role;
REVOKE ALL ON FUNCTION public.create_mlc2_confidence_blind_packet_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_mlc2_confidence_blind_packet_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.submit_mlc2_confidence_blind_judgment_v1(
    UUID, UUID, UUID, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.submit_mlc2_confidence_blind_judgment_v1(
    UUID, UUID, UUID, TEXT, TIMESTAMPTZ, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.reveal_mlc2_confidence_review_v1(
    UUID, UUID, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reveal_mlc2_confidence_review_v1(
    UUID, UUID, TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.get_mlc2_confidence_slice4_health_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc2_confidence_slice4_health_v1()
    TO service_role;

COMMENT ON TABLE public.ml_confidence_producer_receipts IS
    'Atomic successful-Take plus confidence outbox receipts. Dark until a separately approved application flag change.';
COMMENT ON TABLE public.ml_confidence_blind_packets IS
    'Server-built answer-free confidence packets. Scores, ranks, model hints and prior judgments are structurally absent.';
COMMENT ON FUNCTION public.get_mlc2_confidence_slice4_health_v1() IS
    'Operational Slice-4 readiness only; datasets, training and promotion remain disabled.';

COMMIT;
