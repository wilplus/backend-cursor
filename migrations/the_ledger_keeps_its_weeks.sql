-- The ledger keeps its weeks (founder 2026-09-30, C9, L4 to L7; build plan
-- group 5: ML-3, ML-6, ML-7).
--
-- 1. LEDGER SNAPSHOTS. The weekly learning job writes one row per ISO week:
--    the whole ledger as data (counts about the machine, never about a
--    person), the cues that cleared their bar, and the migration text a
--    promotion would merge. One row per week: a second fire in the same
--    week replaces it, so a double-fired cron writes nothing twice.
--
-- 2. THE RESEARCH ROLE. A read-only role, like coach_users and admin_users:
--    an email the founder inserts by hand. It may call the research reads
--    and nothing else (routes/admin.require_research_read).
--
-- 3. THE GOLDEN SET. The founder's own judgements of moments, one per
--    (surface, moment, judge), append-only; a surface's set is sealed with
--    a hash once, and the evaluation reads the sealed set (ML-10). The
--    judgements are the founder's, never a coach's or a machine's (L3).
--
-- Idempotent. No env var. RLS on every new table.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ledger_snapshots (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    week_start       date        NOT NULL UNIQUE,
    ledger_version   text        NOT NULL,
    snapshot         jsonb       NOT NULL,
    ready_cues       text[]      NOT NULL DEFAULT '{}',
    migration_drafts jsonb       NOT NULL DEFAULT '{}'::jsonb,
    exported         jsonb       NOT NULL DEFAULT '[]'::jsonb,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.ledger_snapshots ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.ledger_snapshots IS
    'One row per ISO week from the weekly learning job (ML-3): the ledger as '
    'data, the cues that cleared their bar, the migration text a promotion '
    'would merge. Counts about the system; nothing about a person.';

CREATE TABLE IF NOT EXISTS public.research_users (
    email      text        PRIMARY KEY,
    is_active  boolean     NOT NULL DEFAULT true,
    added_by   text        NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.research_users ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.research_users IS
    'The read-only research role (ML-6): may call the research reads and '
    'nothing else. The founder inserts an email by hand.';

CREATE TABLE IF NOT EXISTS public.golden_judgements (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    surface         text        NOT NULL,
    snippet_id      text        NOT NULL,
    take_session_id text        NULL,
    judge_email     text        NOT NULL,
    value           text        NOT NULL CHECK (value IN (
        'yes', 'in_between', 'no', 'not_sure', 'audio_unclear')),
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT golden_judgements_one_per_moment UNIQUE (surface, snippet_id, judge_email)
);
CREATE INDEX IF NOT EXISTS golden_judgements_surface_idx
    ON public.golden_judgements (surface, judge_email, created_at);
ALTER TABLE public.golden_judgements ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.golden_sets (
    surface     text        PRIMARY KEY,
    judge_email text        NOT NULL,
    count       integer     NOT NULL,
    sha256      text        NOT NULL,
    sealed_at   timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.golden_sets ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.golden_sets IS
    'A surface''s golden set, sealed once with the hash of its judgements '
    '(ML-10 reads it instead of the engineering seeds).';

COMMIT;
