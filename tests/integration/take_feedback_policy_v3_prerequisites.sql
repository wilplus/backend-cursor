-- Disposable prerequisites for migrations 0309 and 0311. Never deploy this file.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

DO $$ BEGIN CREATE ROLE anon NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE public.recordings (
    id UUID PRIMARY KEY
);

CREATE TABLE public.owner_principals (
    id UUID PRIMARY KEY
);

CREATE TABLE public.v2_sessions (
    id UUID PRIMARY KEY,
    arc_id TEXT NOT NULL,
    owner_principal_id UUID REFERENCES public.owner_principals(id),
    user_id UUID NOT NULL,
    recording_1_id UUID REFERENCES public.recordings(id),
    take_index INTEGER NOT NULL,
    recording_kind TEXT,
    paired_session_id UUID
);

CREATE TABLE public.snippets (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES public.v2_sessions(id),
    recording_id UUID NOT NULL REFERENCES public.recordings(id),
    start_offset_ms INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL
);

CREATE OR REPLACE FUNCTION public.reject_immutable_feedback_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'immutable';
END;
$$;
