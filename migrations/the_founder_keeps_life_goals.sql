-- the_founder_keeps_life_goals (Will learning plan, step 3; founder
-- 2026-10-26, N172: "build the life goals now", kept in the Life Panel, a
-- space may hold more than one goal)
--
-- Life goals the Dalio way, asked in the Lounge after the first # note and
-- walked in a lens one goal at a time. Founder only for now (ring 6).
--
--   life_goals          One row per goal: its space (personal, career, the
--                       greater good), its status (a draft while the lens is
--                       open, active once set, replaced when a newer goal
--                       took its place) and its ladder as JSON: the goal,
--                       the words it was drafted from, the want held
--                       knowingly, what they give up, the horizon and the
--                       steps worked back from it to the quarter.
--   life_goal_versions  Every change to a step, dated, never overwritten:
--                       the step, the words before and after.
--   life_goal_asks      How often the Lounge asked "your life goals" and the
--                       last answer (asked once after the first note, once
--                       more after the next if the answer was Not now).
--   feature_rings row   life_goals, ring 6 (the founder's ring).
--
-- Part of the Life Panel's store (services/life_store.py LIFE_TABLES): the
-- Life Panel's export and delete take these rows. Read and written by the
-- backend (service role) only. No environment variable needed. Idempotent
-- and additive: IF NOT EXISTS / ON CONFLICT DO NOTHING everywhere, nothing
-- dropped. One transaction; explicit grants to service_role.

BEGIN;

CREATE TABLE IF NOT EXISTS public.life_goals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL,
    space       TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'draft',
    ladder      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT life_goals_space_check CHECK (space IN ('personal', 'career', 'good')),
    CONSTRAINT life_goals_status_check CHECK (status IN ('draft', 'active', 'replaced', 'dropped')),
    CONSTRAINT life_goals_ladder_size CHECK (octet_length(ladder::text) <= 65536)
);

CREATE INDEX IF NOT EXISTS life_goals_user_idx
    ON public.life_goals (user_id, status, created_at);

ALTER TABLE public.life_goals ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.life_goals FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.life_goals TO service_role;

CREATE TABLE IF NOT EXISTS public.life_goal_versions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    goal_id     UUID NOT NULL REFERENCES public.life_goals(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    step        TEXT NOT NULL,
    before_text TEXT,
    after_text  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT life_goal_versions_step_len CHECK (char_length(step) <= 40),
    CONSTRAINT life_goal_versions_before_len CHECK (char_length(before_text) <= 4000),
    CONSTRAINT life_goal_versions_after_len CHECK (char_length(after_text) <= 4000)
);

CREATE INDEX IF NOT EXISTS life_goal_versions_goal_idx
    ON public.life_goal_versions (goal_id, created_at);
CREATE INDEX IF NOT EXISTS life_goal_versions_user_idx
    ON public.life_goal_versions (user_id);

ALTER TABLE public.life_goal_versions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.life_goal_versions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.life_goal_versions TO service_role;

CREATE TABLE IF NOT EXISTS public.life_goal_asks (
    user_id     UUID PRIMARY KEY,
    asked       INTEGER NOT NULL DEFAULT 0,
    answer      TEXT,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT life_goal_asks_answer_check CHECK (answer IS NULL OR answer IN ('start', 'not_now'))
);

ALTER TABLE public.life_goal_asks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.life_goal_asks FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.life_goal_asks TO service_role;

INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('life_goals', 6,
        'Will learning plan step 3 (N172): life goals asked after the first '
        '# note and walked in a lens, kept in the Life Panel.',
        'migration:the_founder_keeps_life_goals')
ON CONFLICT (feature) DO NOTHING;

-- The ring row's first entry in its audit trail, as 0394 wrote for its seeds.
INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.feature = 'life_goals'
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

COMMIT;
