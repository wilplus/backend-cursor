-- dev_tasks — GPT-4o-authored, user-story-centered tasks derived from dev_bugs,
-- shown as a prioritized backlog in the "user stories · tasks" view at
-- dev.willpowerlab.com. See routes/dev_bugs.py + services/dev_tasks.py.
--
-- Ordering (see services/dev_tasks.py): sort by `order_key` ASC — highest
-- priority on top. Theme rank is FIXED (T1>T2>T3>T4); epic_rank / story_rank are
-- assigned by GPT-4o but FROZEN the first time an epic/story appears, so the list
-- stays stable as tasks amass. A manual drag sets `pinned=true` + a midpoint
-- order_key that survives future GPT-4o runs. `phase` = the 1-10 delivery phase
-- from the Product Delivery Master doc (display/context only).
--
-- Idempotent; safe to re-run.

CREATE TABLE IF NOT EXISTS public.dev_tasks (
    id           BIGSERIAL   PRIMARY KEY,
    bug_id       BIGINT      REFERENCES public.dev_bugs(id) ON DELETE SET NULL,
    body         TEXT        NOT NULL DEFAULT '',   -- the user-story-centered task text (shown + copied)
    user_story   TEXT,                              -- "As a <role>, I want <journey fragment>, so that <payoff>"
    theme        TEXT,                              -- 'T1'..'T4'
    epic         TEXT,                              -- e.g. '1.2 Ideal-Text & Recording UX'
    phase        SMALLINT,                          -- 1..10 delivery phase (optional)
    epic_rank    INTEGER     NOT NULL DEFAULT 50,   -- crucialness of the epic within the theme (frozen per epic)
    story_rank   INTEGER     NOT NULL DEFAULT 50,   -- crucialness of the story within the epic (frozen per story)
    priority     SMALLINT    NOT NULL DEFAULT 2,    -- 1=P1 (high) .. 3=P3
    order_key    DOUBLE PRECISION NOT NULL DEFAULT 0, -- effective sort position; lower = higher on the list
    pinned       BOOLEAN     NOT NULL DEFAULT false, -- true once manually dragged (GPT-4o won't move it again)
    status       TEXT        NOT NULL DEFAULT 'active', -- 'active' | 'archived'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    archived_at  TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS dev_tasks_status_order_idx ON public.dev_tasks (status, order_key, id);
CREATE INDEX IF NOT EXISTS dev_tasks_theme_epic_idx   ON public.dev_tasks (theme, epic);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='dev_tasks_status_check') THEN
        ALTER TABLE public.dev_tasks ADD CONSTRAINT dev_tasks_status_check
            CHECK (status IN ('active','archived'));
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='dev_tasks_priority_check') THEN
        ALTER TABLE public.dev_tasks ADD CONSTRAINT dev_tasks_priority_check
            CHECK (priority BETWEEN 1 AND 3);
    END IF;
END $$;

ALTER TABLE public.dev_tasks ENABLE ROW LEVEL SECURITY;
