-- add_booking.sql revoked booking_hold from PUBLIC, which also took it away
-- from the backend's service_role: every checkout failed with
-- "permission denied for function booking_hold". Give it back to the
-- backend only. Additive and safe to re-run.
GRANT EXECUTE ON FUNCTION public.booking_hold(
    TIMESTAMPTZ, TIMESTAMPTZ, INTEGER, INTEGER, TIMESTAMPTZ, TEXT, TEXT, TEXT,
    TEXT, TEXT, INTEGER, TEXT, TEXT
) TO service_role;
