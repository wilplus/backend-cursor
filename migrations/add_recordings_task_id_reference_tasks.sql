-- Link recordings to the per-student homework task row (public.tasks).
-- Safe after rename_warmup_to_tasks_and_drop_focus.sql (which dropped legacy recordings.task_id).
-- Run in Supabase SQL Editor, then ensure schema cache reloads (NOTIFY at end).

DO $$
BEGIN
  IF to_regclass('public.recordings') IS NULL THEN
    RAISE NOTICE 'add_recordings_task_id: public.recordings missing; skip';
    RETURN;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'task_id'
  ) THEN
    RAISE NOTICE 'add_recordings_task_id: column already exists; skip';
    RETURN;
  END IF;

  IF to_regclass('public.tasks') IS NOT NULL THEN
    ALTER TABLE public.recordings
      ADD COLUMN task_id UUID REFERENCES public.tasks(id) ON DELETE SET NULL;
  ELSE
    -- Pre-migration DBs: add nullable UUID without FK; add FK after tasks exists.
    ALTER TABLE public.recordings ADD COLUMN task_id UUID;
  END IF;
END $$;

COMMENT ON COLUMN public.recordings.task_id IS
  'Homework task row (public.tasks) for this recording; mirrors v2_sessions session_task_id / warm_up_task_id snapshot.';

NOTIFY pgrst, 'reload schema';
