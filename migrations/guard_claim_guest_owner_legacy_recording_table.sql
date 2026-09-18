-- 0338 · A missing legacy table must not roll back the whole guest claim.
--
-- REPORTED FROM PRODUCTION 2026-09-18, three times in ninety seconds against
-- one guest principal:
--
--     claim_guest_owner_principal failed id=4f01f325-...: {'code': '42P01',
--       'message': 'relation "public.recording_1" does not exist'}
--
-- `public.claim_guest_owner` moves a guest's whole graph onto their new
-- account in ONE transaction — projects, sessions, rejected takes, moment
-- suggestions, transcript versions, slides, paragraphs, evidence spans,
-- acoustic snapshots, candidate sets, machine predictions, generation runs,
-- processing stage runs, takes, transition events, recording attempts — and
-- then two legacy row-owner updates. The second-to-last of those targets
-- `public.recording_1`, which this database does not have, so PostgreSQL
-- raised 42P01 and rolled back all sixteen. The signup looked fine and the
-- guest's work stayed on the dead guest principal.
--
-- Same shape as 0331 (fix_claim_guest_owner_pgcrypto_search_path): a function
-- that is correct everywhere except in the one detail production does not
-- share, found only when a real user walked the path. 0331 fixed digest();
-- this fixes the table.
--
-- CARRIES 0331 FORWARD. CREATE OR REPLACE resets a function's search path, so
-- `SET search_path = extensions, public` is restated here on purpose. Dropping
-- it would silently reintroduce 42883 on digest() — the exact bug 0331 exists
-- to stop — and nothing would catch it until the next real claim.
--
-- Changes no rows. Activates no serving or learning gate. Idempotent:
-- replacing the function with the same definition twice is a no-op.

BEGIN;

CREATE OR REPLACE FUNCTION public.claim_guest_owner(
    p_owner_principal_id UUID,
    p_guest_secret_hash TEXT,
    p_user_id UUID
) RETURNS public.owner_principals
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = extensions, public
AS $$
DECLARE
    claimed public.owner_principals;
    target public.owner_principals;
    replay public.owner_claim_events;
    claim_event_id UUID := gen_random_uuid();
    proof_hash TEXT;
    claim_key TEXT;
BEGIN
    IF p_user_id IS NULL OR NULLIF(trim(p_guest_secret_hash), '') IS NULL THEN
        RAISE EXCEPTION 'guest owner claim rejected';
    END IF;
    proof_hash := encode(digest(p_guest_secret_hash, 'sha256'), 'hex');
    claim_key := encode(digest(
        p_owner_principal_id::text || ':' || p_user_id::text,
        'sha256'
    ), 'hex');

    SELECT * INTO replay FROM public.owner_claim_events event
     WHERE event.source_owner_principal_id = p_owner_principal_id
       AND event.claimed_user_id = p_user_id
       AND event.claim_proof_hash = proof_hash
       AND event.idempotency_key = claim_key;
    IF replay.id IS NOT NULL THEN
        SELECT * INTO target FROM public.owner_principals owner
         WHERE owner.id = replay.target_owner_principal_id;
        IF target.id IS NULL THEN
            RAISE EXCEPTION 'claimed owner target is unavailable';
        END IF;
        RETURN target;
    END IF;

    SELECT * INTO claimed FROM public.owner_principals owner
     WHERE owner.id = p_owner_principal_id
       AND owner.user_id IS NULL
       AND owner.claimed_by_owner_principal_id IS NULL
       AND owner.guest_secret_hash = p_guest_secret_hash
     FOR UPDATE;
    IF claimed.id IS NULL THEN
        RAISE EXCEPTION 'guest owner claim rejected';
    END IF;

    SELECT * INTO target FROM public.owner_principals owner
     WHERE owner.user_id = p_user_id
     FOR UPDATE;
    IF target.id IS NULL THEN
        target := claimed;
    END IF;

    INSERT INTO public.owner_claim_events (
        id, source_owner_principal_id, target_owner_principal_id,
        claimed_user_id, claim_proof_hash, idempotency_key,
        source_created_at
    ) VALUES (
        claim_event_id, claimed.id, target.id, p_user_id,
        proof_hash, claim_key, claimed.created_at
    );

    IF target.id = claimed.id THEN
        UPDATE public.owner_principals
           SET user_id = p_user_id,
               guest_secret_hash = NULL,
               claimed_at = now()
         WHERE id = claimed.id
        RETURNING * INTO target;
        RETURN target;
    END IF;

    PERFORM set_config(
        'willab.owner_claim_event_id', claim_event_id::text, true);
    PERFORM set_config(
        'willab.owner_claim_source', claimed.id::text, true);
    PERFORM set_config(
        'willab.owner_claim_target', target.id::text, true);

    -- Match Take promotion's lock order (Attempt, then Project) so a signup
    -- racing the final worker cannot create a circular wait or half-transfer.
    PERFORM 1 FROM public.recording_attempts attempt
     WHERE attempt.owner_principal_id = claimed.id
     ORDER BY attempt.id
     FOR UPDATE;

    UPDATE public.projects
       SET owner_principal_id = target.id, updated_at = now()
     WHERE owner_principal_id = claimed.id;
    UPDATE public.v2_sessions
       SET owner_principal_id = target.id, user_id = p_user_id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.rejected_takes
       SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.moment_suggestions
       SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;

    UPDATE public.transcript_versions SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.slides SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.paragraphs SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.evidence_spans SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.acoustic_feature_snapshots
       SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.candidate_sets SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.machine_predictions SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.generation_runs SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.processing_stage_runs SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;

    UPDATE public.takes SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.processing_transition_events
       SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;
    UPDATE public.recording_attempts SET owner_principal_id = target.id
     WHERE owner_principal_id = claimed.id;

    -- THE ONE MISSING TABLE THAT ATE THE WHOLE CLAIM (2026-09-18).
    --
    --     claim_guest_owner_principal failed id=...: {'code': '42P01',
    --       'message': 'relation "public.recording_1" does not exist'}
    --
    -- 42P01 aborts the function, and the function is one transaction, so the
    -- rollback took every ownership transfer above this line with it: the
    -- projects, the sessions, the takes, the attempts, the transcripts, the
    -- slides, the paragraphs, the evidence spans. A guest who signed up kept
    -- NOTHING, and the only trace was one WARNING in the web log.
    --
    -- `recording_1` is not created by any migration in this repository. It
    -- predates them, three call sites assume it is simply always there, and
    -- in this database it is not.
    --
    -- GUARDED, NOT DELETED. Where the table still exists this runs exactly
    -- the statement it always ran, so no database that has it loses a write.
    -- Where it does not, one legacy row-owner update is skipped and the other
    -- fifteen transfers complete — which is strictly better than today, where
    -- all sixteen are rolled back.
    --
    -- EXECUTE rather than a plain UPDATE inside the IF: plpgsql caches the
    -- plan for a static statement for the life of the session, so a database
    -- that gains or loses the table mid-session would keep answering from the
    -- stale plan. Dynamic SQL is re-planned per call and always agrees with
    -- the guard that just ran.
    IF to_regclass('public.recording_1') IS NOT NULL THEN
        EXECUTE $legacy$
            UPDATE public.recording_1
               SET user_id = $1
             WHERE session_v2_id IN (
                 SELECT id FROM public.v2_sessions
                  WHERE owner_principal_id = $2 AND user_id = $1
             )
        $legacy$ USING p_user_id, target.id;
    END IF;
    UPDATE public.charisma_snippets
       SET user_id = p_user_id
     WHERE session_id IN (
         SELECT id FROM public.v2_sessions
          WHERE owner_principal_id = target.id AND user_id = p_user_id
     );

    UPDATE public.owner_principals
       SET guest_secret_hash = NULL,
           claimed_by_owner_principal_id = target.id,
           claimed_at = now()
     WHERE id = claimed.id;
    RETURN target;
END;
$$;

REVOKE ALL ON FUNCTION public.claim_guest_owner(UUID, TEXT, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_guest_owner(UUID, TEXT, UUID)
    TO service_role;

COMMIT;
