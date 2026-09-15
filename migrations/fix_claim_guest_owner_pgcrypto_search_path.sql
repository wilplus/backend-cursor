-- 0331 · Resolve pgcrypto for the guest owner claim.
--
-- USER-VISIBLE BREAKAGE, seen in production every time a guest tried to claim
-- their account:
--
--     claim_guest_owner_principal failed id=...: {'code': '42883',
--       'message': 'function digest(text, unknown) does not exist'}
--
-- public.claim_guest_owner is SECURITY DEFINER with `SET search_path = public`,
-- and it calls digest() twice -- once for the proof hash, once for the
-- idempotency key. digest() is pgcrypto. Stock PostgreSQL commonly installs
-- pgcrypto in public, while Supabase keeps it in `extensions`, so under a
-- search path pinned to public alone the function is simply not visible and
-- every claim fails with 42883.
--
-- Pinning the search path is correct and must not be removed -- an unpinned
-- SECURITY DEFINER function is a privilege-escalation hazard. The fix is to
-- name the schema the production extension actually lives in.
--
-- EXACTLY THE SAME DEFECT AS 0316 (fix_ideal_text_core_pgcrypto_search_path),
-- which fixed publish_ideal_text_document_snapshot_v1 for the same reason, and
-- this file deliberately mirrors it line for line -- including the guard that
-- refuses to proceed if pgcrypto is not where we think it is. That one was
-- found by a failing snapshot publish; this one by a founder reading the boot
-- log. Both are the same lesson: "SET search_path = public" plus a pgcrypto
-- call is broken on Supabase, and only shows up at the moment a real user
-- exercises the path.
--
-- THE SWEEP, AND WHY THIS IS THE LAST ONE. Every migration file was scanned for
-- the same combination: a function pinned to a search path without
-- `extensions`, calling pgcrypto UNQUALIFIED in its body. Exactly 8 exist, and
-- 7 were already repaired -- which is the point:
--
--   fix_mlc2_pgcrypto_search_path.sql            6 functions
--     assign_ml_speaker_split_v1, create_mlc2_consent_snapshot_v1,
--     finalize_mlc2_confidence_frame_v1, configure_mlc2_consent_policy_v1,
--     create_mlc2_confidence_blind_packet_v1,
--     promote_recording_attempt_with_mlc2_confidence_v1
--   fix_ideal_text_core_pgcrypto_search_path.sql (0316)   1 function
--     publish_ideal_text_document_snapshot_v1
--   THIS FILE                                             1 function
--     claim_guest_owner        <- missed by both sweeps
--
-- So this is the third pass at one defect, not a new discovery, and
-- claim_guest_owner is the only one either sweep left behind. After this the
-- set is empty.
--
-- Two false leads the sweep had to exclude, recorded so the next person does
-- not re-raise them: `gen_random_uuid()` matches the same pattern in 22
-- functions and is harmless, because PostgreSQL 13+ provides it in pg_catalog
-- and it resolves whatever the search path is; and a schema-QUALIFIED
-- `extensions.digest(...)` also matches a naive word search while being
-- perfectly correct. Counting either as a finding turns 1 real defect into 20+
-- imaginary ones.
--
-- Changes no rows. Activates no serving or learning gate. Idempotent: setting
-- the same search path twice is a no-op.

BEGIN;

DO $$
BEGIN
    IF to_regprocedure('extensions.digest(text,text)') IS NULL THEN
        RAISE EXCEPTION
            'claim_guest_owner requires pgcrypto in extensions';
    END IF;
END;
$$;

ALTER FUNCTION public.claim_guest_owner(UUID, TEXT, UUID)
    SET search_path = extensions, public;

COMMIT;
