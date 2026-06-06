-- willab coach role — allowlist table (mirrors admin_users).
--
-- Authorization model (BE pre-flight B.5.2 decision): the coach role is an
-- ALLOWLIST, not a Supabase JWT `role` claim. routes.admin.is_coach() reads
-- the caller's token email and checks for an active row here, exactly like
-- is_admin() against admin_users. The backend uses the service-role key, so
-- this is an app-layer gate; the FE `is_coach` flag is never the gate.
--
-- The willab coach review surface — /v2/admin/review-queue,
-- /v2/admin/sessions/<id>/readout, /v2/admin/sessions/<id>/publish (and the
-- coming per-snippet save + coach video) — is gated by require_admin_or_coach:
-- admins keep access (superset operator), allowlisted coaches gain it.

CREATE TABLE IF NOT EXISTS coach_users (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    email       text        NOT NULL UNIQUE,
    is_active   boolean     NOT NULL DEFAULT true,
    notes       text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_coach_users_email_active
    ON coach_users (email) WHERE is_active;

-- Lock down: only the service role (the BE) should ever read/write this.
-- No policies are created, so with RLS enabled anon/authenticated clients are
-- denied while the service-role key bypasses RLS — mirroring how the BE treats
-- admin_users (the allowlist is never client-readable).
ALTER TABLE coach_users ENABLE ROW LEVEL SECURITY;

-- Seed coaches, e.g.:
--   INSERT INTO coach_users (email) VALUES ('coach@example.com')
--   ON CONFLICT (email) DO UPDATE SET is_active = true, updated_at = now();
