-- 0413 · Signing up carries a guest's whole Take into the account
--        (F1 Repair Plan Phase 0.6, founder 2026-10-04).
--
-- FOUND READING THE CLAIM FOR THE GUEST'S FULL PAGE. `claim_guest_owner` has
-- two ways to finish:
--
--   * MERGE: the account already has an owner principal. Every guest row is
--     re-pointed at it, and `v2_sessions.user_id` is set to the account.
--   * ADOPT: the account has no principal yet, which is every brand-new
--     sign-up. The guest principal simply becomes the account's: its
--     `user_id` is set and the function RETURNS AT ONCE.
--
-- The adopt path never touched `v2_sessions`. The guest's Takes kept
-- `user_id = NULL`, and every route that answers "is this your project?"
-- (`_arc_owned_by_caller`, the feedback-response check) compares
-- `v2_sessions.user_id` with the caller. So a speaker who recorded as a guest
-- and then signed up -- exactly the journey the founder chose, sign-up in
-- front of practise -- opened their own project and got "not found".
--
-- THREE CHANGES, ONE FUNCTION.
--
-- 1. ADOPT finishes the job MERGE already does: the guest's Takes get the
--    account's `user_id`, and the two legacy row owners that follow them
--    (`recording_1` when it exists, `snippets`) are updated the same way.
--
-- 2. BOTH paths move the Ideal Text paragraphs the guest's document was given
--    (`ideal_text_part`, keyed by actor). A guest's actor is its principal id
--    (`_publishing_actor` falls back to `owner_principal_id`); after sign-up
--    the reader is the account, so without this the account would mint new
--    paragraph ids for the same text -- Paragraph identity broken by a
--    sign-up (L1). Moving the rows advances the document generation through
--    the existing trigger, so the account's first read publishes its own
--    head. Only paragraphs on the guest's own projects move, and never onto
--    an arc where the account already has paragraphs.
--
--    NOT moved, on purpose: `ideal_text_part_revision` and
--    `take_feedback_self_report` are append-only evidence (0300 triggers
--    refuse UPDATE), and a guest cannot write either yet -- answering and
--    locking stay account-only in this phase. Document snapshots and heads
--    stay with the guest actor as history; the account publishes its own.
--
-- 3. REPAIR. Principals already adopted before this migration keep sessions
--    with `user_id = NULL`; those, their snippets and their paragraphs are
--    given the account now. Idempotent: every statement only touches rows
--    still in the broken state.
--
-- CARRIES 0331, 0338 AND 0343 FORWARD. CREATE OR REPLACE replaces the whole
-- body and resets the search path, so `SET search_path = extensions, public`
-- (digest), the `to_regclass` guard on `recording_1` and the `snippets` name
-- are restated here unchanged.
--
-- Activates no serving or learning gate.

BEGIN;

CREATE OR REPLACE FUNCTION public.move_guest_ideal_text_parts_v1(
    p_guest_principal_id UUID,
    p_user_id UUID
) RETURNS INTEGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    moved INTEGER;
BEGIN
    UPDATE public.ideal_text_part part
       SET user_id = p_user_id::text
     WHERE part.user_id = p_guest_principal_id::text
       AND NOT EXISTS (
           SELECT 1 FROM public.ideal_text_part mine
            WHERE mine.arc_id = part.arc_id
              AND mine.user_id = p_user_id::text
       );
    GET DIAGNOSTICS moved = ROW_COUNT;
    RETURN moved;
END;
$$;

REVOKE ALL ON FUNCTION public.move_guest_ideal_text_parts_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated, service_role;

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

        -- 0413: ADOPT now gives the guest's Takes to the account, as MERGE
        -- always did. Without it the account's own project answered 404.
        UPDATE public.v2_sessions
           SET user_id = p_user_id
         WHERE owner_principal_id = claimed.id
           AND user_id IS NULL;
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
        UPDATE public.snippets
           SET user_id = p_user_id
         WHERE session_id IN (
             SELECT id FROM public.v2_sessions
              WHERE owner_principal_id = target.id AND user_id = p_user_id
         );
        PERFORM public.move_guest_ideal_text_parts_v1(claimed.id, p_user_id);
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

    -- 0338: guarded, because `recording_1` is created by no migration here.
    -- EXECUTE so a database that gains or loses the table mid-session is
    -- re-planned rather than answered from a stale cached plan.
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
    -- 0343: pointed, not guarded -- 0260 created `snippets` by renaming.
    UPDATE public.snippets
       SET user_id = p_user_id
     WHERE session_id IN (
         SELECT id FROM public.v2_sessions
          WHERE owner_principal_id = target.id AND user_id = p_user_id
     );
    -- 0413: the guest's paragraphs follow its Takes.
    PERFORM public.move_guest_ideal_text_parts_v1(claimed.id, p_user_id);

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

-- 0413 REPAIR: guests adopted before this migration. An adopted principal is
-- one that holds an account and was never merged into another.
UPDATE public.v2_sessions session
   SET user_id = owner.user_id
  FROM public.owner_principals owner
 WHERE session.owner_principal_id = owner.id
   AND session.user_id IS NULL
   AND owner.user_id IS NOT NULL
   AND owner.claimed_at IS NOT NULL
   AND owner.claimed_by_owner_principal_id IS NULL;

UPDATE public.snippets snippet
   SET user_id = session.user_id
  FROM public.v2_sessions session
  JOIN public.owner_principals owner ON owner.id = session.owner_principal_id
 WHERE snippet.session_id = session.id
   AND snippet.user_id IS NULL
   AND session.user_id = owner.user_id
   AND owner.claimed_at IS NOT NULL
   AND owner.claimed_by_owner_principal_id IS NULL;

-- Paragraphs written under a guest actor that has since been claimed, by
-- adoption (the principal is now the account's) or by merge (the account is
-- the target's).
SELECT public.move_guest_ideal_text_parts_v1(guest.id, account.user_id)
  FROM public.owner_principals guest
  JOIN public.owner_principals account
    ON account.id = COALESCE(guest.claimed_by_owner_principal_id, guest.id)
 WHERE guest.claimed_at IS NOT NULL
   AND account.user_id IS NOT NULL
   AND EXISTS (
       SELECT 1 FROM public.ideal_text_part part
        WHERE part.user_id = guest.id::text
   );

COMMIT;
