-- 0419 · A guest's Take claims its feedback set (founder live test,
--        2026-10-05: a guest's Take 1 showed its Ideal Text with no
--        feedback at all and no notice saying why).
--
-- claim_ideal_text_feedback_set_v1 (0347) freezes what a Take served. It
-- checks that the caller owns the Take by comparing v2_sessions.user_id with
-- the caller's id. A guest's Take has no user_id -- only owner_principal_id
-- -- and a guest caller's id IS that principal (routes/v2/guest_owner.py,
-- Phase 0.6; services/project_ownership.session_actor_id). So every guest
-- claim raised 'feedback set provenance mismatch', and the read lost its
-- whole Feedback block.
--
-- WHAT CHANGES, AND ONLY THAT. The owner side of that one comparison reads
-- COALESCE(s.user_id, s.owner_principal_id): the Take's account, else its
-- guest owner -- the rule session_actor_id already applies on the read
-- route. A signed-in Take compares exactly as before (its user_id is never
-- NULL), and a guest Take matches only its own guest principal. The arc and
-- Take-index checks beside it are untouched.
--
-- Patched in place from the installed definition (as 0418); refuses loudly
-- if the line is not found exactly once; a no-op when already applied or
-- when the function is not installed. Changes no rows. Idempotent.

BEGIN;

DO $guest_take_claims$
DECLARE
    target regprocedure := to_regprocedure(
        'public.claim_ideal_text_feedback_set_v1(text,uuid,uuid,integer,integer,jsonb)');
    definition text;
    marker constant text := '/* 0419 guest owner */';
    owner_check constant text := 'IF s.user_id IS DISTINCT FROM p_owner_user_id';
    guest_aware constant text :=
        'IF COALESCE(s.user_id, s.owner_principal_id) /* 0419 guest owner */ '
        || 'IS DISTINCT FROM p_owner_user_id';
BEGIN
    IF target IS NULL THEN
        RAISE NOTICE '0419: claim_ideal_text_feedback_set_v1 is not installed here';
        RETURN;
    END IF;
    definition := pg_get_functiondef(target);
    IF position(marker IN definition) > 0 THEN
        RETURN;  -- applied by an earlier run
    END IF;
    IF (length(definition) - length(replace(definition, owner_check, '')))
       / length(owner_check) <> 1 THEN
        RAISE EXCEPTION 'GUEST_CLAIM_OWNER_CHECK_NOT_UNIQUE';
    END IF;
    EXECUTE replace(definition, owner_check, guest_aware);
    IF position(marker IN pg_get_functiondef(target)) = 0 THEN
        RAISE EXCEPTION 'GUEST_CLAIM_EDIT_DID_NOT_LAND';
    END IF;
END
$guest_take_claims$;

COMMIT;
