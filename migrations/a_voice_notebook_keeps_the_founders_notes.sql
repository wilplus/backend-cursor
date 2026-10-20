-- a_voice_notebook_keeps_the_founders_notes (Will learning plan, step 1,
-- founder 2026-10-20: "approved, start step 1")
--
-- A private notebook in the Lounge: a voice note (up to five minutes) or a
-- typed message starting with "#". Will reads the notes; nobody else does
-- (no coach, never the Ideal Text). Founder only for now (ring 6).
--
--   voice_notebook_notes    One row per note: the cleaned words (fillers out,
--                           every other word kept), the raw transcript, and
--                           where it came from (voice or typed).
--   voice_notebook_audio    The recording itself, kept for a later feature
--                           (how sure the voice sounded). In the database,
--                           not the bucket, so account deletion takes it
--                           with the notes as an ordinary row
--                           (services/data_purge_registry.py). At most a
--                           few MB per note and founder-only.
--   voice_notebook_consent  The person's answer to "Keep a voice notebook?".
--   feature_rings row       voice_notebook, ring 6 (the founder's ring).
--
-- Read and written by the backend (service role) only. No environment
-- variable needed. Idempotent and additive: IF NOT EXISTS / ON CONFLICT DO
-- NOTHING everywhere, nothing dropped.

CREATE TABLE IF NOT EXISTS public.voice_notebook_notes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    source          TEXT NOT NULL,
    text_clean      TEXT NOT NULL,
    transcript_raw  TEXT,
    duration_ms     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT voice_notebook_notes_source_check CHECK (source IN ('voice', 'typed')),
    CONSTRAINT voice_notebook_notes_len CHECK (char_length(text_clean) <= 20000)
);

CREATE INDEX IF NOT EXISTS voice_notebook_notes_user_idx
    ON public.voice_notebook_notes (user_id, created_at);

ALTER TABLE public.voice_notebook_notes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.voice_notebook_notes FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS public.voice_notebook_audio (
    note_id       UUID PRIMARY KEY
                  REFERENCES public.voice_notebook_notes(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL,
    content_type  TEXT NOT NULL,
    audio         BYTEA NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT voice_notebook_audio_size CHECK (octet_length(audio) <= 12582912)
);

CREATE INDEX IF NOT EXISTS voice_notebook_audio_user_idx
    ON public.voice_notebook_audio (user_id);

ALTER TABLE public.voice_notebook_audio ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.voice_notebook_audio FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS public.voice_notebook_consent (
    user_id     UUID PRIMARY KEY,
    decision    TEXT NOT NULL,
    decided_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT voice_notebook_consent_decision_check CHECK (decision IN ('yes', 'not_now'))
);

ALTER TABLE public.voice_notebook_consent ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.voice_notebook_consent FROM anon, authenticated;

INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('voice_notebook', 6,
        'Will learning plan step 1: the founder''s private voice notebook in '
        'the Lounge (mic right of the message box, "#" notes).',
        'migration:a_voice_notebook_keeps_the_founders_notes')
ON CONFLICT (feature) DO NOTHING;
