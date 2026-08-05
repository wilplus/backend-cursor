-- willab — DIMENSION EVALUATIONS: snippet grain.
-- Written 2026-08-05. Amends add_dimension_evaluations.sql (0247).
-- (SPEC.md v3 D26/D30, Appendix G §G.5/§G.7.)
--
-- WHY THIS AMENDMENT EXISTS. 0247 was written against Appendix G, which
-- assumed one evaluation per RECORDING. Wiring the drift layer to the live
-- path showed that is not where the measures are: every metric this layer can
-- actually watch today — wpm, fillers, pause_ms, dynamic_db, pitch_center,
-- energy — is computed PER SNIPPET and only then averaged into session
-- globals (services/session_metrics.compute_session_global_metrics).
--
-- Storing a snippet id in a column called recording_id would have been the
-- kind of almost-working the spec exists to prevent, so the column joins the
-- table properly and recording_id is relaxed to nullable. 0247 is NOT edited;
-- this runs after it. Nothing is dropped.
--
-- ─────────────────────────────────────────────────────────────────────────
-- THE GRAIN DISTINCTION THAT MATTERS, AND IT IS NOT COSMETIC
--
--   STORAGE grain  = snippet. Maximum information, and it is the level the
--                    numbers are actually produced at.
--   ANALYSIS grain = session. PSI and the p-chart MUST aggregate to one
--                    observation per session before computing.
--
-- Why analysis cannot use the storage grain: snippets within a session are
-- NOT INDEPENDENT. One talkative user recording thirty snippets in a single
-- session contributes thirty correlated rows. Treating them as thirty
-- independent observations inflates n, narrows the p-chart's control limits
-- by ~sqrt(30), and makes PSI confident about a shift that is really one
-- person having a long day. The monitor would then fire on its own sampling
-- rather than on drift — the exact false-alarm mode that gets a monitor
-- switched off and ignored.
--
-- This is enforced by CONVENTION in the queries, not by the schema, because
-- the schema cannot know it. It is written here because the query that
-- forgets it still returns a number, and the number looks fine.
-- ─────────────────────────────────────────────────────────────────────────
--
-- Idempotent; safe to re-run. Run in the Supabase SQL Editor AFTER 0247.

ALTER TABLE public.dimension_evaluations
    ADD COLUMN IF NOT EXISTS snippet_id TEXT NULL;

-- ─────────────────────────────────────────────────────────────────────────
-- CONSTRAINT DEFECT IN 0247, FOUND BY WIRING IT. 0247 made fired and
-- insufficient_data a strict XOR: fired IS NULL if and only if the data was
-- insufficient. Wiring the live path showed there are THREE states, not two:
--
--   1. computed AND benchmarked    fired = true/false   insufficient = false
--   2. computed, NO BENCHMARK YET  fired = NULL         insufficient = false
--   3. not computable              fired = NULL         insufficient = true
--
-- State 2 is most of what exists today: wpm, pause_ms, dynamic_db,
-- pitch_center and energy are all measured on every snippet, and none of
-- them has a fire threshold in code yet. Under the XOR the only way to store
-- them was to fabricate `fired = false` (a decision nobody made, which
-- deflates every fire rate) or to claim `insufficient_data` (false — the
-- measure computed fine). Both corrupt the thing the table exists to watch.
--
-- The correct constraint is an IMPLICATION, not a biconditional:
-- insufficient_data ⟹ fired IS NULL. A measurement without a decision is a
-- legitimate row, and PSI wants it — PSI reads `decile`, not `fired`.
--
-- CONSEQUENCE FOR THE P-CHART: it must filter `fired IS NOT NULL`, which it
-- should have done anyway. Encoded in the query, not assumable.
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE public.dimension_evaluations
    DROP CONSTRAINT IF EXISTS ck_dimension_evaluations_fired_exclusive;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_dimension_evaluations_fired_null_when_insufficient'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ADD CONSTRAINT ck_dimension_evaluations_fired_null_when_insufficient
            CHECK (NOT insufficient_data OR fired IS NULL);
    END IF;
END$$;

-- recording_id: NOT NULL -> NULL. Guarded so a re-run is a no-op.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = 'dimension_evaluations'
           AND column_name  = 'recording_id'
           AND is_nullable  = 'NO'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ALTER COLUMN recording_id DROP NOT NULL;
    END IF;
END$$;

-- user_id: NOT NULL -> NULL. The live scoring path (session_metrics) works
-- from snippets and does not carry the user through; requiring it would mean
-- either an extra lookup per snippet on a hot path, or dropping the row
-- entirely. DIF (deferred, stage 5) needs user_id and will join it from the
-- session — but PSI and the p-chart never do, and blocking today's monitor
-- for tomorrow's audit is the wrong trade.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = 'dimension_evaluations'
           AND column_name  = 'user_id'
           AND is_nullable  = 'NO'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ALTER COLUMN user_id DROP NOT NULL;
    END IF;
END$$;

-- A row must anchor to SOMETHING. Without this, relaxing recording_id would
-- permit an evaluation attached to nothing at all, which is unjoinable and
-- therefore silently invisible to every audit query.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'ck_dimension_evaluations_has_anchor'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ADD CONSTRAINT ck_dimension_evaluations_has_anchor
            CHECK (snippet_id IS NOT NULL
                   OR recording_id IS NOT NULL
                   OR session_id IS NOT NULL);
    END IF;
END$$;

-- 0247's unique index assumed recording_id was always present; it becomes a
-- PARTIAL index so it still holds for recording-anchored rows, and a second
-- partial index covers the snippet-anchored ones. Re-evaluating the same
-- snippet on the same dimension under the same benchmark version REPLACES;
-- a new benchmark_version ADDS a row, which is what lets the p-chart read a
-- threshold change as a discontinuity rather than as drift.
DROP INDEX IF EXISTS public.uq_dimension_evaluations_rec_dim_ver;

CREATE UNIQUE INDEX IF NOT EXISTS uq_dimension_evaluations_rec_dim_ver
    ON public.dimension_evaluations (recording_id, dimension_id, benchmark_version)
    WHERE recording_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_dimension_evaluations_snip_dim_ver
    ON public.dimension_evaluations (snippet_id, dimension_id, benchmark_version)
    WHERE snippet_id IS NOT NULL;

-- The PSI pull aggregates to session grain (see the header), so session_id
-- leads the index.
CREATE INDEX IF NOT EXISTS idx_dimension_evaluations_session_dim
    ON public.dimension_evaluations (session_id, dimension_id, evaluated_at DESC)
    WHERE session_id IS NOT NULL;

COMMENT ON COLUMN public.dimension_evaluations.snippet_id IS
    'The evaluation unit for every measure computed today (wpm, fillers, '
    'pause_ms, dynamic_db, pitch_center, energy — all per snippet). STORAGE '
    'is snippet grain; ANALYSIS must aggregate to session grain first, '
    'because snippets within a session are not independent and treating them '
    'as such narrows the control limits by ~sqrt(snippets-per-session).';

-- ─────────────────────────────────────────────────────────────────────────
-- SECOND DEFECT IN 0247, ALSO FOUND BY WIRING IT. reference_distribution
-- stored (decile, pct) — the reference MASS per bucket. That is not enough to
-- compute PSI, and the way it fails is silent.
--
-- If the reference is the deciles of the reference period, then every bucket
-- holds exactly 10% BY CONSTRUCTION, so `pct` is 0.1 ten times over and
-- carries no information. What is actually needed to score a NEW observation
-- is the CUT POINTS: the boundaries that say which bucket a raw value falls
-- in. Without them there is no way to assign `decile` on a live row, so the
-- histogram never populates and PSI reads 0.0 against an empty comparison —
-- a monitor that reports STABLE forever while measuring nothing.
--
-- `pct` is KEPT rather than replaced: it stays meaningful if a future
-- reference uses fixed (non-decile) bins where the expected mass is not
-- uniform. `upper_bound` is NULL on the top bucket, which is +infinity.
-- ─────────────────────────────────────────────────────────────────────────

ALTER TABLE public.reference_distribution
    ADD COLUMN IF NOT EXISTS upper_bound DOUBLE PRECISION NULL;

COMMENT ON COLUMN public.reference_distribution.upper_bound IS
    'Inclusive upper cut point for this bucket; NULL on decile 10 (+inf). '
    'This is what a live raw_value is bucketed against — pct alone cannot '
    'assign a decile, and a reference built from deciles has pct = 0.1 in '
    'every bucket by construction.';

-- Re-asserted here for anyone who ran 0247 BEFORE the REVOKEs were added to
-- it. Postgres grants EXECUTE to PUBLIC on function creation and PostgREST
-- publishes it at /rest/v1/rpc/<name>; RLS is table-level and does not cover
-- it. Idempotent and harmless when 0247 already revoked.
REVOKE ALL ON FUNCTION public.reference_distribution_is_frozen() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reference_distribution_is_frozen() FROM anon;
REVOKE ALL ON FUNCTION public.reference_distribution_is_frozen() FROM authenticated;

NOTIFY pgrst, 'reload schema';

-- down:
--   DROP INDEX IF EXISTS public.uq_dimension_evaluations_snip_dim_ver;
--   DROP INDEX IF EXISTS public.idx_dimension_evaluations_session_dim;
--   ALTER TABLE public.dimension_evaluations
--       DROP CONSTRAINT IF EXISTS ck_dimension_evaluations_has_anchor;
--   ALTER TABLE public.dimension_evaluations DROP COLUMN IF EXISTS snippet_id;
