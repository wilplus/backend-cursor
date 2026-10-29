-- your_why_and_strengths_are_kept (the principles' companions; founder
-- 2026-10-28 and 29, N241 items 1 to 3, N255, signed N258; rules: frontend
-- docs/flows/principles.md §1 N and Q)
--
-- Two of the principles' companions, kept in the Life Panel's store. Ring 5
-- (people who know it is a test), each with its own ring row.
--
--   your_why            One row per person: their why, their vision and how
--                       they want to treat others, each in their own words
--                       (null until set), and the sitting's answers so far
--                       while the lens is open (draft). Q1 to Q5.
--   your_why_versions   Every change to one of the three lines, dated, never
--                       overwritten: the line, the words before and after (Q6).
--   strengths           One row per strength: its words, its state
--                       (suggested by Will, kept, archived by the person, or
--                       not now) and when each happened (N1, N2, N5).
--   strength_notes      The notes a strength gathers, newest last: the two
--                       that showed it first (or the life goals answer), then
--                       each later note that shows it at work (N2, N3). Their
--                       words are copied, so a fixed or deleted note leaves
--                       the strength's history as it was shown.
--   talk_dates          A talk date a # note named (N4), and whether the day
--                       before has brought its strength back. The plan's
--                       deadline is read from speaker_plans, not copied here.
--   feature_rings rows  your_why and strengths, ring 5.
--
-- Part of the Life Panel's store (services/life_store.py LIFE_TABLES): the
-- Life Panel's export and delete take these rows, and the account purge
-- (services/data_purge_registry.py). Read and written by the backend (service
-- role) only. No environment variable needed. Idempotent and additive: IF NOT
-- EXISTS / ON CONFLICT DO NOTHING everywhere, nothing dropped. One
-- transaction; explicit grants to service_role.

BEGIN;

CREATE TABLE IF NOT EXISTS public.your_why (
    user_id     UUID PRIMARY KEY,
    why         TEXT,
    vision      TEXT,
    treat       TEXT,
    draft       JSONB NOT NULL DEFAULT '{}'::jsonb,
    set_at      TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT your_why_why_len CHECK (char_length(why) <= 1000),
    CONSTRAINT your_why_vision_len CHECK (char_length(vision) <= 1000),
    CONSTRAINT your_why_treat_len CHECK (char_length(treat) <= 1000),
    CONSTRAINT your_why_draft_size CHECK (octet_length(draft::text) <= 65536)
);

ALTER TABLE public.your_why ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.your_why FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.your_why TO service_role;

CREATE TABLE IF NOT EXISTS public.your_why_versions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    line        TEXT NOT NULL,
    before_text TEXT,
    after_text  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT your_why_versions_line_check CHECK (line IN ('why', 'vision', 'treat')),
    CONSTRAINT your_why_versions_before_len CHECK (char_length(before_text) <= 1000),
    CONSTRAINT your_why_versions_after_len CHECK (char_length(after_text) <= 1000)
);

CREATE INDEX IF NOT EXISTS your_why_versions_user_idx
    ON public.your_why_versions (user_id, created_at);

ALTER TABLE public.your_why_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.your_why_versions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.your_why_versions TO service_role;

CREATE TABLE IF NOT EXISTS public.strengths (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    title        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'suggested',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    kept_at      TIMESTAMPTZ,
    archived_at  TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT strengths_status_check
        CHECK (status IN ('suggested', 'kept', 'archived', 'not_now')),
    CONSTRAINT strengths_title_len CHECK (char_length(title) BETWEEN 1 AND 200)
);

CREATE INDEX IF NOT EXISTS strengths_user_idx
    ON public.strengths (user_id, status, created_at);

ALTER TABLE public.strengths ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.strengths FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.strengths TO service_role;

CREATE TABLE IF NOT EXISTS public.strength_notes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strength_id  UUID NOT NULL REFERENCES public.strengths(id) ON DELETE CASCADE,
    user_id      UUID NOT NULL,
    note_id      UUID,
    source       TEXT NOT NULL DEFAULT 'note',
    body         TEXT NOT NULL,
    noted_on     DATE NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT strength_notes_source_check CHECK (source IN ('note', 'goals_answer')),
    CONSTRAINT strength_notes_body_len CHECK (char_length(body) BETWEEN 1 AND 2000)
);

CREATE INDEX IF NOT EXISTS strength_notes_strength_idx
    ON public.strength_notes (strength_id, noted_on);
CREATE INDEX IF NOT EXISTS strength_notes_user_idx
    ON public.strength_notes (user_id, note_id);

ALTER TABLE public.strength_notes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.strength_notes FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.strength_notes TO service_role;

CREATE TABLE IF NOT EXISTS public.talk_dates (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL,
    talk_on      DATE NOT NULL,
    note_id      UUID,
    reminded_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT talk_dates_one_per_day UNIQUE (user_id, talk_on)
);

ALTER TABLE public.talk_dates ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.talk_dates FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.talk_dates TO service_role;

INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('your_why', 5,
        'Your why, every day (N255, signed N258): the why, the vision and how '
        'to treat others, kept in the Life Panel; the why in the Lounge daily.',
        'migration:your_why_and_strengths_are_kept'),
       ('strengths', 5,
        'Strengths (N241, signed N258): suggested from # notes on two days, '
        'kept in the Life Panel, brought back the day before a talk.',
        'migration:your_why_and_strengths_are_kept')
ON CONFLICT (feature) DO NOTHING;

-- The ring rows' first entries in their audit trail, as 0394 wrote for its seeds.
INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.feature IN ('your_why', 'strengths')
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

COMMIT;
