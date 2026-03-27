-- v2_sessions.task_score: warm-up / universal-answers composite score (0..1).
-- Present in v2_all_in_one / v2_flow; missing from v2_schema_unified homework path.
-- Without this column, admin GET student profile fails with 42703 when loading sessions.
--
-- Run in Supabase SQL Editor. Idempotent.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'v2_sessions'
      AND column_name = 'task_score'
  ) THEN
    ALTER TABLE public.v2_sessions ADD COLUMN task_score FLOAT;
  END IF;
END $$;

COMMENT ON COLUMN public.v2_sessions.task_score IS 'Optional composite score from warm-up / mood inputs (0..1). Used for exercise band selection in fuller flows.';
