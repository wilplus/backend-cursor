\set ON_ERROR_STOP on

-- Disposable-only representation of objects already deployed before 0310.
-- This file is not an application migration and must never run in production.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

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
ALTER ROLE service_role BYPASSRLS;

CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (
    id UUID PRIMARY KEY,
    email TEXT
);
CREATE TABLE IF NOT EXISTS public.owner_principals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID UNIQUE REFERENCES auth.users(id) ON DELETE CASCADE,
    guest_secret_hash TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claimed_at TIMESTAMPTZ,
    claimed_by_owner_principal_id UUID
);
CREATE TABLE IF NOT EXISTS public.projects (
    id UUID PRIMARY KEY,
    owner_principal_id UUID NOT NULL REFERENCES
        public.owner_principals(id) ON DELETE RESTRICT,
    display_name TEXT NOT NULL DEFAULT 'Rehearsal'
);
CREATE TABLE IF NOT EXISTS public.owner_claim_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_owner_principal_id UUID NOT NULL,
    target_owner_principal_id UUID NOT NULL,
    claimed_user_id UUID NOT NULL,
    claim_proof_hash TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    source_created_at TIMESTAMPTZ NOT NULL,
    claimed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.processing_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind TEXT NOT NULL,
    user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id UUID,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0
);
