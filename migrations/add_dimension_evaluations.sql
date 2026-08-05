-- willab — DIMENSION EVALUATIONS + FROZEN REFERENCE DISTRIBUTION
-- (SPEC.md v3 D26, Appendix G §G.5/§G.7/§G.9; build prompt: docs/PROMPT-drift-layer.md)
--
-- WHY THIS EXISTS. Appendix G's audit queries are all written against a table
-- called `dimension_evaluations`. There was no such table. Per-dimension
-- measures live today as individual columns scattered across several tables
-- (wpm, pause_ms, energy_ratio, confidence_score, pitch_variance_ideal, ...),
-- which makes "has the distribution of dimension X drifted?" unanswerable
-- without a bespoke query per dimension. This normalises them: one row per
-- (recording, dimension, benchmark_version), so PSI and the p-chart are one
-- query each instead of N.
--
-- WHAT THIS IS FOR, PRECISELY. It is a REGRESSION detector, not a CORRECTNESS
-- detector (Appendix G.1.1). It answers "did something change under us" — an
-- ASR upgrade, a VAD change, a segmentation edit shifting word bucketing. It
-- cannot answer "is this dimension measuring anything real", because there is
-- no external criterion in the loop. A green dashboard means nothing moved.
-- It never means the dimensions are right.
--
-- NOT SURFACED (AC-9). Nothing in either table may enter a client-facing
-- schema, payload or comment: not a decile, not a fire rate, not a PSI value,
-- not a control limit. This is an internal audit surface. RLS is ON with no
-- policies, which is service-role-only in Supabase.
--
-- COLUMN NOTES — the four that are load-bearing and non-obvious
--
--   benchmark_version   Without it, CHANGING A THRESHOLD IS INDISTINGUISHABLE
--                       FROM THE POPULATION DRIFTING. Both show up as a step
--                       in the fire rate. It is part of the uniqueness key on
--                       purpose: re-running the same version REPLACES the row,
--                       a new version ADDS one, so the p-chart can group by it
--                       and see the discontinuity for what it is.
--
--   benchmark_tier      The p-chart is meaningful ONLY for ABSOLUTE (T1/T2)
--                       thresholds. For CORPUS_REL the fire rate is pinned BY
--                       CONSTRUCTION — if the threshold IS the 10th percentile
--                       then ~10% fire definitionally, and charting it yields a
--                       monitor that can never signal (Appendix G.5). Stored so
--                       the exclusion is a WHERE clause, not a convention.
--
--   insufficient_data   Appendix F.5 makes "could not compute this" a
--                       first-class outcome. `fired` is NULL in that case, not
--                       false: writing false would book a non-computation as a
--                       real negative, inflating the p-chart denominator and
--                       deflating every fire rate. The CHECK below makes the
--                       pair structurally exclusive rather than remembered —
--                       the same shape as ck_confidence_labels_unrateable_
--                       exclusive in add_state_generic_ratings.sql, and for
--                       the same reason.
--
--   n_units             The denominator ACTUALLY used (Appendix F.3). A rate
--                       computed over a different number of units than the
--                       benchmark assumes is the denominator error F.3 exists
--                       to catch; storing it makes that auditable after the
--                       fact rather than unknowable.
--
-- THE REFERENCE MUST BE FROZEN. PSI compares the current decile distribution
-- against a fixed reference. If the reference is recomputed on a rolling
-- window it tracks the drift it is supposed to detect, PSI reads ~0 forever,
-- and the monitor becomes decorative WHILE APPEARING TO WORK. That failure is
-- silent, so an UPDATE trigger below makes it loud: a refit mints a new
-- `version` row (frozen_v2, ...) and v1 stays readable.
--
-- Nothing here drops a table or a column (standing constraint).
-- Idempotent; safe to re-run. Run in the Supabase SQL Editor.

-- ─────────────────────────────────────────────────────────────────────────────
-- 1 · dimension_evaluations
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.dimension_evaluations (
    id                BIGSERIAL PRIMARY KEY,
    recording_id      TEXT        NOT NULL,
    session_id        TEXT        NULL,
    user_id           TEXT        NOT NULL,
    dimension_id      TEXT        NOT NULL,

    raw_value         DOUBLE PRECISION NULL,   -- the measure in its own units
    decile            SMALLINT    NULL,        -- 1..10 vs the frozen reference; PSI reads this
    fired             BOOLEAN     NULL,        -- NULL iff insufficient_data (see CHECK)

    benchmark_tier    TEXT        NOT NULL,    -- T1|T2|T3|CORPUS_REL
    benchmark_version TEXT        NOT NULL,    -- part of the uniqueness key
    window_class      TEXT        NULL,        -- Appendix F: FRAME|UNIT|CYCLE|PROPORTIONAL|SESSION
    n_units           INTEGER     NULL,        -- denominator actually used (F.3)
    insufficient_data BOOLEAN     NOT NULL DEFAULT false,

    evaluated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Re-evaluating the same recording on the same dimension under the same
-- benchmark version REPLACES; a new version ADDS. See the header.
CREATE UNIQUE INDEX IF NOT EXISTS uq_dimension_evaluations_rec_dim_ver
    ON public.dimension_evaluations (recording_id, dimension_id, benchmark_version);

-- fired XOR insufficient_data. Total: exactly one of the two states holds.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_dimension_evaluations_fired_exclusive'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ADD CONSTRAINT ck_dimension_evaluations_fired_exclusive
            CHECK (
                (insufficient_data AND fired IS NULL)
                OR (NOT insufficient_data AND fired IS NOT NULL)
            );
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_dimension_evaluations_tier'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ADD CONSTRAINT ck_dimension_evaluations_tier
            CHECK (benchmark_tier IN ('T1', 'T2', 'T3', 'CORPUS_REL'));
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_dimension_evaluations_window_class'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ADD CONSTRAINT ck_dimension_evaluations_window_class
            CHECK (window_class IS NULL OR window_class IN (
                'FRAME', 'UNIT', 'CYCLE', 'PROPORTIONAL', 'SESSION'
            ));
    END IF;
END$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_dimension_evaluations_decile'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ADD CONSTRAINT ck_dimension_evaluations_decile
            CHECK (decile IS NULL OR decile BETWEEN 1 AND 10);
    END IF;
END$$;

-- The PSI pull: decile histogram per dimension over a recent window.
CREATE INDEX IF NOT EXISTS idx_dimension_evaluations_psi
    ON public.dimension_evaluations (dimension_id, evaluated_at DESC)
    INCLUDE (decile)
    WHERE decile IS NOT NULL;

-- The p-chart pull: weekly fire rate, ABSOLUTE tiers only, computed rows only.
CREATE INDEX IF NOT EXISTS idx_dimension_evaluations_pchart
    ON public.dimension_evaluations (dimension_id, benchmark_tier, evaluated_at DESC)
    WHERE insufficient_data = false;

-- The DIF pull (deferred, stage 5): join to user attributes by user.
CREATE INDEX IF NOT EXISTS idx_dimension_evaluations_user_dim
    ON public.dimension_evaluations (user_id, dimension_id);

ALTER TABLE public.dimension_evaluations ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.dimension_evaluations IS
    'SPEC.md v3 D26 / Appendix G — one row per (recording, dimension, '
    'benchmark_version). Feeds PSI and the p-chart. A REGRESSION detector, '
    'not a correctness detector (G.1.1). Internal audit surface: nothing here '
    'may reach a client-facing schema or any user-facing copy (AC-9).';

COMMENT ON COLUMN public.dimension_evaluations.benchmark_version IS
    'Part of the uniqueness key. Without it, a threshold change is '
    'indistinguishable from population drift — both appear as a step in the '
    'fire rate.';

COMMENT ON COLUMN public.dimension_evaluations.insufficient_data IS
    'Appendix F.5 — "could not compute" is a first-class outcome. fired is '
    'NULL when this is true; writing false would book a non-computation as a '
    'real negative and deflate every fire rate.';

-- ─────────────────────────────────────────────────────────────────────────────
-- 2 · reference_distribution  (frozen; see header)
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.reference_distribution (
    version      TEXT        NOT NULL,           -- 'frozen_v1', 'frozen_v2', ...
    dimension_id TEXT        NOT NULL,
    decile       SMALLINT    NOT NULL,
    pct          DOUBLE PRECISION NOT NULL,      -- share of mass in this decile, 0..1
    n_at_freeze  INTEGER     NULL,               -- how much data the reference rests on
    frozen_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (version, dimension_id, decile)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_reference_distribution_bounds'
    ) THEN
        ALTER TABLE public.reference_distribution
            ADD CONSTRAINT ck_reference_distribution_bounds
            CHECK (decile BETWEEN 1 AND 10 AND pct >= 0.0 AND pct <= 1.0);
    END IF;
END$$;

-- IMMUTABILITY. A reference that moves tracks the drift it should detect, and
-- PSI silently reads ~0 forever. Blocking UPDATE turns a silent failure into a
-- loud one: refits mint a new `version`, they do not edit an old one.
CREATE OR REPLACE FUNCTION public.reference_distribution_is_frozen()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION
        'reference_distribution is frozen (version=%). A refit inserts a NEW '
        'version (frozen_v2, ...); it never updates an existing one. See '
        'Appendix G.7 and migrations/add_dimension_evaluations.sql.',
        OLD.version;
END$$;

-- Postgres grants EXECUTE on a new function to PUBLIC by default, and
-- PostgREST publishes it at /rest/v1/rpc/<name> — so without these REVOKEs
-- anyone holding the anon key out of the browser bundle could call it. RLS
-- does not cover this; RLS is table-level.
REVOKE ALL ON FUNCTION public.reference_distribution_is_frozen() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reference_distribution_is_frozen() FROM anon;
REVOKE ALL ON FUNCTION public.reference_distribution_is_frozen() FROM authenticated;

DROP TRIGGER IF EXISTS trg_reference_distribution_frozen
    ON public.reference_distribution;
CREATE TRIGGER trg_reference_distribution_frozen
    BEFORE UPDATE ON public.reference_distribution
    FOR EACH ROW EXECUTE FUNCTION public.reference_distribution_is_frozen();

ALTER TABLE public.reference_distribution ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.reference_distribution IS
    'Frozen decile distribution per dimension, the PSI baseline. UPDATE is '
    'blocked by trigger: a refit (PSI >= 0.20) inserts a new version and '
    'leaves the old one readable. Appendix G.7.';

NOTIFY pgrst, 'reload schema';

-- down:
--   DROP TRIGGER IF EXISTS trg_reference_distribution_frozen ON public.reference_distribution;
--   DROP FUNCTION IF EXISTS public.reference_distribution_is_frozen();
--   DROP TABLE IF EXISTS public.reference_distribution;
--   DROP TABLE IF EXISTS public.dimension_evaluations;
