-- Disposable prerequisites for the FREEZE/ANSWER lane. Never deploy this file.
--
-- WHAT THIS LANE EXISTS FOR (#597). The two functions that decide whether a
-- speaker's judgement is accepted — `claim_ideal_text_feedback_set_v1`, which
-- freezes what was served, and `record_take_feedback_response_v1`, which
-- checks an answer against that freeze — had NO rehearsal coverage at all.
-- The tier's lanes stop at the MLC-3 chain and never install either one, so it
-- went green while testing none of the path the founder was actually blocked
-- on. Three merges in a row argued about that path from reading alone.
--
-- Only the tables the four migrations below actually touch are declared, at
-- the narrowest shape that satisfies their DDL. This is a checkpoint of one
-- chain, not a clone of production.

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

-- `add_take_review_lifecycle` reads the coach copy when it advances a review;
-- the freeze path never writes it, so an empty table is the whole requirement.
CREATE TABLE public.coach_arc_ideal_text (
    arc_id TEXT PRIMARY KEY,
    user_id UUID NULL,
    text TEXT NULL,
    version INTEGER NOT NULL DEFAULT 0,
    approved_at TIMESTAMPTZ NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- `add_feedback_manager_and_part_commits` widens this with the root-phrase
-- columns and their span CHECK. Only the identity columns it ALTERs onto
-- need to pre-exist.
CREATE TABLE public.ideal_text_part (
    id UUID PRIMARY KEY DEFAULT extensions.gen_random_uuid(),
    arc_id TEXT NOT NULL,
    user_id UUID NOT NULL,
    position INTEGER NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    locked BOOLEAN NOT NULL DEFAULT false,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION public.reject_immutable_feedback_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'immutable';
END;
$$;
