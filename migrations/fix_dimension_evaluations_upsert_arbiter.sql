-- 0251 · Make the snippet-grain unique index usable as an ON CONFLICT arbiter.
--
-- THE BUG. 0249 created the snippet uniqueness as a PARTIAL index:
--
--     CREATE UNIQUE INDEX uq_dimension_evaluations_snip_dim_ver
--         ON dimension_evaluations (snippet_id, dimension_id, benchmark_version)
--         WHERE snippet_id IS NOT NULL;      -- <-- the predicate
--
-- and services/db.py::record_dimension_evaluations writes with
--
--     .upsert(payload, on_conflict="snippet_id,dimension_id,benchmark_version")
--
-- PostgreSQL will only infer a PARTIAL unique index as an ON CONFLICT arbiter
-- when the statement repeats the index predicate (`ON CONFLICT (cols) WHERE
-- ...`). PostgREST's `on_conflict` parameter emits the column list and no
-- predicate, so inference fails with
--
--     42P10  there is no unique or exclusion constraint matching the
--            ON CONFLICT specification
--
-- record_dimension_evaluations catches every exception, logs at WARNING and
-- returns 0 — by design, so telemetry can never break the scoring path it
-- observes. The cost of that design is that this failed on EVERY write and
-- looked like "no data yet". `dimension_evaluations` stayed empty while the
-- pipeline reported success.
--
-- THE FIX. Drop the predicate. The index is unique on
-- (snippet_id, dimension_id, benchmark_version) either way for every row the
-- writer produces, because that writer always sets snippet_id.
--
-- SAFE FOR THE RECORDING-ANCHORED ROWS TOO. PostgreSQL treats NULLs as
-- DISTINCT in a unique index by default, so rows with snippet_id IS NULL —
-- the recording-grain shape 0249 kept the door open for — still never
-- collide with each other. Removing the predicate changes the behaviour for
-- no row that can exist; it only makes the index visible to the arbiter.
--
-- uq_dimension_evaluations_rec_dim_ver KEEPS its predicate deliberately:
-- nothing upserts on recording grain, so it needs no arbiter, and the
-- predicate is the more precise statement of intent there.
--
-- Idempotent. Safe to re-run.

BEGIN;

DROP INDEX IF EXISTS public.uq_dimension_evaluations_snip_dim_ver;

CREATE UNIQUE INDEX IF NOT EXISTS uq_dimension_evaluations_snip_dim_ver
    ON public.dimension_evaluations (snippet_id, dimension_id, benchmark_version);

COMMENT ON INDEX public.uq_dimension_evaluations_snip_dim_ver IS
    'Snippet-grain uniqueness AND the ON CONFLICT arbiter for '
    'record_dimension_evaluations. NOT partial: PostgreSQL cannot infer a '
    'partial unique index as an arbiter unless the statement repeats the '
    'predicate, and PostgREST''s on_conflict emits columns only. NULL '
    'snippet_id rows stay non-colliding because NULLs are DISTINCT here.';

COMMIT;

-- ROLLBACK (restores the broken arbiter — only if the writer stops upserting):
--   DROP INDEX IF EXISTS public.uq_dimension_evaluations_snip_dim_ver;
--   CREATE UNIQUE INDEX uq_dimension_evaluations_snip_dim_ver
--       ON public.dimension_evaluations
--          (snippet_id, dimension_id, benchmark_version)
--       WHERE snippet_id IS NOT NULL;
