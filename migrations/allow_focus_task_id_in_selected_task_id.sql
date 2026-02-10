-- Allow selected_task_id and recordings.task_id to store either v2_tasks id or v2_focus_tasks id.
-- Homework flow now prefers per-student focus tasks from v2_focus_tasks (admin panel); resolution
-- is done in code via v2_get_task_or_focus_task. Run this so session/recording rows can reference
-- v2_focus_tasks(id) when the chosen task came from the student's focus list.

-- v2_sessions.selected_task_id: drop FK to v2_tasks so we can store v2_focus_tasks id
DO $$ BEGIN
  ALTER TABLE v2_sessions DROP CONSTRAINT IF EXISTS v2_sessions_selected_task_id_fkey;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

-- recordings.task_id: drop FK to v2_tasks so we can store v2_focus_tasks id
DO $$ BEGIN
  ALTER TABLE recordings DROP CONSTRAINT IF EXISTS recordings_task_id_fkey;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;

-- If your schema uses different constraint names, run: SELECT conname FROM pg_constraint WHERE conrelid = 'v2_sessions'::regclass AND contype = 'f';
-- and similarly for recordings, then DROP CONSTRAINT <name>;
