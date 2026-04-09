-- Labeled task templates for tasks_pool (existing endpoints, no path changes)
-- Adds profile/level/step/active/replacement fields + active-slot uniqueness.

BEGIN;

ALTER TABLE public.tasks_pool
  ADD COLUMN IF NOT EXISTS target_profile TEXT;

ALTER TABLE public.tasks_pool
  ADD COLUMN IF NOT EXISTS level INTEGER;

ALTER TABLE public.tasks_pool
  ADD COLUMN IF NOT EXISTS step_in_level INTEGER;

ALTER TABLE public.tasks_pool
  ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

ALTER TABLE public.tasks_pool
  ADD COLUMN IF NOT EXISTS replaces_task_id UUID REFERENCES public.tasks_pool(id) ON DELETE SET NULL;

ALTER TABLE public.tasks_pool
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

UPDATE public.tasks_pool
SET
  target_profile = COALESCE(NULLIF(TRIM(target_profile), ''), 'The Overwhelmed'),
  level = COALESCE(level, 1),
  step_in_level = COALESCE(step_in_level, 1),
  is_active = COALESCE(is_active, TRUE)
WHERE
  target_profile IS NULL
  OR TRIM(target_profile) = ''
  OR level IS NULL
  OR step_in_level IS NULL
  OR is_active IS NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'tasks_pool_target_profile_check'
      AND conrelid = 'public.tasks_pool'::regclass
  ) THEN
    ALTER TABLE public.tasks_pool
      ADD CONSTRAINT tasks_pool_target_profile_check
      CHECK (
        target_profile IN ('The Overwhelmed', 'The Stressor', 'The Drifter', 'The Master')
      );
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'tasks_pool_level_check'
      AND conrelid = 'public.tasks_pool'::regclass
  ) THEN
    ALTER TABLE public.tasks_pool
      ADD CONSTRAINT tasks_pool_level_check
      CHECK (level >= 1);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'tasks_pool_step_in_level_check'
      AND conrelid = 'public.tasks_pool'::regclass
  ) THEN
    ALTER TABLE public.tasks_pool
      ADD CONSTRAINT tasks_pool_step_in_level_check
      CHECK (step_in_level BETWEEN 1 AND 10);
  END IF;
END $$;

DO $$
BEGIN
  BEGIN
    CREATE UNIQUE INDEX IF NOT EXISTS idx_tasks_pool_active_slot_unique
      ON public.tasks_pool(target_profile, level, step_in_level)
      WHERE is_active = TRUE;
  EXCEPTION
    WHEN unique_violation THEN
      -- Existing duplicate active slots must be resolved manually before this index can be created.
      -- We leave schema migration otherwise successful.
      NULL;
  END;
END $$;

CREATE INDEX IF NOT EXISTS idx_tasks_pool_profile_level_step
  ON public.tasks_pool(target_profile, level, step_in_level);

CREATE INDEX IF NOT EXISTS idx_tasks_pool_is_active
  ON public.tasks_pool(is_active);

GRANT ALL ON TABLE public.tasks_pool TO service_role;

COMMIT;
