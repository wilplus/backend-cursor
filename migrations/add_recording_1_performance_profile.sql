-- ============================================================================
-- recording_1_performance_profile: session-level behavioral labels from recording 1.
-- Step 3 of coaching redesign. Enables recurring-issue detection and need-based selection.
-- Run after v2_sessions exists.
--
-- Deployment order: (1) Run this migration in Supabase SQL Editor first,
--                   (2) then deploy backend. If you deploy code first, recording_1
--                   job will fail when writing the new column.
-- Safe: idempotent; existing rows keep recording_1_performance_profile = NULL.
-- ============================================================================

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions'
    AND column_name = 'recording_1_performance_profile'
  ) THEN
    ALTER TABLE v2_sessions ADD COLUMN recording_1_performance_profile JSONB DEFAULT NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.recording_1_performance_profile IS 'Labels from recording 1: pace_level (too_slow|optimal|too_fast), filler_level (low|medium|high). Optional: version, energy_level. Set by recording_1_job. Used for recurring-issue detection and future multi-factor task selection.';
