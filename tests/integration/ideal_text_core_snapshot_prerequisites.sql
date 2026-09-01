\set ON_ERROR_STOP on
CREATE EXTENSION IF NOT EXISTS pgcrypto;
DO $$ BEGIN CREATE ROLE anon NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE authenticated NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE ROLE service_role NOLOGIN; EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users(id UUID PRIMARY KEY);
CREATE TABLE IF NOT EXISTS public.owner_principals(
  id UUID PRIMARY KEY,
  user_id UUID UNIQUE REFERENCES auth.users(id),
  guest_secret_hash TEXT
);
CREATE TABLE IF NOT EXISTS public.projects(
  id UUID PRIMARY KEY,
  owner_principal_id UUID NOT NULL REFERENCES public.owner_principals(id),
  display_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS public.v2_sessions(
  id UUID PRIMARY KEY,
  user_id UUID,
  owner_principal_id UUID REFERENCES public.owner_principals(id),
  project_id UUID REFERENCES public.projects(id),
  arc_id UUID,
  take_index INTEGER,
  analysis_state TEXT,
  recording_kind TEXT,
  paired_session_id UUID
);
CREATE TABLE IF NOT EXISTS public.coach_arc_ideal_text(
  arc_id TEXT PRIMARY KEY,
  text TEXT NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS public.user_arc_ideal_notes(
  arc_id TEXT NOT NULL,
  user_id UUID NOT NULL,
  text TEXT NOT NULL DEFAULT '',
  user_text TEXT,
  user_text_version INTEGER,
  PRIMARY KEY(arc_id,user_id)
);
CREATE TABLE IF NOT EXISTS public.ideal_text_part(
  id UUID PRIMARY KEY,
  arc_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  ord INTEGER NOT NULL,
  text TEXT NOT NULL
);
INSERT INTO auth.users(id) VALUES
  ('10000000-0000-4000-8000-000000000001'),
  ('10000000-0000-4000-8000-000000000002')
ON CONFLICT DO NOTHING;
INSERT INTO public.owner_principals(id,user_id) VALUES
  ('20000000-0000-4000-8000-000000000001','10000000-0000-4000-8000-000000000001'),
  ('20000000-0000-4000-8000-000000000002','10000000-0000-4000-8000-000000000002')
ON CONFLICT DO NOTHING;
INSERT INTO public.projects(id,owner_principal_id,display_name) VALUES
  ('30000000-0000-4000-8000-000000000001','20000000-0000-4000-8000-000000000001','Test')
ON CONFLICT DO NOTHING;
INSERT INTO public.v2_sessions(
  id,user_id,owner_principal_id,project_id,arc_id,take_index,
  analysis_state,recording_kind
) VALUES (
  '40000000-0000-4000-8000-000000000001',
  '10000000-0000-4000-8000-000000000001',
  '20000000-0000-4000-8000-000000000001',
  '30000000-0000-4000-8000-000000000001',
  '50000000-0000-4000-8000-000000000001',1,'ready','spoken'
) ON CONFLICT DO NOTHING;
