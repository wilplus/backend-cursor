-- dev_tasks re-evaluation (Level 1): when a new P1/P2 task arrives, a few RELATED
-- existing tasks can be bumped UP in priority. Each bump stamps a reason + a
-- timestamp so the move is transparent in the UI and easy to reason about /
-- undo. See services/dev_tasks.reevaluate + config.DEV_TASKS_REEVAL_ENABLED.
--
-- Idempotent; safe to re-run.

ALTER TABLE public.dev_tasks
    ADD COLUMN IF NOT EXISTS bump_reason TEXT,
    ADD COLUMN IF NOT EXISTS bumped_at   TIMESTAMPTZ;
