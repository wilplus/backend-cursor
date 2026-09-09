-- MLC-3 founder-canary activation security closure — release migration 0325.
--
-- These lower-level SECURITY DEFINER writers are implementation helpers for
-- reviewed exact-identity wrappers.  No HTTP repository calls them directly.
-- Keeping service_role EXECUTE would permit bypassing the wrapper's packet or
-- acquisition boundary, so activation readiness requires them owner-only.

BEGIN;

REVOKE ALL ON FUNCTION public.submit_mlc2_confidence_blind_judgment_v1(
    UUID, UUID, UUID, TEXT, TIMESTAMPTZ, TEXT
) FROM PUBLIC, anon, authenticated, service_role;

REVOKE ALL ON FUNCTION public.record_exercise_service_acquisition_receipt_v1(
    UUID, TEXT, UUID, UUID, UUID, UUID, TEXT
) FROM PUBLIC, anon, authenticated, service_role;

NOTIFY pgrst, 'reload schema';
COMMIT;
