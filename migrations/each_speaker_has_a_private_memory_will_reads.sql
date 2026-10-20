-- each_speaker_has_a_private_memory_will_reads (WIL-74, founder 2026-10-20)
--
-- Will learns about each speaker without any model being retrained: a short
-- private note per speaker, rewritten from what happened, read by Will
-- before it chats and before it writes the summary after a Take. The note
-- is plain text, so it survives any change of AI provider.
--
--   speaker_memory_events  The raw inputs, kept for good (the asset): every
--                          answer to "Did this help?" and every Take's
--                          outcome. A better model can rebuild every note
--                          from these.
--   speaker_memory         One row per speaker: the current note (at most
--                          five lines), who wrote it last (the AI or the
--                          founder) and when.
--
-- Read and written by the backend (service role) only; never shown to the
-- speaker or a coach. Both are purged with the account
-- (services/data_purge_registry.py). No environment variable needed.
-- Idempotent and additive: IF NOT EXISTS everywhere, nothing dropped.

CREATE TABLE IF NOT EXISTS public.speaker_memory_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    take_session_id  UUID,
    kind             TEXT NOT NULL,
    payload          JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT speaker_memory_events_kind_check CHECK (kind IN ('answer', 'take'))
);

CREATE INDEX IF NOT EXISTS speaker_memory_events_user_idx
    ON public.speaker_memory_events (user_id, created_at);

ALTER TABLE public.speaker_memory_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.speaker_memory_events FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS public.speaker_memory (
    user_id     UUID PRIMARY KEY,
    note        TEXT NOT NULL DEFAULT '',
    written_by  TEXT NOT NULL DEFAULT 'ai',
    model       TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT speaker_memory_written_by_check CHECK (written_by IN ('ai', 'founder')),
    CONSTRAINT speaker_memory_note_len CHECK (char_length(note) <= 800)
);

ALTER TABLE public.speaker_memory ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.speaker_memory FROM anon, authenticated;
