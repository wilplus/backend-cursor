-- 0430 · The confidence chain hears the training yes and the coach's walk
--        (founder 2026-10-05, decisions log N48.5 Q27 A: "the
--        confidence-learning chain is connected: one consent authority (the
--        training yes) and the coach walk's blind labels as its judgements;
--        training stays closed"; N2 / C2, N10 item 6: bundled-era yeses
--        count for nothing).
--
-- ONE CONSENT AUTHORITY. The chain asked the bundled v1 reader
-- (get_mlc2_principal_consent_status_v1, 0306/0377) whether a person may
-- enter it, and the canonical promotion froze a snapshot of the bundled
-- two-purpose grant (create_mlc2_consent_snapshot_v1, 0302). Two "yes"
-- records gated two learning lanes. From here the only authority is the
-- training yes, read through get_mlc2_training_consent_status_v2 (0373):
--
--   ring_consent_is_current_v1        pooled_model_improvement = an active
--                                     training yes AND a bound speaker (the
--                                     two things the bundled reader's
--                                     "granted" meant). The personalised
--                                     practice branch is byte for byte 0394's.
--   ring_consent_policy_exists_v1     pooled_model_improvement = an active
--                                     training_only policy exists.
--   create_mlc2_training_consent_snapshot_v1
--                                     NEW: the per-Take snapshot, taken from
--                                     the training grant (one purpose); the
--                                     table's CHECK keeps both keys, so the
--                                     coaching key says, truthfully, that this
--                                     grant does not authorise it.
--   promote_recording_attempt_with_mlc2_confidence_v1
--                                     re-issued from 0392: it takes and reads
--                                     only a TRAINING snapshot. A bundled
--                                     snapshot, pre-made or not, admits
--                                     nothing.
--   get_ring_confidence_readiness_v1  re-issued from 0394 with two counts
--                                     added (training yes; yes without a
--                                     bound speaker). The bundled count stays,
--                                     for the record.
--   get_mlc2_confidence_canary_readiness_v1
--                                     re-issued from 0377 with the training
--                                     policy's two counts added.
--
-- A LATENT FAULT THIS FIXES, FOR THE CHAIN ONLY. 0394 guarded each consent
-- door with to_regproc('public.<reader>(uuid)'). to_regproc takes a bare
-- name; with an argument list it answers NULL on every PostgreSQL version,
-- so the guard always returned false and the consent half of the rule
-- never said yes. Since take_lifecycle began asking the ring row
-- (2026-10-03) no Take has entered the canonical promotion. The
-- pooled_model_improvement branch now uses to_regprocedure. The
-- personalised_practice branch keeps 0394's text unchanged on purpose: it
-- gates the exercise_service row, whose loop is retired (L8), and opening
-- it is not this decision. It is reported to the founder instead.
--
-- THE SPEAKER IS BOUND THROUGH THE TRAINING YES (F-3).
--   bind_mlc2_training_speaker_v1     NEW: binds a verified account identity
--                                     to its principal, only while that
--                                     principal holds an active training yes;
--                                     an existing binding is kept (a
--                                     principal is never rebound). The
--                                     speaker gets its 80/10/10 assignment in
--                                     the same call (register_ml_speaker_
--                                     principal_v1, 0302).
--   accept_mlc2_training_consent_v1   NEW: the training switch's yes and the
--                                     binding in one transaction. Every
--                                     refusal of record_mlc2_training_
--                                     consent_grant_v2 (its own act, C1's
--                                     receipt, the approved copy) stands, and
--                                     a refused yes binds nobody.
--   get_mlc2_speaker_splits_v1        NEW, read-only: each principal's bound
--                                     speaker's assignment, the split doors 2
--                                     and 3 read (services/speaker_split.py).
--
-- THE WALK'S BLIND LABEL, AS THE CHAIN READS IT BACK (DA-PROHIBIT).
--   get_mlc2_blind_coach_ratings_v1   NEW, read-only: the latest blind_coach
--                                     judgement per snippet of one Take, from
--                                     ml_judgments, for the dark training-
--                                     corpus copy job, which stops reading the
--                                     mixed-purpose confidence_labels.
--
-- EVERY DOWNLOAD OR RELEASE CHECK APPENDS A VERIFICATION (F-8). The
-- foundation's ml_object_verifications had no writer at all.
--   record_mlc2_object_verification_v1
--                                     NEW: one row per check of a chain
--                                     object; the database, not the caller,
--                                     decides "verified" against the
--                                     artifact's immutable hash and size. A
--                                     key that is no chain object writes
--                                     nothing.
--   list_mlc2_objects_due_verification_v1
--                                     NEW, read-only: the weekly check's
--                                     capped work list.
--   pair_release_verifications        NEW TABLE, append-only (0302's trigger
--                                     function), RLS on, service-role SELECT
--                                     only: door 2's file is the only data
--                                     that leaves and spans many speakers, so
--                                     it cannot be one chain object.
--   record_pair_release_verification_v1
--                                     NEW: one row per object per release
--                                     check (the read-after-write at export
--                                     and the weekly check).
--
-- STAYS CLOSED. Nothing here trains, releases a dataset or promotes a model
-- (MLC2_TRAINING_ENABLED, MLC2_DATASET_RELEASES_ENABLED,
-- MLC2_PROMOTION_ENABLED, DETECTOR_TRAINING_AUTHORISED stay False in code;
-- K10, K11, K12, TC-4.x untouched). The writer state stays the code
-- constant it is. No reach changes: the confidence_learning_writes row
-- still reaches ring 5 only, and moving it is the founder's panel act. No
-- owner answer, peer rating or machine read becomes a judgement (L3).
--
-- Additive and idempotent: CREATE OR REPLACE for every function, and one
-- new table created IF NOT EXISTS with its index, RLS, grants and trigger
-- (the trigger only when absent). No existing table, column or row is
-- altered or removed, no environment variable read (CONFIG-FIRST). One
-- transaction.

BEGIN;

-- ── One consent authority: the ring's consent door ─────────────────────────

-- Whether the named consent is current for this person. READ ONLY, and
-- through the doors that already exist: the Phase-1 tick, or the training
-- yes (0430; the bundled grant no longer answers). A door this database
-- does not have, an unknown principal or a policy in an invalid state all
-- answer false (closed).
CREATE OR REPLACE FUNCTION public.ring_consent_is_current_v1(
    p_principal UUID,
    p_purpose TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    answer JSONB;
BEGIN
    IF p_principal IS NULL OR p_purpose IS NULL THEN
        RETURN false;
    END IF;
    IF p_purpose = 'personalised_practice' THEN
        IF to_regproc('public.get_phase1_consent_choices_v1(uuid)') IS NULL THEN
            RETURN false;
        END IF;
        BEGIN
            EXECUTE 'SELECT public.get_phase1_consent_choices_v1($1)'
               INTO answer USING p_principal;
        EXCEPTION WHEN OTHERS THEN
            RETURN false;
        END;
        RETURN COALESCE((answer ->> 'has_receipt')::boolean, false)
           AND COALESCE((answer ->> 'personalised_practice')::boolean, false);
    ELSIF p_purpose = 'pooled_model_improvement' THEN
        -- 0430 (N48.5 Q27 A): the one authority is the training yes. A
        -- bundled-era grant counts for nothing (N2, N10.6). The speaker
        -- binding is the half the bundled reader's "granted" also required:
        -- the canonical promotion cannot bind a Take without it.
        IF to_regprocedure('public.get_mlc2_training_consent_status_v2(uuid)')
           IS NULL
           OR to_regclass('public.ml_speaker_principals') IS NULL THEN
            RETURN false;
        END IF;
        BEGIN
            EXECUTE 'SELECT public.get_mlc2_training_consent_status_v2($1)'
               INTO answer USING p_principal;
        EXCEPTION WHEN OTHERS THEN
            RETURN false;
        END;
        IF NOT COALESCE((answer ->> 'active')::boolean, false) THEN
            RETURN false;
        END IF;
        RETURN EXISTS (
            SELECT 1 FROM public.ml_speaker_principals binding
             WHERE binding.acquisition_principal_id = p_principal);
    END IF;
    RETURN false;
END;
$$;
REVOKE ALL ON FUNCTION public.ring_consent_is_current_v1(UUID, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ring_consent_is_current_v1(UUID, TEXT)
    TO service_role;

-- Whether the legal policy behind a consent purpose exists yet. The panel's
-- "yes" for a Phase-2 purpose stays disabled until this says true. Reads
-- only; registers nothing. 0430: for pooled model improvement that policy
-- is the training-only one.
CREATE OR REPLACE FUNCTION public.ring_consent_policy_exists_v1(
    p_purpose TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    found BOOLEAN := false;
BEGIN
    IF p_purpose = 'personalised_practice' THEN
        IF to_regclass('public.processing_policy_versions') IS NULL THEN
            RETURN false;
        END IF;
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.processing_policy_versions '
                || 'WHERE status = ''active'' AND activated_at <= now() '
                || 'AND (retired_at IS NULL OR retired_at > now()))'
           INTO found;
        RETURN found;
    ELSIF p_purpose = 'pooled_model_improvement' THEN
        IF to_regclass('public.ml_consent_policies') IS NULL THEN
            RETURN false;
        END IF;
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.ml_consent_policies '
                || 'WHERE active_from <= now() '
                || 'AND (retired_at IS NULL OR retired_at > now()) '
                || 'AND grant_scope = ''training_only'')'
           INTO found;
        RETURN found;
    END IF;
    RETURN false;
END;
$$;
REVOKE ALL ON FUNCTION public.ring_consent_policy_exists_v1(TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ring_consent_policy_exists_v1(TEXT)
    TO service_role;

-- ── The per-Take snapshot, from the training grant ────────────────────────

-- The consent state a canonical Take is promoted under, frozen. Same
-- ownership checks and fingerprint construction as
-- create_mlc2_consent_snapshot_v1 (0302), which stays for the record and is
-- no longer called by the promotion. The table's CHECK asks for both purpose
-- keys; the training grant authorises one, so the coaching key records that
-- this grant does not authorise it (coaching runs under the Phase-1
-- processing authorisation, never under this grant).
CREATE OR REPLACE FUNCTION public.create_mlc2_training_consent_snapshot_v1(
    p_acquisition_principal_id UUID,
    p_recording_attempt_id UUID,
    p_take_id UUID,
    p_project_id UUID
) RETURNS public.ml_consent_snapshots
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = extensions, public
AS $$
DECLARE
    status JSONB;
    grant_event public.ml_consent_events;
    pooled public.ml_consent_event_purposes;
    state JSONB;
    fingerprint TEXT;
    snapshot public.ml_consent_snapshots;
BEGIN
    IF p_acquisition_principal_id IS NULL THEN
        RAISE EXCEPTION 'acquisition principal is required';
    END IF;
    IF p_recording_attempt_id IS NULL AND p_take_id IS NULL THEN
        RAISE EXCEPTION 'a recording attempt or a Take is required';
    END IF;
    IF p_recording_attempt_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.recording_attempts attempt
         WHERE attempt.id = p_recording_attempt_id
           AND attempt.owner_principal_id = p_acquisition_principal_id
           AND (p_project_id IS NULL OR attempt.project_id = p_project_id)
    ) THEN
        RAISE EXCEPTION 'recording attempt does not belong to acquisition principal';
    END IF;
    IF p_take_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.takes take_row
         WHERE take_row.id = p_take_id
           AND take_row.owner_principal_id = p_acquisition_principal_id
           AND (p_project_id IS NULL OR take_row.project_id = p_project_id)
    ) THEN
        RAISE EXCEPTION 'Take does not belong to acquisition principal';
    END IF;

    status := public.get_mlc2_training_consent_status_v2(
        p_acquisition_principal_id);
    IF NOT COALESCE((status ->> 'active')::boolean, false) THEN
        RAISE EXCEPTION 'no active training yes';
    END IF;
    SELECT event.* INTO grant_event
      FROM public.ml_consent_events event
      JOIN public.ml_consent_policies policy
        ON policy.version = event.consent_policy_version
     WHERE event.id = (status ->> 'grant_event_id')::uuid
       AND event.acquisition_principal_id = p_acquisition_principal_id
       AND event.event_kind = 'grant'
       AND policy.grant_scope = 'training_only';
    SELECT purpose.* INTO pooled
      FROM public.ml_consent_event_purposes purpose
     WHERE purpose.consent_event_id = grant_event.id
       AND purpose.purpose = 'pooled_model_improvement';
    IF grant_event.id IS NULL OR pooled.consent_event_id IS NULL THEN
        RAISE EXCEPTION 'no active training yes';
    END IF;

    state := jsonb_build_object(
        'pooled_model_improvement', jsonb_build_object(
            'authorized', true,
            'article_6_basis', pooled.article_6_basis,
            'article_9_basis', pooled.article_9_basis,
            'grant_scope', 'training_only'
        ),
        'personalized_coaching', jsonb_build_object(
            'authorized', false,
            'governed_by', 'phase1_processing_authorization'
        )
    );

    fingerprint := encode(digest(concat_ws(':',
        grant_event.id::text,
        p_acquisition_principal_id::text,
        COALESCE(p_recording_attempt_id::text, ''),
        COALESCE(p_take_id::text, ''),
        COALESCE(p_project_id::text, ''),
        state::text
    ), 'sha256'), 'hex');

    INSERT INTO public.ml_consent_snapshots (
        acquisition_principal_id, grant_event_id, consent_policy_version,
        recording_attempt_id, take_id, project_id, purpose_state,
        retention_state, snapshot_sha256
    ) VALUES (
        p_acquisition_principal_id, grant_event.id,
        grant_event.consent_policy_version, p_recording_attempt_id,
        p_take_id, p_project_id, state, 'eligible', fingerprint
    ) ON CONFLICT (snapshot_sha256) DO NOTHING;

    SELECT * INTO snapshot FROM public.ml_consent_snapshots
     WHERE snapshot_sha256 = fingerprint;
    RETURN snapshot;
END;
$$;
REVOKE ALL ON FUNCTION public.create_mlc2_training_consent_snapshot_v1(
    UUID, UUID, UUID, UUID
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.create_mlc2_training_consent_snapshot_v1(
    UUID, UUID, UUID, UUID
) TO service_role;

-- ── The canonical promotion reads the training snapshot (from 0392) ───────

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
    -- now from the current training yes (0430, N48.5 Q27 A: the bundled
    -- grant admits nothing). Without a yes the snapshot RPC raises and the
    -- whole promotion rolls back with it, so a Take is never promoted
    -- canonically without the consent it needs.
    IF NOT EXISTS (
        SELECT 1 FROM public.ml_consent_snapshots snapshot
          JOIN public.ml_consent_policies policy
            ON policy.version = snapshot.consent_policy_version
         WHERE snapshot.recording_attempt_id = attempt.id
           AND snapshot.acquisition_principal_id = attempt.owner_principal_id
           AND policy.grant_scope = 'training_only'
           AND snapshot.retention_state = 'eligible'
           AND NOT EXISTS (
               SELECT 1 FROM public.ml_consent_events withdrawal
                WHERE withdrawal.event_kind = 'withdraw'
                  AND withdrawal.supersedes_event_id = snapshot.grant_event_id
           )
    ) THEN
        PERFORM public.create_mlc2_training_consent_snapshot_v1(
            attempt.owner_principal_id, attempt.id, NULL, attempt.project_id
        );
    END IF;

    SELECT snapshot.id INTO consent_id
      FROM public.ml_consent_snapshots snapshot
      JOIN public.ml_consent_policies policy
        ON policy.version = snapshot.consent_policy_version
     WHERE snapshot.recording_attempt_id = attempt.id
       AND snapshot.acquisition_principal_id = attempt.owner_principal_id
       AND policy.grant_scope = 'training_only'
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

-- ── The speaker, bound through the training yes (F-3) ─────────────────────

-- Bind one verified account identity to its principal, only while that
-- principal holds an active training yes. An existing binding is returned
-- as it is: a principal is never rebound and a yes is never refused over
-- it. Without a yes nothing is written and NULL is returned. The identity
-- and proof are computed by the caller from the verified token (the same
-- construction as the retired bundled route), never sent by a browser.
CREATE OR REPLACE FUNCTION public.bind_mlc2_training_speaker_v1(
    p_acquisition_principal_id UUID,
    p_identity_hash TEXT,
    p_identity_version TEXT,
    p_binding_proof_hash TEXT,
    p_bound_by TEXT
) RETURNS public.ml_speaker_principals
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    status JSONB;
    binding public.ml_speaker_principals;
BEGIN
    IF p_acquisition_principal_id IS NULL
       OR NULLIF(btrim(p_identity_version), '') IS NULL
       OR NULLIF(btrim(p_bound_by), '') IS NULL THEN
        RAISE EXCEPTION 'TRAINING_SPEAKER_INPUT_INVALID';
    END IF;
    SELECT * INTO binding FROM public.ml_speaker_principals
     WHERE acquisition_principal_id = p_acquisition_principal_id;
    IF binding.id IS NOT NULL THEN
        RETURN binding;
    END IF;
    status := public.get_mlc2_training_consent_status_v2(
        p_acquisition_principal_id);
    IF NOT COALESCE((status ->> 'active')::boolean, false) THEN
        RETURN NULL;
    END IF;
    SELECT * INTO binding FROM public.register_ml_speaker_principal_v1(
        p_acquisition_principal_id, p_identity_hash, p_identity_version,
        'verified_account_link', p_binding_proof_hash, p_bound_by,
        'speaker-sha256-80-10-10-v1'
    );
    RETURN binding;
END;
$$;
REVOKE ALL ON FUNCTION public.bind_mlc2_training_speaker_v1(
    UUID, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.bind_mlc2_training_speaker_v1(
    UUID, TEXT, TEXT, TEXT, TEXT
) TO service_role;

-- The training switch's yes and the speaker binding, one transaction. The
-- yes is recorded first, through the only training writer, so every one of
-- its refusals stands and a refused yes binds nobody.
CREATE OR REPLACE FUNCTION public.accept_mlc2_training_consent_v1(
    p_acquisition_principal_id UUID,
    p_consent_policy_version TEXT,
    p_jurisdiction TEXT,
    p_terms_version TEXT,
    p_privacy_policy_version TEXT,
    p_source_route TEXT,
    p_client_version TEXT,
    p_affirmative_action JSONB,
    p_occurred_at TIMESTAMPTZ,
    p_idempotency_key TEXT,
    p_identity_hash TEXT,
    p_identity_version TEXT,
    p_binding_proof_hash TEXT,
    p_bound_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    consent_event public.ml_consent_events;
    binding public.ml_speaker_principals;
BEGIN
    SELECT * INTO consent_event
      FROM public.record_mlc2_training_consent_grant_v2(
        p_acquisition_principal_id, p_consent_policy_version, p_jurisdiction,
        p_terms_version, p_privacy_policy_version, p_source_route,
        p_client_version, p_affirmative_action, p_occurred_at,
        p_idempotency_key
    );
    binding := public.bind_mlc2_training_speaker_v1(
        p_acquisition_principal_id, p_identity_hash, p_identity_version,
        p_binding_proof_hash, p_bound_by
    );
    RETURN jsonb_build_object(
        'consent_event_id', consent_event.id,
        'binding_id', binding.id,
        'speaker_id', binding.speaker_id,
        'speaker_bound', binding.id IS NOT NULL,
        'accepted', true
    );
END;
$$;
REVOKE ALL ON FUNCTION public.accept_mlc2_training_consent_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT,
    TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_mlc2_training_consent_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT,
    TEXT, TEXT, TEXT, TEXT
) TO service_role;

-- ── The walk's blind label, read back from the chain (DA-PROHIBIT) ────────

-- The latest blind coach judgement per snippet of one Take, from the
-- chain's own immutable judgements: provenance blind_coach on the
-- confidence surface, reached through the blind packet that was rendered
-- before it. Read-only. Owner answers, peer ratings and machine reads are
-- never in it (L3).
CREATE OR REPLACE FUNCTION public.get_mlc2_blind_coach_ratings_v1(
    p_take_id UUID,
    p_snippet_ids UUID[]
) RETURNS TABLE (
    snippet_id UUID,
    decision TEXT,
    judgment_id UUID,
    decided_at TIMESTAMPTZ
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT DISTINCT ON (candidate.clip_id)
           candidate.clip_id, judgment.decision, judgment.id,
           judgment.decided_at
      FROM public.ml_judgments judgment
      JOIN public.ml_confidence_blind_packets packet
        ON packet.review_assignment_id = judgment.review_assignment_id
      JOIN public.ml_candidates candidate
        ON candidate.id = packet.candidate_id
      JOIN public.ml_candidate_sets candidate_set
        ON candidate_set.id = candidate.candidate_set_id
     WHERE p_take_id IS NOT NULL
       AND candidate_set.take_id = p_take_id
       AND candidate.clip_id = ANY(COALESCE(p_snippet_ids, ARRAY[]::uuid[]))
       AND judgment.actor_provenance = 'blind_coach'
       AND judgment.learning_surface_id = 'confidence_classification'
       AND packet.reviewer_role = 'coach'
       AND NOT EXISTS (
           SELECT 1 FROM public.ml_judgments later
            WHERE later.supersedes_id = judgment.id
       )
     ORDER BY candidate.clip_id, judgment.decided_at DESC, judgment.id DESC
$$;
REVOKE ALL ON FUNCTION public.get_mlc2_blind_coach_ratings_v1(UUID, UUID[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc2_blind_coach_ratings_v1(UUID, UUID[])
    TO service_role;

-- ── Readiness reads the training yes (from 0394 and 0377) ─────────────────

-- Readiness for the confidence chain, read against the RING rows instead of
-- the retired founder email and principal variable. Aggregate counts only,
-- never a recording, a transcript or a packet. Every learning table is
-- guarded: a database without it (a narrow lane) reports 0 and says so
-- with `tables_present`. 0430: the training yes is the count readiness
-- gates on; the bundled count stays in the payload as a record.
CREATE OR REPLACE FUNCTION public.get_ring_confidence_readiness_v1()
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    confidence_row feature_rings;
    canonical_row feature_rings;
    eligible UUID[];
    eligible_count INTEGER := 0;
    eligible_grants INTEGER := 0;
    eligible_training INTEGER := 0;
    eligible_training_unbound INTEGER := 0;
    eligible_receipts INTEGER := 0;
    other_receipts INTEGER := 0;
    other_events INTEGER := 0;
    has_consent BOOLEAN := to_regclass('public.ml_consent_events') IS NOT NULL
        AND to_regclass('public.ml_consent_policies') IS NOT NULL
        AND to_regclass('public.ml_consent_event_purposes') IS NOT NULL;
    has_training BOOLEAN := to_regprocedure(
        'public.get_mlc2_training_consent_status_v2(uuid)') IS NOT NULL
        AND to_regclass('public.ml_speaker_principals') IS NOT NULL;
    has_receipts BOOLEAN :=
        to_regclass('public.ml_confidence_producer_receipts') IS NOT NULL;
    has_events BOOLEAN := to_regclass('public.ml_canonical_events') IS NOT NULL;
BEGIN
    SELECT * INTO confidence_row FROM feature_rings
     WHERE feature = 'confidence_learning_writes';
    SELECT * INTO canonical_row FROM feature_rings
     WHERE feature = 'canonical_take_rows';
    SELECT COALESCE(array_agg(p), '{}'::uuid[]) INTO eligible
      FROM ring_eligible_principals_v1('confidence_learning_writes') AS p;
    eligible_count := cardinality(eligible);
    IF has_consent THEN
        EXECUTE $q$
            SELECT count(*) FROM public.ml_consent_events consent_event
              JOIN public.ml_consent_policies policy
                ON policy.version = consent_event.consent_policy_version
             WHERE consent_event.acquisition_principal_id = ANY($1)
               AND consent_event.event_kind = 'grant'
               AND policy.active_from <= now()
               AND (policy.retired_at IS NULL OR policy.retired_at > now())
               AND NOT EXISTS (
                   SELECT 1 FROM public.ml_consent_events withdrawal
                    WHERE withdrawal.event_kind = 'withdraw'
                      AND withdrawal.supersedes_event_id = consent_event.id
                      AND withdrawal.occurred_at <= now())
               AND (SELECT count(*) FROM public.ml_consent_event_purposes purpose
                     WHERE purpose.consent_event_id = consent_event.id
                       AND purpose.purpose IN ('personalized_coaching',
                                               'pooled_model_improvement')
                       AND purpose.article_6_basis = '6(1)(a)') = 2
        $q$ INTO eligible_grants USING eligible;
    END IF;
    IF has_training THEN
        EXECUTE $q$
            SELECT count(*) FILTER (WHERE bound),
                   count(*) FILTER (WHERE NOT bound)
              FROM (
                SELECT EXISTS (
                           SELECT 1 FROM public.ml_speaker_principals binding
                            WHERE binding.acquisition_principal_id = p) AS bound
                  FROM unnest($1) AS p
                 WHERE COALESCE((public.get_mlc2_training_consent_status_v2(p)
                                 ->> 'active')::boolean, false)
              ) yes
        $q$ INTO eligible_training, eligible_training_unbound USING eligible;
    END IF;
    IF has_receipts THEN
        EXECUTE 'SELECT count(*) FROM public.ml_confidence_producer_receipts r '
                'WHERE r.acquisition_principal_id = ANY($1)'
           INTO eligible_receipts USING eligible;
        EXECUTE 'SELECT count(*) FROM public.ml_confidence_producer_receipts r '
                'WHERE NOT (r.acquisition_principal_id = ANY($1))'
           INTO other_receipts USING eligible;
    END IF;
    IF has_events THEN
        EXECUTE 'SELECT count(*) FROM public.ml_canonical_events e '
                'WHERE e.learning_surface_id = ''confidence_classification'' '
                'AND NOT (e.acquisition_principal_id = ANY($1))'
           INTO other_events USING eligible;
    END IF;
    RETURN jsonb_build_object(
        'ring_readiness_contract_version', 'rings-confidence-readiness-v1',
        'confidence_ring_row_present', confidence_row.feature IS NOT NULL,
        'confidence_ring_row_killed', COALESCE(confidence_row.killed, false),
        'confidence_ring_row_one_way', COALESCE(confidence_row.one_way, false),
        'confidence_ring_min_ring', confidence_row.min_ring,
        'canonical_take_rows_row_present', canonical_row.feature IS NOT NULL,
        'canonical_take_rows_row_killed', COALESCE(canonical_row.killed, false),
        'eligible_principal_count', eligible_count,
        'eligible_bundled_consent_grant_count', eligible_grants,
        'eligible_training_consent_grant_count', eligible_training,
        'eligible_training_yes_without_speaker_count', eligible_training_unbound,
        'eligible_producer_receipt_count', eligible_receipts,
        'noneligible_producer_receipt_count', other_receipts,
        'noneligible_canonical_event_count', other_events,
        'tables_present', jsonb_build_object(
            'consent', has_consent, 'training', has_training,
            'receipts', has_receipts, 'events', has_events),
        'aggregate_health_only', true
    );
END;
$$;
REVOKE ALL ON FUNCTION public.get_ring_confidence_readiness_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_ring_confidence_readiness_v1()
    TO service_role;

CREATE OR REPLACE FUNCTION public.get_mlc2_confidence_canary_readiness_v1(
    p_founder_principal_id UUID DEFAULT NULL
) RETURNS JSONB
LANGUAGE sql
SECURITY DEFINER
STABLE
SET search_path = public
AS $$
SELECT jsonb_build_object(
    'readiness_contract_version', 'mlc2-confidence-canary-readiness-v1',
    'learning_contract_version', 'MLC-2',
    'data_epoch', 1,
    'learning_surface', 'confidence_classification',
    'founder_principal_configured', p_founder_principal_id IS NOT NULL,
    'active_consent_policy_count', (
        SELECT count(*) FROM ml_consent_policies policy
         WHERE policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND policy.grant_scope = 'bundled_v1'
    ),
    'valid_active_consent_policy_count', (
        SELECT count(*)
          FROM ml_consent_policies policy
          JOIN ml_product_legal_approvals approval
            ON approval.id = policy.product_legal_approval_id
         WHERE policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND policy.required_for_service
           AND policy.bundled_ui
           AND policy.grant_scope = 'bundled_v1'
           AND approval.consent_policy_version = policy.version
           AND approval.article_6_basis = '6(1)(a)'
           AND approval.article_9_treatment IN (
               'not_applicable', '9(2)(a)_when_special_category'
           )
           AND length(approval.approved_copy_sha256) = 64
           AND length(approval.evidence_sha256) = 64
           AND NULLIF(btrim(approval.approval_reference), '') IS NOT NULL
           AND NULLIF(btrim(approval.evidence_object_key), '') IS NOT NULL
    ),
    'active_training_consent_policy_count', (
        SELECT count(*) FROM ml_consent_policies policy
         WHERE policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND policy.grant_scope = 'training_only'
    ),
    'valid_active_training_consent_policy_count', (
        SELECT count(*)
          FROM ml_consent_policies policy
          JOIN ml_product_legal_approvals approval
            ON approval.id = policy.product_legal_approval_id
         WHERE policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND NOT policy.required_for_service
           AND NOT policy.bundled_ui
           AND policy.grant_scope = 'training_only'
           AND approval.consent_policy_version = policy.version
           AND approval.article_6_basis = '6(1)(a)'
           AND length(approval.approved_copy_sha256) = 64
           AND length(approval.evidence_sha256) = 64
           AND NULLIF(btrim(approval.approval_reference), '') IS NOT NULL
           AND NULLIF(btrim(approval.evidence_object_key), '') IS NOT NULL
    ),
    'founder_active_bundled_consent_grant_count', (
        SELECT count(*)
          FROM ml_consent_events consent_event
          JOIN ml_consent_policies policy
            ON policy.version = consent_event.consent_policy_version
         WHERE p_founder_principal_id IS NOT NULL
           AND consent_event.acquisition_principal_id = p_founder_principal_id
           AND consent_event.event_kind = 'grant'
           AND policy.grant_scope = 'bundled_v1'
           AND policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
           AND NOT EXISTS (
               SELECT 1 FROM ml_consent_events withdrawal
                WHERE withdrawal.event_kind = 'withdraw'
                  AND withdrawal.supersedes_event_id = consent_event.id
                  AND withdrawal.occurred_at <= now()
           )
           AND (
               SELECT count(*) FROM ml_consent_event_purposes purpose
                WHERE purpose.consent_event_id = consent_event.id
                  AND purpose.purpose IN (
                      'personalized_coaching', 'pooled_model_improvement'
                  )
                  AND purpose.article_6_basis = '6(1)(a)'
           ) = 2
    ),
    'founder_producer_receipt_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
         WHERE p_founder_principal_id IS NOT NULL
           AND receipt.acquisition_principal_id = p_founder_principal_id
    ),
    'nonfounder_producer_receipt_count', (
        SELECT count(*) FROM ml_confidence_producer_receipts receipt
         WHERE p_founder_principal_id IS NULL
            OR receipt.acquisition_principal_id <> p_founder_principal_id
    ),
    'nonfounder_canonical_event_count', (
        SELECT count(*) FROM ml_canonical_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND (p_founder_principal_id IS NULL
                OR event.acquisition_principal_id <> p_founder_principal_id)
    ),
    'pending_confidence_outbox_count', (
        SELECT count(*) FROM ml_outbox_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.processed_at IS NULL
    ),
    'failed_confidence_outbox_count', (
        SELECT count(*) FROM ml_outbox_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.processed_at IS NULL
           AND event.last_error_code IS NOT NULL
    ),
    'oldest_pending_confidence_outbox_at', (
        SELECT min(event.created_at) FROM ml_outbox_events event
         WHERE event.learning_surface_id = 'confidence_classification'
           AND event.event_type = 'confidence_take_ready'
           AND event.processed_at IS NULL
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
        SELECT count(*) FROM ml_review_assignment_events assignment_event
         WHERE assignment_event.event_kind = 'revealed'
           AND NOT EXISTS (
               SELECT 1 FROM ml_judgments judgment
                WHERE judgment.review_assignment_id =
                      assignment_event.review_assignment_id
           )
    ),
    'dataset_creation_enabled', false,
    'training_enabled', false,
    'promotion_enabled', false
);
$$;
REVOKE ALL ON FUNCTION public.get_mlc2_confidence_canary_readiness_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc2_confidence_canary_readiness_v1(UUID)
    TO service_role;

-- ── F-3: the split both data doors read ───────────────────────────────────

-- Each principal's bound speaker's one assignment under a split policy, for
-- door 2 (the pair release) and door 3 (the fine-tune run). Read-only. A
-- principal with no bound speaker, or a speaker with no assignment under
-- the policy, is absent: the doors then wait rather than guess a split.
CREATE OR REPLACE FUNCTION public.get_mlc2_speaker_splits_v1(
    p_acquisition_principal_ids UUID[],
    p_split_policy_version TEXT
) RETURNS TABLE (
    acquisition_principal_id UUID,
    split TEXT
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT binding.acquisition_principal_id, assignment.split
      FROM public.ml_speaker_principals binding
      JOIN public.ml_speaker_split_assignments assignment
        ON assignment.speaker_id = binding.speaker_id
       AND assignment.split_policy_version = p_split_policy_version
     WHERE binding.acquisition_principal_id = ANY (
               COALESCE(p_acquisition_principal_ids, ARRAY[]::UUID[]));
$$;
REVOKE ALL ON FUNCTION public.get_mlc2_speaker_splits_v1(UUID[], TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_mlc2_speaker_splits_v1(UUID[], TEXT)
    TO service_role;

-- ── F-8: every download or release check appends a verification ──────────

-- The foundation's object verifications (0302) had no writer, so no R2
-- artifact was ever verified after the bytes were hashed at promotion. One
-- reviewed writer: the caller states what it observed, the database
-- compares it with the artifact's immutable hash and size, so no caller can
-- declare an object verified. A key that is not a chain object writes
-- nothing and answers NULL, so any job that downloads a recording may ask.
CREATE OR REPLACE FUNCTION public.record_mlc2_object_verification_v1(
    p_bucket TEXT,
    p_object_key TEXT,
    p_observed_sha256 TEXT,
    p_observed_byte_size BIGINT,
    p_verification_method TEXT,
    p_verifier_version TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_object public.ml_object_artifacts%ROWTYPE;
    v_verified BOOLEAN;
    v_verification_id UUID;
BEGIN
    IF p_verification_method IS NULL OR p_verification_method NOT IN (
        'download_sha256', 'scheduled_check_sha256'
    ) THEN
        RAISE EXCEPTION 'MLC2_OBJECT_VERIFICATION_METHOD_INVALID';
    END IF;
    IF p_observed_sha256 IS NULL OR p_observed_sha256 !~ '^[0-9a-f]{64}$'
       OR p_observed_byte_size IS NULL OR p_observed_byte_size < 0 THEN
        RAISE EXCEPTION 'MLC2_OBJECT_VERIFICATION_OBSERVATION_INVALID';
    END IF;
    IF NULLIF(btrim(COALESCE(p_verifier_version, '')), '') IS NULL
       OR length(p_verifier_version) > 120 THEN
        RAISE EXCEPTION 'MLC2_OBJECT_VERIFICATION_VERIFIER_INVALID';
    END IF;

    SELECT * INTO v_object FROM public.ml_object_artifacts artifact
     WHERE artifact.object_key = ltrim(COALESCE(p_object_key, ''), '/')
       AND artifact.bucket = btrim(COALESCE(p_bucket, ''));
    IF NOT FOUND THEN
        RETURN NULL;
    END IF;

    v_verified := p_observed_sha256 = lower(v_object.sha256)
                  AND p_observed_byte_size = v_object.byte_size;
    INSERT INTO public.ml_object_verifications (
        object_artifact_id, observed_sha256, observed_byte_size, verified,
        verification_method, verifier_version
    ) VALUES (
        v_object.id, p_observed_sha256, p_observed_byte_size, v_verified,
        p_verification_method, p_verifier_version
    ) RETURNING id INTO v_verification_id;

    RETURN jsonb_build_object(
        'verification_id', v_verification_id,
        'object_artifact_id', v_object.id,
        'verified', v_verified
    );
END;
$$;
REVOKE ALL ON FUNCTION public.record_mlc2_object_verification_v1(
    TEXT, TEXT, TEXT, BIGINT, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_mlc2_object_verification_v1(
    TEXT, TEXT, TEXT, BIGINT, TEXT, TEXT
) TO service_role;

-- The weekly check's work list: chain objects never checked first, then
-- the longest unchecked, capped. An object whose source recording a purge
-- already deleted is not downloaded again. Coordinates only, never a hash
-- to compare against: the comparison is the writer's.
CREATE OR REPLACE FUNCTION public.list_mlc2_objects_due_verification_v1(
    p_limit INTEGER
) RETURNS TABLE (
    object_artifact_id UUID,
    bucket TEXT,
    object_key TEXT,
    last_checked_at TIMESTAMPTZ
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT artifact.id, artifact.bucket, artifact.object_key, checked.last_at
      FROM public.ml_object_artifacts artifact
      LEFT JOIN LATERAL (
          SELECT max(verification.verified_at) AS last_at
            FROM public.ml_object_verifications verification
           WHERE verification.object_artifact_id = artifact.id
      ) checked ON true
     WHERE artifact.object_store = 'cloudflare_r2'
       AND artifact.retention_status IN ('eligible', 'legal_hold')
       AND NOT EXISTS (
           SELECT 1 FROM public.processing_audio_objects source
            WHERE source.storage_provider = 'r2'
              AND source.bucket = artifact.bucket
              AND source.object_key = artifact.object_key
              AND source.deleted_at IS NOT NULL
       )
     ORDER BY checked.last_at ASC NULLS FIRST, artifact.created_at, artifact.id
     LIMIT LEAST(GREATEST(COALESCE(p_limit, 0), 0), 100);
$$;
REVOKE ALL ON FUNCTION public.list_mlc2_objects_due_verification_v1(INTEGER)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.list_mlc2_objects_due_verification_v1(INTEGER)
    TO service_role;

-- Door 2's file is the only data that leaves, and it is no chain object (a
-- release spans many speakers, and ml_object_artifacts names one), so its
-- checks get their own append-only ledger: one row per object per check,
-- the file against the release's file_sha256, the manifest against its
-- manifest_sha256 AND its signature.
CREATE TABLE IF NOT EXISTS public.pair_release_verifications (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    release_id          UUID NOT NULL
        REFERENCES public.pair_releases(id) ON DELETE RESTRICT,
    object_role         TEXT NOT NULL CHECK (object_role IN ('file', 'manifest')),
    observed_sha256     TEXT NOT NULL CHECK (observed_sha256 ~ '^[0-9a-f]{64}$'),
    observed_byte_size  BIGINT NOT NULL CHECK (observed_byte_size >= 0),
    signature_valid     BOOLEAN NULL,
    verified            BOOLEAN NOT NULL,
    verification_method TEXT NOT NULL CHECK (verification_method IN (
        'read_after_write_sha256', 'scheduled_check_sha256'
    )),
    verified_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    verifier_version    TEXT NOT NULL
        CHECK (length(verifier_version) BETWEEN 1 AND 120),
    CONSTRAINT pair_release_verifications_signature_on_manifest
        CHECK ((object_role = 'manifest') = (signature_valid IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS pair_release_verifications_release_idx
    ON public.pair_release_verifications (release_id, verified_at DESC);
ALTER TABLE public.pair_release_verifications ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.pair_release_verifications
    FROM PUBLIC, anon, authenticated, service_role;
GRANT SELECT ON TABLE public.pair_release_verifications TO service_role;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
         WHERE tgrelid = 'public.pair_release_verifications'::regclass
           AND tgname = 'pair_release_verifications_append_only'
    ) THEN
        CREATE TRIGGER pair_release_verifications_append_only
            BEFORE UPDATE OR DELETE ON public.pair_release_verifications
            FOR EACH ROW EXECUTE FUNCTION public.reject_mlc2_immutable_mutation();
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION public.record_pair_release_verification_v1(
    p_release_id UUID,
    p_object_role TEXT,
    p_observed_sha256 TEXT,
    p_observed_byte_size BIGINT,
    p_signature_valid BOOLEAN,
    p_verification_method TEXT,
    p_verifier_version TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_release public.pair_releases%ROWTYPE;
    v_verified BOOLEAN;
    v_verification_id UUID;
BEGIN
    SELECT * INTO v_release FROM public.pair_releases release
     WHERE release.id = p_release_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'PAIR_RELEASE_UNKNOWN';
    END IF;
    IF p_object_role IS NULL OR p_object_role NOT IN ('file', 'manifest') THEN
        RAISE EXCEPTION 'PAIR_RELEASE_VERIFICATION_ROLE_INVALID';
    END IF;
    IF (p_object_role = 'manifest') <> (p_signature_valid IS NOT NULL) THEN
        RAISE EXCEPTION 'PAIR_RELEASE_VERIFICATION_SIGNATURE_STATE_INVALID';
    END IF;
    IF p_verification_method IS NULL OR p_verification_method NOT IN (
        'read_after_write_sha256', 'scheduled_check_sha256'
    ) THEN
        RAISE EXCEPTION 'PAIR_RELEASE_VERIFICATION_METHOD_INVALID';
    END IF;
    IF p_observed_sha256 IS NULL OR p_observed_sha256 !~ '^[0-9a-f]{64}$'
       OR p_observed_byte_size IS NULL OR p_observed_byte_size < 0 THEN
        RAISE EXCEPTION 'PAIR_RELEASE_VERIFICATION_OBSERVATION_INVALID';
    END IF;
    IF NULLIF(btrim(COALESCE(p_verifier_version, '')), '') IS NULL
       OR length(p_verifier_version) > 120 THEN
        RAISE EXCEPTION 'PAIR_RELEASE_VERIFICATION_VERIFIER_INVALID';
    END IF;

    v_verified := CASE p_object_role
        WHEN 'file' THEN p_observed_sha256 = v_release.file_sha256
        ELSE p_observed_sha256 = v_release.manifest_sha256
             AND p_signature_valid
    END;
    INSERT INTO public.pair_release_verifications (
        release_id, object_role, observed_sha256, observed_byte_size,
        signature_valid, verified, verification_method, verifier_version
    ) VALUES (
        v_release.id, p_object_role, p_observed_sha256, p_observed_byte_size,
        p_signature_valid, v_verified, p_verification_method,
        p_verifier_version
    ) RETURNING id INTO v_verification_id;

    RETURN jsonb_build_object(
        'verification_id', v_verification_id,
        'release_id', v_release.id,
        'object_role', p_object_role,
        'verified', v_verified
    );
END;
$$;
REVOKE ALL ON FUNCTION public.record_pair_release_verification_v1(
    UUID, TEXT, TEXT, BIGINT, BOOLEAN, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_pair_release_verification_v1(
    UUID, TEXT, TEXT, BIGINT, BOOLEAN, TEXT, TEXT
) TO service_role;

COMMENT ON FUNCTION public.ring_consent_is_current_v1(UUID, TEXT) IS
    '0430: pooled_model_improvement is current only for an active training yes '
    '(get_mlc2_training_consent_status_v2) with a bound speaker; a bundled-era '
    'grant counts for nothing (N2, N10.6). Read only.';
COMMENT ON FUNCTION public.create_mlc2_training_consent_snapshot_v1(
    UUID, UUID, UUID, UUID
) IS '0430: the per-Take consent snapshot the canonical promotion freezes, '
     'taken from the training yes. The coaching key records that this grant '
     'does not authorise coaching.';
COMMENT ON FUNCTION public.accept_mlc2_training_consent_v1(
    UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, TIMESTAMPTZ, TEXT,
    TEXT, TEXT, TEXT, TEXT
) IS '0430: the training switch''s yes (record_mlc2_training_consent_grant_v2) '
     'and the speaker binding, one transaction.';
COMMENT ON FUNCTION public.get_mlc2_blind_coach_ratings_v1(UUID, UUID[]) IS
    '0430: the latest blind_coach judgement per snippet of one Take, from '
    'ml_judgments. Read only; never an owner, peer or machine answer.';

COMMENT ON FUNCTION public.get_mlc2_speaker_splits_v1(UUID[], TEXT) IS
    '0430 (F-3): each principal''s bound speaker''s assignment under one split '
    'policy, for the two data doors. Read only; an unbound principal is absent.';
COMMENT ON FUNCTION public.record_mlc2_object_verification_v1(
    TEXT, TEXT, TEXT, BIGINT, TEXT, TEXT
) IS '0430 (F-8): appends one ml_object_verifications row for a chain object '
     'a job downloaded; the database compares the observation with the '
     'artifact. NULL for a key that is not a chain object.';
COMMENT ON FUNCTION public.list_mlc2_objects_due_verification_v1(INTEGER) IS
    '0430 (F-8): the weekly check''s capped work list, never-checked first. '
    'Coordinates only.';
COMMENT ON TABLE public.pair_release_verifications IS
    '0430 (F-8): append-only checks of a door 2 release''s file and signed '
    'manifest, read back from the release bucket. Counts and hashes, no person.';
COMMENT ON FUNCTION public.record_pair_release_verification_v1(
    UUID, TEXT, TEXT, BIGINT, BOOLEAN, TEXT, TEXT
) IS '0430 (F-8): appends one pair_release_verifications row; the database '
     'compares the observation with the release row.';

NOTIFY pgrst, 'reload schema';
COMMIT;
