-- Fix PGRST204: add missing warm_up columns to v2_sessions
-- Run in Supabase SQL Editor (or your Postgres client). Idempotent.

-- Add columns (no FK inline to avoid schema-cache issues; add FK after if needed)
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS warm_up_task_id UUID;
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS warm_up_task_text TEXT;

-- Optional: add FK so warm_up_task_id references v2_warm_up_tasks(id)
-- Run only if v2_warm_up_tasks exists and you want referential integrity
-- ALTER TABLE v2_sessions
--   ADD CONSTRAINT v2_sessions_warm_up_task_id_fkey
--   FOREIGN KEY (warm_up_task_id) REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL;
