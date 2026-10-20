-- will_writes_the_founder_a_sunday_case (Will learning plan, step 2,
-- founder 2026-10-20: "start step 2")
--
-- On Sunday at 6 pm the founder's local time, and whenever they ask, Will
-- writes one note in the chat in the founder's own case form (CASE AT HAND,
-- which of the four bugs it was, the principles applied and how they were
-- weighed, reflections, a new principle). Founder only, like the notebook.
--
--   sunday_notes                     One row per note: the week it covers,
--                                    whether it was Sunday's or asked for,
--                                    what it said, which bug it named, the
--                                    founder's "Old" or "New" for that bug,
--                                    and the principle Will suggested (and
--                                    the Life Panel item, once added).
--   voice_notebook_consent.time_zone The browser's time zone, so "Sunday at
--                                    6 pm" is the founder's own.
--
-- Read and written by the backend (service role) only. No environment
-- variable needed. Idempotent and additive: IF NOT EXISTS everywhere,
-- nothing dropped. One transaction; explicit grants to service_role.

BEGIN;

CREATE TABLE IF NOT EXISTS public.sunday_notes (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id            UUID NOT NULL,
    week_start         DATE NOT NULL,
    source             TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'claimed',
    body               TEXT,
    pattern            TEXT,
    pattern_known      TEXT,
    new_principle      TEXT,
    principle_item_id  UUID,
    principle_declined BOOLEAN NOT NULL DEFAULT false,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sunday_notes_source_check CHECK (source IN ('sunday', 'asked')),
    CONSTRAINT sunday_notes_status_check CHECK (status IN ('claimed', 'written', 'failed')),
    CONSTRAINT sunday_notes_pattern_check CHECK (pattern IS NULL OR pattern IN
        ('too_much_pleasure', 'blind_spots', 'hubris', 'wishful_thinking')),
    CONSTRAINT sunday_notes_known_check CHECK (pattern_known IS NULL OR pattern_known IN ('old', 'new')),
    CONSTRAINT sunday_notes_body_len CHECK (body IS NULL OR char_length(body) <= 8000),
    CONSTRAINT sunday_notes_principle_len CHECK (new_principle IS NULL OR char_length(new_principle) <= 500)
);

-- One Sunday note per week; notes asked for are not limited.
CREATE UNIQUE INDEX IF NOT EXISTS sunday_notes_one_sunday_per_week
    ON public.sunday_notes (user_id, week_start) WHERE source = 'sunday';

CREATE INDEX IF NOT EXISTS sunday_notes_user_idx
    ON public.sunday_notes (user_id, created_at);

ALTER TABLE public.sunday_notes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.sunday_notes FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.sunday_notes TO service_role;

ALTER TABLE public.voice_notebook_consent
    ADD COLUMN IF NOT EXISTS time_zone TEXT;

COMMIT;
