-- 0253 · intervention_arms — the experiment's record. PM-8.
--
-- WHY THIS IS BLOCKING, not a nice-to-have. Once the manager engine is live,
-- 12% of (user, dimension) pairs receive nothing and 20% of notes that won
-- triage are deliberately withheld. Those users pay a real cost in feedback,
-- and the ONLY thing it buys is a causal claim later. If the arm assignment
-- is not stored next to the outcome they pay the cost and we get nothing back
-- — and from outside it looks exactly like a working experiment. Running the
-- controls without this table is strictly WORSE than not running them.
--
-- ONE ROW PER (session, dimension) CONSIDERED, not per surfaced note. Per-note
-- would give the untreated arms no rows at all and the table would record only
-- the treatment group, which is the same defect as measuring only the people
-- who answered.
--
-- NOT MERGED INTO dimension_evaluations. That table is MEASUREMENTS (Appendix
-- G); this is DECISIONS and ARMS. Joining them is right; merging them puts two
-- grains and two retention arguments in one place.
--
-- THE SALTS ARE STAMPED PER ROW and are the field most likely to be dropped.
-- Assignment is a pure function of (salt, user_id, dimension), so rows written
-- either side of a salt change belong to TWO DIFFERENT EXPERIMENTS with no way
-- to tell them apart afterwards. Same defect as benchmark_version in the
-- evaluation key (D30b): without it, a policy change and a population shift
-- are indistinguishable.
--
-- TWO LESSONS FROM 2026-08-06 APPLIED HERE DELIBERATELY:
--
--   1. The unique index is NOT PARTIAL. PostgreSQL cannot infer a partial
--      unique index as an ON CONFLICT arbiter unless the statement repeats the
--      predicate, and PostgREST's `on_conflict` emits columns only — so a
--      predicate here would make every write raise 42P10 and, because the
--      writer swallows exceptions, do it silently forever. (0251.)
--   2. Every numeric column is DOUBLE PRECISION, never INTEGER. `priority` is
--      a product of floats and the rates are fractions; an INTEGER column
--      would raise 22P02 on the first write, take the whole batch with it, and
--      again do so silently. (0252.)
--
-- AC-9. INTERNAL ONLY. Priority values, arm assignments and rates are
-- arbitration inputs and must never reach a client-facing schema or any
-- user-visible copy. RLS is ON with no policies; the service role bypasses it,
-- which is the only intended writer.
--
-- Idempotent. Safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS public.intervention_arms (
    id                BIGSERIAL PRIMARY KEY,

    session_id        TEXT        NOT NULL,
    user_id           TEXT        NULL,       -- NULL = unattributed, no arm
    dimension_id      TEXT        NOT NULL,

    -- CONTROL      gamma_control holdout — permanent, per (user, dimension)
    -- WITHHELD     won triage, deliberately not shown (within-subject)
    -- EXPLORE      surfaced as a rank-2 probe (epsilon_explore)
    -- TREATED      surfaced normally
    -- NOT_SELECTED considered and lost — budget, collision, cooldown, PPV
    arm               TEXT        NOT NULL,

    priority          DOUBLE PRECISION NULL,  -- NULL where never ranked
    -- NULL for CONTROL: the holdout is removed from the pool BEFORE ranking,
    -- so whether it would have won is genuinely unknown rather than false.
    -- Recording that as NULL keeps the aggregate comparison honest; ranking
    -- before the holdout would make it knowable, if the analysis ever needs it.
    would_have_surfaced BOOLEAN   NULL,
    surfaced          BOOLEAN     NOT NULL DEFAULT false,
    form              TEXT        NULL,       -- FIRST_SHOWING / REFRAME / ...

    -- The policy in force AT THE TIME. Never read these from code at analysis
    -- time — the constants move, and a row must stay interpretable against the
    -- policy that produced it.
    control_salt      TEXT        NULL,
    withhold_salt     TEXT        NULL,
    gamma             DOUBLE PRECISION NULL,
    withhold_rate     DOUBLE PRECISION NULL,
    exploration_rate  DOUBLE PRECISION NULL,

    evaluated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_intervention_arms_arm'
    ) THEN
        ALTER TABLE public.intervention_arms
            ADD CONSTRAINT ck_intervention_arms_arm
            CHECK (arm IN ('CONTROL', 'WITHHELD', 'EXPLORE',
                           'TREATED', 'NOT_SELECTED'));
    END IF;
END$$;

-- A surfaced row is TREATED or EXPLORE and nothing else. Without this the
-- withheld arm can be quietly corrupted into the treated one by a caller bug,
-- and the comparison would still look populated.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_intervention_arms_surfaced_agrees'
    ) THEN
        ALTER TABLE public.intervention_arms
            ADD CONSTRAINT ck_intervention_arms_surfaced_agrees
            CHECK (
                (surfaced AND arm IN ('TREATED', 'EXPLORE'))
                OR (NOT surfaced AND arm IN ('CONTROL', 'WITHHELD',
                                             'NOT_SELECTED'))
            );
    END IF;
END$$;

-- THE ARBITER. Deliberately non-partial — see the header.
CREATE UNIQUE INDEX IF NOT EXISTS uq_intervention_arms_session_dim
    ON public.intervention_arms (session_id, dimension_id);

-- The analysis read: "how did this (user, dimension) pair fare over time",
-- which is the between-subject comparison gamma_control exists to enable.
CREATE INDEX IF NOT EXISTS idx_intervention_arms_user_dim
    ON public.intervention_arms (user_id, dimension_id, evaluated_at DESC);

CREATE INDEX IF NOT EXISTS idx_intervention_arms_arm
    ON public.intervention_arms (arm, evaluated_at DESC);

ALTER TABLE public.intervention_arms ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.intervention_arms IS
    'PM-8. One row per (session, dimension) CONSIDERED by the manager engine, '
    'with the experiment arm and the policy in force. INTERNAL — AC-9: never '
    'client-facing. The health check is SELECT arm, COUNT(*) GROUP BY arm: '
    'roughly 12% CONTROL and 20% WITHHELD among what would have surfaced. An '
    'EMPTY CONTROL ARM MEANS THE CONTROLS ARE RUNNING AND THE RECORD IS NOT, '
    'which is the silent failure this table exists to prevent.';

COMMIT;

-- ROLLBACK:
--   DROP TABLE IF EXISTS public.intervention_arms;
