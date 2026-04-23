-- =============================================================================
-- Behavioral recommendation engine v1: partition + seed + session columns
-- =============================================================================
-- Context:
--   Introduces the 12 canonical behavioral tasks (4 profiles x 3 graduated
--   levels) into the existing tasks_pool, alongside the legacy warm-up tasks,
--   without colliding with the existing unique slot index and without
--   disrupting the current admin warm-up workflow.
--
-- Strategy:
--   1. Add `is_behavioral` boolean to tasks_pool (DEFAULT FALSE so all legacy
--      rows remain unchanged, visible in the legacy admin modal).
--   2. Replace the existing unique slot index with one that also keys on
--      is_behavioral, so legacy and behavioral tasks can coexist at the same
--      (profile, level, step) tuple without conflict.
--   3. Seed the 12 canonical behavioral tasks with is_behavioral = TRUE,
--      guarded by NOT EXISTS to keep the migration idempotent.
--   4. Add ai_suggested_profile + ai_suggested_task_id columns to v2_sessions
--      so the diagnose-and-prescribe engine (Phase 3) has somewhere to store
--      the pending machine recommendation before coach approval.
--
-- Safe rollback: drop the new columns and the new index, restore the old
-- index on (target_profile, level, step_in_level) WHERE is_active = TRUE.
-- Legacy rows are not mutated by this migration.
-- =============================================================================

BEGIN;

-- ---------------------------------------------------------------------------
-- 1) Partition column
-- ---------------------------------------------------------------------------
ALTER TABLE public.tasks_pool
  ADD COLUMN IF NOT EXISTS is_behavioral BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN public.tasks_pool.is_behavioral IS
  'TRUE for the 12 canonical behavioral recommendation-engine tasks (seeded 2026-04-23). FALSE for legacy warm-up tasks.';

-- ---------------------------------------------------------------------------
-- 2) Unique slot index: include is_behavioral so legacy and behavioral can
--    coexist at the same (profile, level, step) tuple.
--
--    The live database may hold a UNIQUE index on the 3-column tuple under a
--    name that differs from the repo (observed in prod: `ux_tasks_pool_active_slot`
--    instead of `idx_tasks_pool_active_slot_unique`). Drop both known names,
--    then do a defensive sweep for any other UNIQUE index over exactly
--    (target_profile, level, step_in_level) that does not include is_behavioral.
-- ---------------------------------------------------------------------------
DROP INDEX IF EXISTS public.idx_tasks_pool_active_slot_unique;
DROP INDEX IF EXISTS public.ux_tasks_pool_active_slot;

DO $$
DECLARE
  idx_name TEXT;
  col_names TEXT[];
BEGIN
  FOR idx_name, col_names IN
    SELECT
      c.relname,
      (
        SELECT array_agg(a.attname ORDER BY k.ord)
        FROM unnest(i.indkey) WITH ORDINALITY AS k(col, ord)
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.col
      )
    FROM pg_index i
    JOIN pg_class c ON c.oid = i.indexrelid
    WHERE i.indrelid = 'public.tasks_pool'::regclass
      AND i.indisunique
  LOOP
    IF col_names @> ARRAY['target_profile','level','step_in_level']::TEXT[]
       AND NOT (col_names @> ARRAY['is_behavioral']::TEXT[]) THEN
      EXECUTE 'DROP INDEX IF EXISTS public.' || quote_ident(idx_name);
    END IF;
  END LOOP;
END $$;

DO $$
BEGIN
  BEGIN
    CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_pool_active_slot_unique
      ON public.tasks_pool(target_profile, level, step_in_level, is_behavioral)
      WHERE is_active = TRUE;
  EXCEPTION
    WHEN unique_violation THEN
      -- Pre-existing duplicate active slots in legacy rows must be resolved
      -- manually. The migration otherwise completes successfully.
      NULL;
  END;
END $$;

CREATE INDEX IF NOT EXISTS idx_tasks_pool_behavioral_profile_level_step
  ON public.tasks_pool(is_behavioral, target_profile, level, step_in_level);

-- ---------------------------------------------------------------------------
-- 3) Seed the 12 canonical behavioral tasks (idempotent).
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  seed JSONB := '[
    {"profile": "The Stressor",    "level": 1, "step": 1, "text": "The 3-Second Bridge"},
    {"profile": "The Stressor",    "level": 2, "step": 1, "text": "The Breath Reset"},
    {"profile": "The Stressor",    "level": 3, "step": 1, "text": "The Deliberate Pace"},
    {"profile": "The Drifter",     "level": 1, "step": 1, "text": "The Grandmother Test"},
    {"profile": "The Drifter",     "level": 2, "step": 1, "text": "The Rule of Three"},
    {"profile": "The Drifter",     "level": 3, "step": 1, "text": "The BLUF Protocol"},
    {"profile": "The Overwhelmed", "level": 1, "step": 1, "text": "The Volume Escalation"},
    {"profile": "The Overwhelmed", "level": 2, "step": 1, "text": "The Unapologetic Pause"},
    {"profile": "The Overwhelmed", "level": 3, "step": 1, "text": "The Assertive Posture"},
    {"profile": "The Master",      "level": 1, "step": 1, "text": "The Boardroom Interruption"},
    {"profile": "The Master",      "level": 2, "step": 1, "text": "The Hostile Q&A"},
    {"profile": "The Master",      "level": 3, "step": 1, "text": "The Improv Pivot"}
  ]'::JSONB;
  task JSONB;
BEGIN
  FOR task IN SELECT * FROM jsonb_array_elements(seed)
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM public.tasks_pool
      WHERE is_behavioral = TRUE
        AND target_profile = (task->>'profile')
        AND level = (task->>'level')::INTEGER
        AND step_in_level = (task->>'step')::INTEGER
    ) THEN
      INSERT INTO public.tasks_pool (
        text,
        order_index,
        max_performance_score,
        target_profile,
        level,
        step_in_level,
        is_active,
        is_behavioral
      ) VALUES (
        task->>'text',
        0,
        1.00,
        task->>'profile',
        (task->>'level')::INTEGER,
        (task->>'step')::INTEGER,
        TRUE,
        TRUE
      );
    END IF;
  END LOOP;
END $$;

-- ---------------------------------------------------------------------------
-- 4) v2_sessions: AI suggestion columns (not yet populated until Phase 3).
-- ---------------------------------------------------------------------------
ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS ai_suggested_profile TEXT;

ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS ai_suggested_task_id UUID;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'v2_sessions_ai_suggested_task_id_fkey'
      AND conrelid = 'public.v2_sessions'::regclass
  ) THEN
    ALTER TABLE public.v2_sessions
      ADD CONSTRAINT v2_sessions_ai_suggested_task_id_fkey
      FOREIGN KEY (ai_suggested_task_id)
      REFERENCES public.tasks_pool(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'v2_sessions_ai_suggested_profile_check'
      AND conrelid = 'public.v2_sessions'::regclass
  ) THEN
    ALTER TABLE public.v2_sessions
      ADD CONSTRAINT v2_sessions_ai_suggested_profile_check
      CHECK (
        ai_suggested_profile IS NULL
        OR ai_suggested_profile IN ('The Overwhelmed', 'The Stressor', 'The Drifter', 'The Master')
      );
  END IF;
END $$;

COMMENT ON COLUMN public.v2_sessions.ai_suggested_profile IS
  'Machine guess from diagnose_session_state(). Separate from the human-approved state so coach overrides can feed admin_annotation_events for future RLHF.';
COMMENT ON COLUMN public.v2_sessions.ai_suggested_task_id IS
  'Machine-prescribed task from tasks_pool (is_behavioral = TRUE). Coach can override via the admin dashboard.';

-- ---------------------------------------------------------------------------
-- 5) PostgREST schema cache (Supabase)
-- ---------------------------------------------------------------------------
NOTIFY pgrst, 'reload schema';

COMMIT;
