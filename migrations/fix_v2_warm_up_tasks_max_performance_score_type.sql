-- ============================================================================
-- Fix: "invalid input syntax for type integer: \"1.0\"" on confirm warm-up
-- selection (PUT task-warm-up sync).
--
-- Cause: v2_warm_up_tasks.max_performance_score was created or altered as
-- INTEGER somewhere; the backend sends 1.0 (decimal). Postgres rejects it.
--
-- Run this in Supabase SQL Editor (same DB as Railway). Idempotent: only
-- alters when the column type is integer.
-- ============================================================================

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'v2_warm_up_tasks'
      AND column_name = 'max_performance_score'
      AND data_type = 'integer'
  ) THEN
    ALTER TABLE public.v2_warm_up_tasks
    ALTER COLUMN max_performance_score TYPE DECIMAL(3,2)
    USING (max_performance_score::numeric);
  END IF;
END $$;
