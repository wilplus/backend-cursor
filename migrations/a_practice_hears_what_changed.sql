-- 0409 · a practice hears what changed (founder 2026-10-01, F5; Phase 3 of
-- the after-practice paths)
--
-- WHY. "After a practice the speaker judges Yes or In-between, one signed
-- sentence names what measurably changed. If nothing measurably changed, a
-- plain 'Good job'. It is practice feedback, not a Feedback item, and
-- carries no budget." (F5.) A practice that did not land hears an
-- encouragement instead. After the first practice that lands the speaker
-- may hear Bold voices: their own landed attempt first, then a coach's
-- model readings (others' shared clips wait for Phase 4 and counsel), plays
-- only, nothing judged, no names. Each of those steps is shown at most once
-- per Take; a "heard" receipt is kept per play.
--
-- WHAT. One nullable column on confident_voice_practice (the sentence said,
-- with its key, lane and rule version, for the coach and the audit); three
-- append-only tables: coach_readings (a coach's own recorded readings, the
-- coach agreement covering their use), after_practice_steps (once per
-- Take per step), bold_voices_plays (the receipt). Additive; idempotent; no
-- env var. Dark: Config.PRAISE_AFTER_PRACTICE_ENABLED is False, so nothing
-- is written until a reviewed change flips it.
--
-- Rollback (a new forward migration): drop the column and the three tables.

BEGIN;

ALTER TABLE public.confident_voice_practice
    ADD COLUMN IF NOT EXISTS after_practice JSONB NULL;
COMMENT ON COLUMN public.confident_voice_practice.after_practice IS
    'What the speaker heard after this practice (0409, F5): the sentence''s '
    'key, lane and rule version, about the attempt they landed on (or the '
    'encouragement on a dismissal). Practice feedback, never a Feedback '
    'item; read by no scorer.';

CREATE TABLE IF NOT EXISTS public.coach_readings (
    id            uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id      text        NOT NULL,
    passage       text        NOT NULL,
    media_url     text        NOT NULL,
    media_kind    text        NOT NULL,
    published_at  timestamptz NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coach_readings_media_kind_check CHECK (media_kind IN ('audio', 'video')),
    CONSTRAINT coach_readings_passage_len CHECK (length(btrim(passage)) BETWEEN 1 AND 2000)
);
CREATE INDEX IF NOT EXISTS coach_readings_published_idx
    ON public.coach_readings (published_at DESC) WHERE published_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS coach_readings_coach_idx
    ON public.coach_readings (coach_id, created_at DESC);
ALTER TABLE public.coach_readings ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_readings IS
    'A coach''s own model readings (0409; founder 2026-10-01, Phase 3): a '
    'passage and the coach''s recording of it, played to speakers in Bold '
    'voices once published, without the coach''s name. The coach agreement '
    'covers the use. Purged with the coach.';

CREATE TABLE IF NOT EXISTS public.after_practice_steps (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   text        NOT NULL,
    take_session_id text        NOT NULL,
    step            text        NOT NULL,
    shown_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT after_practice_steps_step_check
        CHECK (step IN ('bridge', 'lend_your_ear', 'bold_voices')),
    CONSTRAINT after_practice_steps_once UNIQUE (take_session_id, step)
);
ALTER TABLE public.after_practice_steps ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.after_practice_steps IS
    'Which after-practice steps this Take has shown (0409): the bridge, Lend '
    'your ear (Phase 4), Bold voices; each at most once per Take. Purged with '
    'the Take.';

CREATE TABLE IF NOT EXISTS public.bold_voices_plays (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   text        NOT NULL,
    take_session_id text        NOT NULL,
    clip_kind       text        NOT NULL,
    clip_id         text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT bold_voices_plays_kind_check
        CHECK (clip_kind IN ('own_attempt', 'coach_reading'))
);
CREATE INDEX IF NOT EXISTS bold_voices_plays_take_idx
    ON public.bold_voices_plays (take_session_id);
CREATE INDEX IF NOT EXISTS bold_voices_plays_created_idx
    ON public.bold_voices_plays (created_at);
ALTER TABLE public.bold_voices_plays ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.bold_voices_plays IS
    'The speaker heard a Bold voices clip (0409): a receipt, nothing judged. '
    'Purged with the Take.';

COMMIT;
