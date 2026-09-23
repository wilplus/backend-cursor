-- 0354 · Authorization binds to the principal that actually acquired the audio.
--
-- B-2 and B-3 (major) from the ML provenance audit of 2026-09-22, plus the
-- app-side half of B-11, which ships in services/processing_authorization.py.
--
-- ONE DEFECT WEARING TWO NAMES. Phase-1 lineage rests on a single claim: the
-- principal named on a permit is the principal that acquired the recording.
-- Two functions let that claim be false, from opposite ends.
--
--   B-2  issue_phase1_provider_permit_v1 never checked that the take or
--        recording it was handed belonged to the principal whose receipt it
--        was reading. The auditor minted a permit for one guest's recording
--        under another principal's receipt; the snapshot table then held two
--        rows for that recording naming different principals.
--
--   B-3  resolve_phase1_acquisition_principal_v1 returned a claim's SOURCE
--        only when that source already held a receipt, and otherwise returned
--        the TARGET. A guest who recorded while the gate was off holds no
--        receipt by construction, so after they signed up every one of their
--        recordings resolved to the new account principal — whose receipt was
--        signed later, by a different principal row, for an acquisition that
--        had already happened.
--
-- Together they are the same hole: authorization evidence could be attached
-- to audio it was never given for.
--
-- WHAT THIS DOES NOT DO. It does not refuse anything a correct caller could
-- do before. B-2 adds a check that passes for every source the acquisition
-- principal owns or was claimed from, and stays silent where ownership cannot
-- be proved at all rather than refusing on absent evidence. B-3 turns a WHERE
-- filter into an ORDER BY preference, so the resolver returns exactly what it
-- returned before whenever any claim source holds a receipt; the change is
-- only in the case where none does, which previously returned the wrong
-- principal. A person whose acquisition now resolves to their old guest
-- principal is asked to accept the policy for it, and the receipt lands where
-- the audio actually came from. The loop keeps running.
--
-- ADDITIVE AND IDEMPOTENT. Two CREATE OR REPLACE FUNCTIONs and the restated
-- grants they already carry. No table, column, row or grant is created,
-- altered or dropped, and no role gains anything. Every path other than the
-- one named in each comment is byte-identical to what runs today.

CREATE OR REPLACE FUNCTION public.resolve_phase1_acquisition_principal_v1(
    p_product_owner_principal_id UUID,
    p_user_id UUID DEFAULT NULL
) RETURNS UUID
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE resolved UUID;
BEGIN
    IF p_product_owner_principal_id IS NULL THEN
        RAISE EXCEPTION 'PROCESSING_PRINCIPAL_UNRESOLVED';
    END IF;
    -- B-3 (audit 2026-09-22): the receipt-existence condition used to sit
    -- inside this WHERE clause, so a claim whose SOURCE
    -- held no receipt fell through to COALESCE and returned the TARGET. That
    -- is the account principal, whose receipt post-dates the acquisition by
    -- definition — every recording made while the gate was off could be
    -- processed under a receipt signed later, by a different principal row.
    -- The claim event is the audited fact; a receipt is not what makes a
    -- principal the acquirer.
    --
    -- Receipt existence survives as a PREFERENCE, not a filter, so the answer
    -- is unchanged for every claim whose source does hold one: `ORDER BY
    -- has_receipt DESC` still picks the newest source with a receipt exactly
    -- as before. It only decides which source wins when none of them has one,
    -- where the old clause returned the target instead of any of them.
    SELECT event.source_owner_principal_id INTO resolved
      FROM public.owner_claim_events event
     WHERE event.target_owner_principal_id = p_product_owner_principal_id
       AND (p_user_id IS NULL OR event.claimed_user_id = p_user_id)
     ORDER BY EXISTS (
           SELECT 1 FROM public.processing_authorization_receipts receipt
            WHERE receipt.acquisition_principal_id =
                  event.source_owner_principal_id
       ) DESC,
       event.claimed_at DESC, event.id DESC
     LIMIT 1;
    RETURN COALESCE(resolved, p_product_owner_principal_id);
END;
$$;

-- CREATE OR REPLACE preserves a function's ACL; these restate what 0313
-- already granted. Written out because a migration that creates a function
-- must say in its own text who may call it, and because a reader auditing the
-- permit writer should not have to open another file to learn it is
-- service_role-only.
REVOKE ALL ON FUNCTION public.resolve_phase1_acquisition_principal_v1(UUID,UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_phase1_acquisition_principal_v1(UUID,UUID)
    TO service_role;

CREATE OR REPLACE FUNCTION public.issue_phase1_provider_permit_v1(
    p_acquisition_principal_id UUID, p_source_take_id UUID,
    p_source_recording_id UUID, p_provider TEXT, p_operation_kind TEXT,
    p_pseudonymous_subject_ref TEXT, p_minimum_data_manifest JSONB,
    p_idempotency_key TEXT, p_ttl_seconds INTEGER DEFAULT 900
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    auth JSONB;
    receipt processing_authorization_receipts;
    purpose TEXT;
    snapshot_id UUID;
    permit processing_provider_permits;
    authority_hash TEXT;
    carryover processing_job_carryovers;
    source_job phase1_processing_jobs;
    source_principal UUID;
    session_owner UUID;
BEGIN
    -- B-2 (audit 2026-09-22). THIS FUNCTION READ THE AUTHORIZATION OF ONE
    -- PRINCIPAL AND STAMPED IT ONTO ANOTHER PRINCIPAL'S RECORDING. It checked
    -- that p_acquisition_principal_id holds a receipt and then inserted
    -- p_source_take_id / p_source_recording_id verbatim, with no statement
    -- anywhere that those coordinates were that principal's to name. The
    -- auditor minted a permit for P1's recording under P2's receipt, and
    -- processing_authorization_snapshots then held two rows for one recording
    -- naming different principals. Nothing downstream can tell which one is
    -- the truth: the permit lineage attests that the later account authorized
    -- the earlier acquisition.
    --
    -- The check runs FIRST, before the authorization read, so a caller cannot
    -- learn anything about another principal's authorization state by probing
    -- with their recording id.
    IF p_source_recording_id IS NOT NULL THEN
        SELECT attempt.acquisition_principal_id INTO source_principal
          FROM processing_recording_attempts attempt
         WHERE attempt.recording_id = p_source_recording_id;
    END IF;
    IF source_principal IS NOT NULL THEN
        -- The attempt row is the acquisition record itself. It is written
        -- once, at intake, and is authoritative wherever it exists.
        IF source_principal <> p_acquisition_principal_id THEN
            RAISE EXCEPTION 'PROCESSING_SOURCE_PRINCIPAL_MISMATCH';
        END IF;
    ELSIF p_source_take_id IS NOT NULL THEN
        -- No attempt row: every recording acquired while the gate was off.
        -- Product ownership is the only statement left, and claim_guest_owner
        -- rewrites v2_sessions.owner_principal_id when a guest signs up, so
        -- the acquirer is either the session's current owner or a principal
        -- claimed INTO it. Both are accepted; a third principal is not.
        --
        -- A source we cannot place is left alone rather than refused: a
        -- missing session row is an absence of evidence, and turning it into
        -- a refusal would take the live loop down for a data gap this
        -- function did not create. What is provable is enforced; what is not
        -- provable is not invented.
        SELECT take.owner_principal_id INTO session_owner
          FROM v2_sessions take WHERE take.id = p_source_take_id;
        IF session_owner IS NOT NULL
           AND session_owner <> p_acquisition_principal_id
           AND NOT EXISTS (
               SELECT 1 FROM owner_claim_events event
                WHERE event.target_owner_principal_id = session_owner
                  AND event.source_owner_principal_id =
                      p_acquisition_principal_id
           )
        THEN RAISE EXCEPTION 'PROCESSING_SOURCE_PRINCIPAL_MISMATCH'; END IF;
    END IF;

    auth := get_phase1_processing_authorization_v1(p_acquisition_principal_id);
    IF NOT COALESCE((auth->>'authorized')::boolean, false) THEN
        IF p_operation_kind NOT IN (
            'audio_download', 'transcription', 'feedback_generation',
            'ideal_text_generation'
        ) THEN
            RAISE EXCEPTION '%', COALESCE(
                auth->>'code', 'PROCESSING_AUTHORIZATION_REQUIRED'
            );
        END IF;
        SELECT j.* INTO source_job
          FROM phase1_processing_jobs j
          JOIN processing_recording_attempts a
            ON a.id = j.recording_attempt_id
         WHERE j.acquisition_principal_id = p_acquisition_principal_id
           AND a.recording_id = p_source_recording_id
           AND j.job_kind = 'recording_transcription_ranking_feedback'
           AND j.status IN ('pending', 'processing')
         ORDER BY j.created_at DESC LIMIT 1;
        IF source_job.id IS NOT NULL THEN
            SELECT c.* INTO carryover
              FROM processing_job_carryovers c
             WHERE c.processing_job_id = source_job.id
               AND c.acquisition_principal_id = p_acquisition_principal_id
               AND c.exact_operation =
                   'recording_transcription_ranking_feedback'
               AND c.cancelled_at IS NULL
               AND c.cutoff_at <= now() AND c.expires_at > now()
             ORDER BY c.created_at DESC LIMIT 1;
        END IF;
        IF carryover.id IS NULL THEN
            RAISE EXCEPTION '%', COALESCE(
                auth->>'code', 'PROCESSING_AUTHORIZATION_REQUIRED'
            );
        END IF;
    END IF;
    IF p_ttl_seconds < 30 OR p_ttl_seconds > 3600 THEN
        RAISE EXCEPTION 'INVALID_PERMIT_TTL';
    END IF;
    purpose := CASE p_operation_kind
        WHEN 'audio_download' THEN 'recording_voice_processing'
        WHEN 'transcription' THEN 'transcription_feedback'
        WHEN 'feedback_generation' THEN 'transcription_feedback'
        WHEN 'ideal_text_generation' THEN 'transcription_feedback'
        WHEN 'coach_delivery' THEN 'coach_review'
        ELSE NULL END;
    IF purpose IS NULL THEN RAISE EXCEPTION 'INVALID_PROVIDER_OPERATION'; END IF;
    IF COALESCE((auth->>'authorized')::boolean, false) THEN
        SELECT * INTO receipt FROM processing_authorization_receipts
         WHERE id = (auth->>'receipt_id')::uuid;
    ELSE
        SELECT r.* INTO receipt
          FROM processing_authorization_snapshots s
          JOIN processing_authorization_receipts r ON r.id = s.receipt_id
         WHERE s.id = source_job.authorization_snapshot_id;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM processing_authorization_receipt_purposes
         WHERE receipt_id = receipt.id AND purpose_id = purpose
    ) THEN RAISE EXCEPTION 'PROCESSING_PURPOSE_NOT_AUTHORIZED'; END IF;

    authority_hash := encode(extensions.digest(concat_ws(':', receipt.id::text,
        p_source_take_id::text, p_source_recording_id::text,
        p_provider, p_operation_kind, p_idempotency_key), 'sha256'), 'hex');
    INSERT INTO processing_authorization_snapshots (
        acquisition_principal_id, receipt_id, policy_id, purpose_id,
        operation_kind, source_take_id, source_recording_id,
        authority_evidence_sha256, pooled_learning_eligible
    ) VALUES (
        p_acquisition_principal_id, receipt.id, receipt.policy_id, purpose,
        p_operation_kind, p_source_take_id, p_source_recording_id,
        authority_hash, false
    ) RETURNING id INTO snapshot_id;
    INSERT INTO processing_provider_permits (
        acquisition_principal_id, authorization_snapshot_id, provider,
        operation_kind, pseudonymous_subject_ref, minimum_data_manifest,
        expires_at, idempotency_key
    ) VALUES (
        p_acquisition_principal_id, snapshot_id, p_provider,
        p_operation_kind, p_pseudonymous_subject_ref,
        p_minimum_data_manifest, now() + make_interval(secs => p_ttl_seconds),
        p_idempotency_key
    ) ON CONFLICT (idempotency_key) DO NOTHING;
    SELECT * INTO permit FROM processing_provider_permits
     WHERE idempotency_key = p_idempotency_key;
    IF permit.acquisition_principal_id <> p_acquisition_principal_id
       OR permit.operation_kind <> p_operation_kind THEN
        RAISE EXCEPTION 'IDEMPOTENCY_CONFLICT';
    END IF;
    RETURN jsonb_build_object(
        'permit_id', permit.id, 'provider', permit.provider,
        'operation_kind', permit.operation_kind,
        'expires_at', permit.expires_at,
        'authorization_snapshot_id', permit.authorization_snapshot_id
    );
END;
$$;

REVOKE ALL ON FUNCTION public.issue_phase1_provider_permit_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT,JSONB,TEXT,INTEGER
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.issue_phase1_provider_permit_v1(
    UUID,UUID,UUID,TEXT,TEXT,TEXT,JSONB,TEXT,INTEGER
) TO service_role;
