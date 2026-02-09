-- Fix PGRST204: add missing v2_sessions columns (warm_up, final_task, etc.)
-- Run in Supabase SQL Editor (or your Postgres client). Idempotent.

-- Warm-up and final task columns
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS warm_up_task_id UUID;
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS warm_up_task_text TEXT;
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS final_task_text TEXT;

-- If you still see PGRST204 for other columns, run the full §1 block in docs/MIGRATION-PLAN-MINIMAL-DIFF.md

-- Optional: add FK for warm_up_task_id (only if v2_warm_up_tasks exists)
-- ALTER TABLE v2_sessions
--   ADD CONSTRAINT v2_sessions_warm_up_task_id_fkey
--   FOREIGN KEY (warm_up_task_id) REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL;
