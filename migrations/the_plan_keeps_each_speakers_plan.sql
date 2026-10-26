-- the_plan_keeps_each_speakers_plan (the plan, N129 onward; built one to one
-- with the prototype, founder 2026-10-26, N203; ring 5, N204)
--
-- The plan: the questions a new speaker answers in the Lounge before the
-- first Take, the level and the practice days that follow, and the plan's
-- end at the deadline (frontend docs/flows/the-plan.md).
--
--   speaker_plans       One row per plan. At most one open plan (asking or
--                       active) per person; an ended or replaced plan stays
--                       as history (N140).
--   plan_answers        Each answer: a voice answer's words and its
--                       readings, or a rating from 1 to 10 (never shown
--                       back to the speaker, N178).
--   plan_answer_audio   A voice answer's recording, in the database so the
--                       account purge takes it as an ordinary row
--                       (services/data_purge_registry.py), as the voice
--                       notebook does (0484). The key line's answer plays
--                       back on the plan card ("How you said it").
--   plan_level_events   Append-only: every level the plan has had, and why.
--   feature_rings row   plan, ring 5 (N204).
--
-- Read and written by the backend (service role) only. No environment
-- variable needed. Idempotent and additive: IF NOT EXISTS / ON CONFLICT DO
-- NOTHING everywhere, nothing dropped. One transaction; explicit grants to
-- service_role, as 0484.

BEGIN;

CREATE TABLE IF NOT EXISTS public.speaker_plans (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    status          TEXT NOT NULL DEFAULT 'asking',
    step            TEXT NOT NULL DEFAULT 'deadline',
    deadline        DATE,
    deadline_given  BOOLEAN NOT NULL DEFAULT false,
    practice_days   SMALLINT[] NOT NULL DEFAULT '{1,3,5}',
    level           TEXT,
    level_by        TEXT,
    facts           JSONB NOT NULL DEFAULT '{}'::jsonb,
    asked           JSONB NOT NULL DEFAULT '[]'::jsonb,
    calls           JSONB NOT NULL DEFAULT '{}'::jsonb,
    time_zone       TEXT,
    total           INTEGER,
    every_day       BOOLEAN NOT NULL DEFAULT false,
    hello_on        DATE,
    done_on         DATE,
    started_at      TIMESTAMPTZ,
    ended_at        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT speaker_plans_status_check
        CHECK (status IN ('asking', 'active', 'ending', 'ended', 'replaced')),
    CONSTRAINT speaker_plans_step_check
        CHECK (step IN ('deadline', 'why', 'followup', 'stress', 'ready',
                        'kickoff', 'summary', 'done', 'how_it_went', 'whats_next',
                        'same_event')),
    CONSTRAINT speaker_plans_level_check
        CHECK (level IS NULL OR level IN ('say_once', 'key_line', 'pauses',
                                          'voice_moves', 'make_it_yours')),
    CONSTRAINT speaker_plans_level_by_check
        CHECK (level_by IS NULL OR level_by IN ('machine', 'coach'))
);

CREATE UNIQUE INDEX IF NOT EXISTS speaker_plans_one_open_idx
    ON public.speaker_plans (user_id) WHERE status IN ('asking', 'active', 'ending');
CREATE INDEX IF NOT EXISTS speaker_plans_user_idx
    ON public.speaker_plans (user_id, created_at);

ALTER TABLE public.speaker_plans ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.speaker_plans FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.speaker_plans TO service_role;

CREATE TABLE IF NOT EXISTS public.plan_answers (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id      UUID NOT NULL REFERENCES public.speaker_plans(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL,
    kind         TEXT NOT NULL,
    moment       TEXT,
    question     TEXT,
    transcript   TEXT,
    value        SMALLINT,
    duration_ms  INTEGER,
    readings     JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT plan_answers_kind_check
        CHECK (kind IN ('why', 'key', 'audience', 'length', 'worry', 'experience',
                        'success', 'opening', 'how_it_went', 'stress', 'ready')),
    CONSTRAINT plan_answers_moment_check
        CHECK (moment IS NULL OR moment IN ('first', 'last')),
    CONSTRAINT plan_answers_value_check
        CHECK (value IS NULL OR value BETWEEN 1 AND 10),
    CONSTRAINT plan_answers_len CHECK (char_length(coalesce(transcript, '')) <= 20000)
);

CREATE INDEX IF NOT EXISTS plan_answers_plan_idx
    ON public.plan_answers (plan_id, created_at);
CREATE INDEX IF NOT EXISTS plan_answers_user_idx
    ON public.plan_answers (user_id);

ALTER TABLE public.plan_answers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.plan_answers FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.plan_answers TO service_role;

CREATE TABLE IF NOT EXISTS public.plan_answer_audio (
    answer_id     UUID PRIMARY KEY
                  REFERENCES public.plan_answers(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL,
    content_type  TEXT NOT NULL,
    audio         BYTEA NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT plan_answer_audio_size CHECK (octet_length(audio) <= 12582912)
);

CREATE INDEX IF NOT EXISTS plan_answer_audio_user_idx
    ON public.plan_answer_audio (user_id);

ALTER TABLE public.plan_answer_audio ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.plan_answer_audio FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.plan_answer_audio TO service_role;

CREATE TABLE IF NOT EXISTS public.plan_level_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_id     UUID NOT NULL REFERENCES public.speaker_plans(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    level       TEXT NOT NULL,
    reason      TEXT NOT NULL,
    by_who      TEXT NOT NULL DEFAULT 'machine',
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT plan_level_events_level_check
        CHECK (level IN ('say_once', 'key_line', 'pauses', 'voice_moves', 'make_it_yours')),
    CONSTRAINT plan_level_events_reason_check
        CHECK (reason IN ('diagnosis', 'reached', 'time', 'stuck', 'coach', 'ask_coach')),
    CONSTRAINT plan_level_events_by_check
        CHECK (by_who IN ('machine', 'coach', 'speaker'))
);

CREATE INDEX IF NOT EXISTS plan_level_events_plan_idx
    ON public.plan_level_events (plan_id, created_at);
CREATE INDEX IF NOT EXISTS plan_level_events_user_idx
    ON public.plan_level_events (user_id);

ALTER TABLE public.plan_level_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.plan_level_events FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.plan_level_events TO service_role;

INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('plan', 5,
        'The plan (N203, N204): the questions before the first Take, the plan '
        'card, the practice days and the deadline, in the Lounge.',
        'migration:the_plan_keeps_each_speakers_plan')
ON CONFLICT (feature) DO NOTHING;

-- The ring row's first entry in its audit trail, as 0394 wrote for its seeds.
INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.feature = 'plan'
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

COMMIT;
