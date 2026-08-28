-- 0307 · Make every MLC-2 SHA-256 contract resolve pgcrypto exactly as
-- Supabase installs it: in the trusted `extensions` schema.
--
-- Earlier functions deliberately pinned their SECURITY DEFINER search path to
-- `public`, but their digest calls were unqualified. A stock Supabase database
-- therefore could not resolve `digest(...)`. This additive migration changes
-- no data and activates no learning writer. It only places the trusted
-- extension schema before the application schema for the affected functions.

BEGIN;

DO $$
BEGIN
    IF to_regprocedure('extensions.digest(bytea,text)') IS NULL
       OR to_regprocedure('extensions.digest(text,text)') IS NULL THEN
        RAISE EXCEPTION
            'MLC-2 requires pgcrypto digest functions in the extensions schema';
    END IF;
END;
$$;

ALTER FUNCTION public.assign_ml_speaker_split_v1(UUID, TEXT)
    SET search_path = extensions, public;

ALTER FUNCTION public.create_mlc2_consent_snapshot_v1(UUID, UUID, UUID, UUID)
    SET search_path = extensions, public;

ALTER FUNCTION public.finalize_mlc2_confidence_frame_v1(
    UUID, TEXT, JSONB, JSONB
) SET search_path = extensions, public;

ALTER FUNCTION public.promote_recording_attempt_with_mlc2_confidence_v1(
    UUID, TEXT, UUID, INTEGER, TEXT, TEXT, TEXT, JSONB
) SET search_path = extensions, public;

ALTER FUNCTION public.create_mlc2_confidence_blind_packet_v1(
    UUID, UUID, TEXT, TEXT, TEXT, TEXT, TEXT
) SET search_path = extensions, public;

ALTER FUNCTION public.configure_mlc2_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT,
    TEXT, TEXT, TIMESTAMPTZ
) SET search_path = extensions, public;

COMMIT;
