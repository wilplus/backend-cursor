-- 0254 · charisma_snippets — drop the six dead metric columns. PM-9.
--
-- WHAT THEY WERE. wpm, fillers, pause_ms, dynamic_db, pitch_center, energy:
-- denormalized copies of figures that also live in the `metrics` JSONB blob.
-- They look canonical. They are NULL on every row the live pipeline makes.
--
-- WHY THEY ARE DEAD. The only writer was db.update_snippet_metrics, reached
-- solely from snippet_extraction.recompute_snippet_metrics_for_window, which
-- had zero callers repo-wide — an orphaned boundary-adjust path. Both are
-- deleted in the same commit as this file. process_lab_recording inserts the
-- blob and nothing else, and always has.
--
-- WHY THIS IS NOT DATA LOSS. update_snippet_metrics wrote the columns AND
-- `metrics` in one payload, so any historical row that ever got column values
-- carries the same figures in its blob. Nothing is only in a column. Verify on
-- your own data before running — the count query is at the bottom.
--
-- WHY DROP RATHER THAN LEAVE. This is exactly the shape that hid the PM-9 bug
-- for months: a column that looks like the source of truth, reads as NULL, and
-- makes every consumer of it silently blank instead of loudly broken. Leaving
-- them is an invitation to write `snippet["wpm"]` again.
--
-- ORDERING. The code stopped naming these columns first (services/db.py's
-- get_recent_published_snippet_metrics used to SELECT them explicitly; it now
-- selects only metrics/transcript/duration_ms/created_at). Deploy that commit
-- BEFORE running this, or that query errors on a missing column.
--
-- SAFE TO RUN TWICE — IF EXISTS on every drop.
-- SAFE TO RUN BEFORE THE DEPLOY REACHES EVERY DYNO — services/snippet_values
-- resolves column → blob → derivation, and a column that no longer exists is
-- simply a dict lookup that misses. The blob answers either way.

BEGIN;

ALTER TABLE public.charisma_snippets DROP COLUMN IF EXISTS wpm;
ALTER TABLE public.charisma_snippets DROP COLUMN IF EXISTS fillers;
ALTER TABLE public.charisma_snippets DROP COLUMN IF EXISTS pause_ms;
ALTER TABLE public.charisma_snippets DROP COLUMN IF EXISTS dynamic_db;
ALTER TABLE public.charisma_snippets DROP COLUMN IF EXISTS pitch_center;
ALTER TABLE public.charisma_snippets DROP COLUMN IF EXISTS energy;

COMMIT;

-- ─────────────────────────────────────────────────────────────────────────
-- RUN THIS FIRST, and only proceed if every count is 0. A non-zero count
-- means some path DID write a column, the diagnosis above is incomplete, and
-- you should stop and re-read it rather than drop.
--
--   SELECT count(*) FILTER (WHERE wpm          IS NOT NULL) AS wpm,
--          count(*) FILTER (WHERE fillers      IS NOT NULL) AS fillers,
--          count(*) FILTER (WHERE pause_ms     IS NOT NULL) AS pause_ms,
--          count(*) FILTER (WHERE dynamic_db   IS NOT NULL) AS dynamic_db,
--          count(*) FILTER (WHERE pitch_center IS NOT NULL) AS pitch_center,
--          count(*) FILTER (WHERE energy       IS NOT NULL) AS energy
--   FROM public.charisma_snippets;
--
-- If a count is non-zero but the same figure is present in `metrics`, the drop
-- is still safe — that is the expected state for rows the retired
-- boundary-adjust path touched, since it wrote both in one payload.
-- ─────────────────────────────────────────────────────────────────────────
