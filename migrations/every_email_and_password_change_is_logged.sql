-- every_email_and_password_change_is_logged (WIL-95; founder 2026-10-26,
-- N189: "approved, implement it", Email and password on Data & consent)
--
-- A speaker changes their email and their password on Data & consent, and
-- every request, change and wrong password is kept as one row here, with
-- the time, the IP address and the device. Never a password.
--
--   account_security_events   One row per thing that happened:
--       email_change_requested  a link went to the new address and a notice
--                               to the old one; the row keeps the SHA-256 of
--                               the link's one-time token and when it
--                               expires, never the token itself
--       email_change_refused    the new address already has an account
--       email_changed           the link was opened and the email changed
--       password_check_failed   the current password typed was wrong
--       password_changed        on the card (source settings) or with an
--                               emailed link (source link)
--       password_set            a Google or LinkedIn account set its first
--                               password with an emailed link
--       password_reset_requested / password_set_requested
--                               a link went to the account's email
--   Append-only: the backend inserts and reads; nothing updates a row. The
--   account purge deletes them (services/data_purge_registry.py).
--
--   account_email_in_use_v1(email, except_user)
--       Whether another account already has this email, so the card can say
--       so before a link is sent. Reads auth.users, so it is SECURITY
--       DEFINER with its search_path pinned, and only the backend (service
--       role) may call it. It answers a boolean and nothing else.
--   account_has_password_v1(user)
--       Whether this account has a password, so the card asks for the
--       current one, or offers Set a password to an account that signs in
--       with Google or LinkedIn. The identities Supabase reports cannot tell:
--       a password set later adds none. Same guard as the one above; it
--       answers a boolean and never reads the hash out.
--
-- Read and written by the backend (service role) only. No environment
-- variable needed. Idempotent and additive: IF NOT EXISTS / CREATE OR
-- REPLACE, nothing dropped. One transaction; explicit grants.

BEGIN;

CREATE TABLE IF NOT EXISTS public.account_security_events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL,
    event         TEXT NOT NULL,
    old_email     TEXT,
    new_email     TEXT,
    source        TEXT,
    ip            TEXT,
    user_agent    TEXT,
    token_sha256  TEXT,
    expires_at    TIMESTAMPTZ,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT account_security_events_event_check CHECK (event IN (
        'email_change_requested', 'email_change_refused', 'email_changed',
        'password_check_failed', 'password_changed', 'password_set',
        'password_reset_requested', 'password_set_requested')),
    CONSTRAINT account_security_events_source_check
        CHECK (source IS NULL OR source IN ('settings', 'link')),
    CONSTRAINT account_security_events_old_email_len CHECK (char_length(old_email) <= 320),
    CONSTRAINT account_security_events_new_email_len CHECK (char_length(new_email) <= 320),
    CONSTRAINT account_security_events_ip_len CHECK (char_length(ip) <= 64),
    CONSTRAINT account_security_events_user_agent_len CHECK (char_length(user_agent) <= 512),
    CONSTRAINT account_security_events_token_shape
        CHECK (token_sha256 IS NULL OR token_sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS account_security_events_user_idx
    ON public.account_security_events (user_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS account_security_events_token_idx
    ON public.account_security_events (token_sha256)
    WHERE token_sha256 IS NOT NULL;

ALTER TABLE public.account_security_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.account_security_events FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, DELETE ON TABLE public.account_security_events TO service_role;

CREATE OR REPLACE FUNCTION public.account_email_in_use_v1(
    p_email TEXT,
    p_except_user UUID
) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1
          FROM auth.users u
         WHERE lower(u.email) = lower(btrim(p_email))
           AND u.id IS DISTINCT FROM p_except_user
    );
$$;

REVOKE ALL ON FUNCTION public.account_email_in_use_v1(TEXT, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.account_email_in_use_v1(TEXT, UUID)
    TO service_role;

CREATE OR REPLACE FUNCTION public.account_has_password_v1(
    p_user UUID
) RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
    SELECT COALESCE((
        SELECT COALESCE(u.encrypted_password, '') <> ''
          FROM auth.users u
         WHERE u.id = p_user
    ), false);
$$;

REVOKE ALL ON FUNCTION public.account_has_password_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.account_has_password_v1(UUID)
    TO service_role;

COMMIT;
