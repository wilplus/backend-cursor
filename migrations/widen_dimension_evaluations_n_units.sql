-- 0252 · n_units must hold a FRACTIONAL denominator count.
--
-- THE BUG. `n_units` records "how many units the rate was computed over"
-- (Appendix F.3). It was typed INTEGER, which is right for a lexical rate —
-- the denominator is WORDS, always whole — and wrong for a temporal one,
-- where the denominator is MINUTES and a 6.55-second snippet is 0.109 of one.
--
-- session_metrics._denominator_count returns that fraction. PostgREST casts
-- JSON values through text, so the write became
--
--     '0.109'::integer   ->   ERROR: invalid input syntax for type integer
--
-- which is a hard error, not a rounding. A PostgREST insert is ONE statement
-- for the whole batch, so a single `fillers` row failing takes every row of
-- that recording with it — and record_dimension_evaluations catches, logs at
-- WARNING and returns 0, so the table simply stayed empty.
--
-- WHY IT APPEARED TODAY. Until the per-measure window fix, `wpm` carried
-- denominator="wpm" and n_units was the word COUNT — an integer. Splitting
-- `unit` from `denominator` left `fillers` as the only rate, denominated in
-- minutes, and minutes are not whole. It was masked until 0251 because the
-- partial-index arbiter was failing every write first.
--
-- THE FIX. Widen to DOUBLE PRECISION. The column has to hold both kinds of
-- denominator, and one of them is genuinely fractional, so the wider type is
-- the correct one rather than a workaround. Rounding to an integer instead
-- would store 0 minutes for every snippet under 30 seconds — a denominator of
-- zero, which is worse than a wrong one because it reads as a division error
-- rather than as a short window.
--
-- Widening is safe and non-rewriting for existing rows: every INTEGER value
-- is representable, and PostgreSQL does not need a table rewrite for
-- integer -> double precision.
--
-- Idempotent. Safe to re-run.

BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name   = 'dimension_evaluations'
           AND column_name  = 'n_units'
           AND data_type    = 'integer'
    ) THEN
        ALTER TABLE public.dimension_evaluations
            ALTER COLUMN n_units TYPE DOUBLE PRECISION;
    END IF;
END$$;

COMMENT ON COLUMN public.dimension_evaluations.n_units IS
    'How many units the rate was computed over (Appendix F.3). DOUBLE '
    'PRECISION because the denominator is WORDS for a lexical rate (whole) '
    'and MINUTES for a temporal one (fractional — a 6.55 s snippet is 0.109 '
    'of a minute). NULL for a LEVEL, which divides by nothing.';

COMMIT;

-- ROLLBACK (lossy — truncates every fractional minute count to 0):
--   ALTER TABLE public.dimension_evaluations
--       ALTER COLUMN n_units TYPE INTEGER USING round(n_units)::integer;
