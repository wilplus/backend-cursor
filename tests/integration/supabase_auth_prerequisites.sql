-- Supabase Auth's own tables, as far as erasing a deleted account's sign-in
-- (migration 0497) reads and updates them.
-- A narrow copy: the columns and types Supabase Auth (GoTrue) declares for
-- auth.users, auth.identities, auth.sessions, auth.refresh_tokens,
-- auth.one_time_tokens, auth.flow_state and auth.mfa_factors, with the
-- foreign keys they have to auth.users. Enums are text here. Real Supabase
-- owns these tables; a disposable cluster has only the recipe's auth.users
-- stub (id, email, raw_user_meta_data, created_at), which this completes.
-- Idempotent: IF NOT EXISTS throughout.

CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (id UUID PRIMARY KEY);

ALTER TABLE auth.users
    ADD COLUMN IF NOT EXISTS instance_id UUID,
    ADD COLUMN IF NOT EXISTS aud VARCHAR(255),
    ADD COLUMN IF NOT EXISTS role VARCHAR(255),
    ADD COLUMN IF NOT EXISTS email VARCHAR(255),
    ADD COLUMN IF NOT EXISTS encrypted_password VARCHAR(255),
    ADD COLUMN IF NOT EXISTS email_confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS invited_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS confirmation_token VARCHAR(255),
    ADD COLUMN IF NOT EXISTS confirmation_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS recovery_token VARCHAR(255),
    ADD COLUMN IF NOT EXISTS recovery_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS email_change_token_new VARCHAR(255),
    ADD COLUMN IF NOT EXISTS email_change VARCHAR(255),
    ADD COLUMN IF NOT EXISTS email_change_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_sign_in_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS raw_app_meta_data JSONB,
    ADD COLUMN IF NOT EXISTS raw_user_meta_data JSONB,
    ADD COLUMN IF NOT EXISTS is_super_admin BOOLEAN,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS phone TEXT UNIQUE DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS phone_confirmed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS phone_change TEXT DEFAULT '',
    ADD COLUMN IF NOT EXISTS phone_change_token VARCHAR(255) DEFAULT '',
    ADD COLUMN IF NOT EXISTS phone_change_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS email_change_token_current VARCHAR(255) DEFAULT '',
    ADD COLUMN IF NOT EXISTS email_change_confirm_status SMALLINT DEFAULT 0,
    ADD COLUMN IF NOT EXISTS banned_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS reauthentication_token VARCHAR(255) DEFAULT '',
    ADD COLUMN IF NOT EXISTS reauthentication_sent_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS is_sso_user BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS is_anonymous BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS auth.identities (
    provider_id     TEXT NOT NULL,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    identity_data   JSONB NOT NULL,
    provider        TEXT NOT NULL,
    last_sign_in_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ,
    email           TEXT GENERATED ALWAYS AS
                        (lower(identity_data ->> 'email')) STORED,
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    CONSTRAINT identities_provider_id_provider_unique
        UNIQUE (provider_id, provider)
);

CREATE TABLE IF NOT EXISTS auth.sessions (
    id           UUID PRIMARY KEY,
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ,
    factor_id    UUID,
    aal          TEXT,
    not_after    TIMESTAMPTZ,
    refreshed_at TIMESTAMP,
    user_agent   TEXT,
    ip           INET,
    tag          TEXT
);

-- user_id is VARCHAR in Supabase Auth, not UUID.
CREATE TABLE IF NOT EXISTS auth.refresh_tokens (
    instance_id UUID,
    id          BIGSERIAL PRIMARY KEY,
    token       VARCHAR(255) UNIQUE,
    user_id     VARCHAR(255),
    revoked     BOOLEAN,
    created_at  TIMESTAMPTZ,
    updated_at  TIMESTAMPTZ,
    parent      VARCHAR(255),
    session_id  UUID REFERENCES auth.sessions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS auth.one_time_tokens (
    id         UUID PRIMARY KEY,
    user_id    UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    token_type TEXT NOT NULL,
    token_hash TEXT NOT NULL CHECK (char_length(token_hash) > 0),
    relates_to TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS auth.flow_state (
    id                     UUID PRIMARY KEY,
    user_id                UUID,
    auth_code              TEXT,
    code_challenge_method  TEXT,
    code_challenge         TEXT,
    provider_type          TEXT NOT NULL,
    provider_access_token  TEXT,
    provider_refresh_token TEXT,
    created_at             TIMESTAMPTZ,
    updated_at             TIMESTAMPTZ,
    authentication_method  TEXT NOT NULL,
    auth_code_issued_at    TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS auth.mfa_factors (
    id                 UUID PRIMARY KEY,
    user_id            UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    friendly_name      TEXT,
    factor_type        TEXT NOT NULL,
    status             TEXT NOT NULL,
    created_at         TIMESTAMPTZ NOT NULL,
    updated_at         TIMESTAMPTZ NOT NULL,
    secret             TEXT,
    phone              TEXT,
    last_challenged_at TIMESTAMPTZ
);
