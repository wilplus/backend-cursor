-- 0462 · The AI version of your voice in practice (founder lock 2026-10-12,
-- N71; docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md).
--
-- WHY. In the voice Exercise the app plays the speaker's own sentence in an
-- AI version of their voice (ElevenLabs Instant Voice Clone), then measures
-- their next try on the one problem practised. Two things need a home: the
-- speaker's one clone, and each practice's one clip with its before/after.
--
-- WHAT.
--   1. `ai_voice_clones`: one row per speaker. The provider's voice id stays
--      here and never reaches a client. `enabled` is the Data & consent card
--      (on by default; off after Delete). `status` tracks the clone itself.
--   2. `ai_voice_cycles`: one row per practice (UNIQUE practice_id, so a
--      retried request never makes a second clip). The clip's storage
--      coordinates and hash (for verified deletion), the prepared text and
--      non-sensitive settings, the validation result, latencies, the
--      characters billed, and the cycle's before/after for the future
--      exercise picker. Nothing here is ever a training label (L3); nothing
--      trains from it until separately authorised.
--
-- SAFE TWICE. Tables and indexes are IF NOT EXISTS; policies and grants are
-- restated. Nothing is dropped.
CREATE TABLE IF NOT EXISTS public.ai_voice_clones (
    owner_user_id      UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    provider           TEXT NOT NULL DEFAULT 'elevenlabs'
                       CHECK (provider = 'elevenlabs'),
    provider_voice_id  TEXT,
    status             TEXT NOT NULL DEFAULT 'none'
                       CHECK (status IN ('none', 'creating', 'ready', 'failed',
                                         'deleting', 'deleted')),
    enabled            BOOLEAN NOT NULL DEFAULT TRUE,
    source_take_id     UUID,
    failure_kind       TEXT,
    attempts           INTEGER NOT NULL DEFAULT 0,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    ready_at           TIMESTAMPTZ,
    deleted_at         TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS public.ai_voice_cycles (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id           UUID NOT NULL UNIQUE
                          REFERENCES public.confident_voice_practice(id) ON DELETE CASCADE,
    owner_user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    take_session_id       UUID,
    snippet_id            UUID,
    status                TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'analyzing', 'choosing_exercise',
                                            'generating', 'validating', 'completed',
                                            'failed', 'skipped', 'deleted')),
    demo                  TEXT CHECK (demo IN ('video', 'ai_voice', 'none')),
    exercise              TEXT CHECK (exercise IN ('pace', 'pause', 'stress')),
    selection             JSONB,
    prepared_text         TEXT,
    generation_metadata   JSONB,
    validation            JSONB,
    failure_kind          TEXT CHECK (failure_kind IN ('provider', 'validation',
                                                       'limits', 'no_voice',
                                                       'no_exercise', 'internal')),
    failure_code          TEXT,
    generation_attempts   INTEGER NOT NULL DEFAULT 0,
    characters            INTEGER NOT NULL DEFAULT 0,
    credits_estimated     NUMERIC NOT NULL DEFAULT 0,
    latency_ms            JSONB,
    storage_provider      TEXT,
    bucket                TEXT,
    storage_key           TEXT,
    content_sha256        TEXT,
    duration_ms           INTEGER,
    metrics_before        JSONB,
    metrics_after         JSONB,
    outcome               TEXT CHECK (outcome IN ('improved', 'similar', 'worsened',
                                                  'inconclusive')),
    plays                 INTEGER NOT NULL DEFAULT 0,
    listened              BOOLEAN NOT NULL DEFAULT FALSE,
    retried               BOOLEAN NOT NULL DEFAULT FALSE,
    helpfulness           TEXT,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    ready_at              TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ai_voice_cycles_owner_created
    ON public.ai_voice_cycles (owner_user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ai_voice_cycles_created
    ON public.ai_voice_cycles (created_at DESC);
ALTER TABLE public.ai_voice_clones ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_voice_cycles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.ai_voice_clones FROM anon, authenticated;
REVOKE ALL ON TABLE public.ai_voice_cycles FROM anon, authenticated;
GRANT ALL ON TABLE public.ai_voice_clones TO service_role;
GRANT ALL ON TABLE public.ai_voice_cycles TO service_role;
