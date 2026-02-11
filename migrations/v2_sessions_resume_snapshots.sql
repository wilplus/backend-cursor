-- Persistence for resume/reproducibility: warmup ID + text snapshot, final_task text snapshot.
-- Run after v2_sessions exists. Canonical schema: .taskmaster/docs/schema.sql.

ALTER TABLE v2_sessions
  ADD COLUMN IF NOT EXISTS warm_up_task_id UUID REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS warm_up_task_text TEXT,
  ADD COLUMN IF NOT EXISTS final_task_text TEXT;

COMMENT ON COLUMN v2_sessions.warm_up_task_id IS 'Snapshot: which warm-up task was used for this attempt (resume/reproducibility).';
COMMENT ON COLUMN v2_sessions.warm_up_task_text IS 'Snapshot: warm-up task text at time of session (survives task edits).';
COMMENT ON COLUMN v2_sessions.final_task_text IS 'Snapshot: AI-generated final task instruction (resume/reproducibility).';
