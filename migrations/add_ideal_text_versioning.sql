-- willab — ideal-text versioning + verification (founder re-shape 2026-07-17:
-- the single deliverable).
--
-- The product loop becomes: record a take → instant ideal text vN
-- (unverified) → the coach VERIFIES in the background (always, paid or not)
-- → the verified text displays FREE. A new take reassembles → version
-- increments → verification resets implicitly (verified_version < version).
--
--   version          — increments whenever the MACHINE copy actually changes
--   verified_version — the version the coach verified (NULL = never)
--   verified_text    — the snapshot served as "verified" (stable even if the
--                      coach keeps editing the working copy afterwards)
--   verified_at/by   — the stamp
--
-- Idempotent; additive; flag-gated read paths (SINGLE_DELIVERABLE_ENABLED)
-- mean running this early is safe.
ALTER TABLE public.coach_arc_ideal_text
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS verified_version INTEGER NULL,
    ADD COLUMN IF NOT EXISTS verified_text TEXT NULL,
    ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS verified_by UUID NULL;
