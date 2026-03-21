-- Adds an optional short coach-written comment to a homework session report.
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'v2_sessions'
      AND column_name = 'report_comment'
  ) THEN
    ALTER TABLE v2_sessions ADD COLUMN report_comment TEXT DEFAULT NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.report_comment IS 'Optional coach-written note shown next to the grade in the full report view.';
