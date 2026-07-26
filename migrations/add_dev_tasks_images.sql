-- dev_tasks.images — carry the source bug's image(s) onto the task it becomes,
-- so a screenshot attached to a bug shows on its task card too. Populated at
-- generation time from dev_bugs.images. Idempotent; safe to re-run.

ALTER TABLE public.dev_tasks
    ADD COLUMN IF NOT EXISTS images JSONB NOT NULL DEFAULT '[]'::jsonb;
