-- =============================================================================
-- Homework tasks cleanup: canonical "tasks" naming + remove focus-task tables
-- =============================================================================
-- Run in Supabase SQL Editor on a backup/snapshot-backed database.
--
-- ORDER OF OPERATIONS (important):
--   1) Deploy NOTHING until this script succeeds (or run in staging first).
--   2) This script ends with NOTIFY pgrst, 'reload schema' (Supabase PostgREST).
--      You can still use Dashboard → Settings → API → reload if needed.
--   3) Run rename_homework_session_status_warm_up_to_task.sql so active rows use status = 'task'.
--
-- What this does:
--   • DROP v2_focus_tasks, v2_focus_task_pool (obsolete product feature).
--   • Archive the OLD global prompt pool table v2_tasks (title/prompt_text)
--     → v2_deprecated_prompt_tasks_archive (safe to DROP later after review).
--   • RENAME v2_warm_up_task_pool → tasks_pool
--   • RENAME v2_warm_up_tasks → tasks  (per-student homework task rows)
--   • v2_sessions: DROP selected_task_id; RENAME warm_up_task_* → session_task_*
--   • recordings: DROP task_id if it pointed at the old global v2_tasks pool
--   • v2_student_overrides: RENAME assigned_warm_up_task_id → assigned_task_id
--   • v2_student_coaching_memory: DROP recent_focus_task_ids if present
--   • GRANT service_role on new public names
--   • NOTIFY pgrst, 'reload schema' after COMMIT-bound work (see end of file)
--
-- Rollback: restore from backup only (renames are not trivially reversible).
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) Remove focus-task feature tables
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS public.v2_focus_tasks CASCADE;
DROP TABLE IF EXISTS public.v2_focus_task_pool CASCADE;

-- ---------------------------------------------------------------------------
-- 2) Drop foreign keys that point at the CURRENT public.v2_tasks (old global
--    pool). Per-student warm-up rows live in v2_warm_up_tasks until step 4.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  r RECORD;
BEGIN
  FOR r IN
    SELECT c.conname, c.conrelid::regclass AS tbl
    FROM pg_constraint c
    WHERE c.confrelid = 'public.v2_tasks'::regclass
      AND c.contype = 'f'
  LOOP
    EXECUTE format('ALTER TABLE %s DROP CONSTRAINT IF EXISTS %I', r.tbl, r.conname);
  END LOOP;
END $$;

ALTER TABLE public.v2_sessions
  DROP COLUMN IF EXISTS selected_task_id;

ALTER TABLE public.recordings
  DROP CONSTRAINT IF EXISTS recordings_task_id_fkey;

ALTER TABLE public.recordings
  DROP COLUMN IF EXISTS task_id;

-- ---------------------------------------------------------------------------
-- 3) Archive old global pool, then promote warm-up tables to canonical names
-- ---------------------------------------------------------------------------
ALTER TABLE IF EXISTS public.v2_tasks
  RENAME TO v2_deprecated_prompt_tasks_archive;

DO $$
BEGIN
  IF to_regclass('public.tasks_pool') IS NULL AND to_regclass('public.v2_warm_up_task_pool') IS NOT NULL THEN
    ALTER TABLE public.v2_warm_up_task_pool RENAME TO tasks_pool;
  END IF;
  IF to_regclass('public.tasks') IS NULL AND to_regclass('public.v2_warm_up_tasks') IS NOT NULL THEN
    ALTER TABLE public.v2_warm_up_tasks RENAME TO tasks;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 4) v2_sessions: rename warm-up snapshot columns → session_task_*
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions'
      AND column_name = 'warm_up_task_id'
  ) THEN
    ALTER TABLE public.v2_sessions RENAME COLUMN warm_up_task_id TO session_task_id;
  END IF;

  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions'
      AND column_name = 'warm_up_task_text'
  ) THEN
    ALTER TABLE public.v2_sessions RENAME COLUMN warm_up_task_text TO session_task_text;
  END IF;
END $$;

-- FK session_task_id → tasks(id)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions'
      AND column_name = 'session_task_id'
  ) THEN
    ALTER TABLE public.v2_sessions
      DROP CONSTRAINT IF EXISTS v2_sessions_warm_up_task_id_fkey;
    ALTER TABLE public.v2_sessions
      DROP CONSTRAINT IF EXISTS v2_sessions_session_task_id_fkey;
    -- Legacy rows can still point to archived/deleted task ids.
    -- Null them before re-attaching FK to public.tasks.
    UPDATE public.v2_sessions s
    SET session_task_id = NULL
    WHERE s.session_task_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM public.tasks t WHERE t.id = s.session_task_id
      );
    ALTER TABLE public.v2_sessions
      ADD CONSTRAINT v2_sessions_session_task_id_fkey
      FOREIGN KEY (session_task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;
  END IF;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------
-- 5) Overrides: assigned_warm_up_task_id → assigned_task_id
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_student_overrides'
      AND column_name = 'assigned_warm_up_task_id'
  ) THEN
    ALTER TABLE public.v2_student_overrides
      DROP CONSTRAINT IF EXISTS v2_student_overrides_assigned_warm_up_task_id_fkey;
    ALTER TABLE public.v2_student_overrides
      RENAME COLUMN assigned_warm_up_task_id TO assigned_task_id;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_student_overrides'
      AND column_name = 'assigned_task_id'
  ) THEN
    ALTER TABLE public.v2_student_overrides
      DROP CONSTRAINT IF EXISTS v2_student_overrides_assigned_task_id_fkey;
    -- Same cleanup for stale override ids from pre-rename datasets.
    UPDATE public.v2_student_overrides o
    SET assigned_task_id = NULL
    WHERE o.assigned_task_id IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM public.tasks t WHERE t.id = o.assigned_task_id
      );
    ALTER TABLE public.v2_student_overrides
      ADD CONSTRAINT v2_student_overrides_assigned_task_id_fkey
      FOREIGN KEY (assigned_task_id) REFERENCES public.tasks(id) ON DELETE SET NULL;
  END IF;
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

-- ---------------------------------------------------------------------------
-- 6) Coaching memory: column unused by current Python upsert
-- ---------------------------------------------------------------------------
ALTER TABLE public.v2_student_coaching_memory
  DROP COLUMN IF EXISTS recent_focus_task_ids;

-- ---------------------------------------------------------------------------
-- 7) service_role (PostgREST with service key)
-- ---------------------------------------------------------------------------
GRANT ALL ON TABLE public.tasks TO service_role;
GRANT ALL ON TABLE public.tasks_pool TO service_role;
GRANT ALL ON TABLE public.v2_deprecated_prompt_tasks_archive TO service_role;

-- ---------------------------------------------------------------------------
-- 8) PostgREST schema cache (Supabase)
-- ---------------------------------------------------------------------------
NOTIFY pgrst, 'reload schema';

COMMIT;
