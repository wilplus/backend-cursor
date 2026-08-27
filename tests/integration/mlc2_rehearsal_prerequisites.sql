\set ON_ERROR_STOP on

-- Minimal production-coordinate shape for a disposable MLC-2 PostgreSQL
-- rehearsal.  This is not an application migration and must never be applied
-- outside a temporary local database.  Migrations 0001..0301 are baselined in
-- the rehearsal because their already-deployed prerequisite objects are
-- represented here.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        CREATE ROLE anon NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        CREATE ROLE authenticated NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        CREATE ROLE service_role NOLOGIN BYPASSRLS;
    END IF;
END;
$$;

-- Supabase's service role bypasses RLS but still receives only the explicit
-- grants below; reproduce that role property in the disposable database.
ALTER ROLE service_role BYPASSRLS;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (
    id UUID PRIMARY KEY,
    email TEXT NULL
);

CREATE TABLE IF NOT EXISTS public.owner_principals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID UNIQUE NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    guest_secret_hash TEXT UNIQUE NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ NULL,
    CONSTRAINT owner_principal_identity_check CHECK (
        (user_id IS NOT NULL AND guest_secret_hash IS NULL)
        OR (user_id IS NULL AND guest_secret_hash IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS public.projects (
    id UUID PRIMARY KEY,
    owner_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    setup JSONB NOT NULL DEFAULT '{}'::jsonb,
    presentation_ref TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.recording_attempts (
    id UUID PRIMARY KEY,
    owner_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.takes (
    id UUID PRIMARY KEY,
    recording_attempt_id UUID NOT NULL
        REFERENCES public.recording_attempts(id) ON DELETE RESTRICT,
    owner_principal_id UUID NOT NULL
        REFERENCES public.owner_principals(id) ON DELETE RESTRICT,
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS public.paragraphs (
    id UUID PRIMARY KEY
);
