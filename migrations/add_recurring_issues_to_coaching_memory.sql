-- ============================================================================
-- Step 3.5: recurring_issues on v2_student_coaching_memory.
-- Derived from last 5 sessions' recording_1_performance_profile (pace_level, filler_level).
-- Run after add_v2_student_coaching_memory and add_recording_1_performance_profile.
--
-- Deployment: Run this in Supabase SQL Editor before deploying backend that writes
-- recurring_issues. Idempotent; existing rows get recurring_issues = [] until next upsert.
-- ============================================================================

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_student_coaching_memory'
    AND column_name = 'recurring_issues'
  ) THEN
    ALTER TABLE v2_student_coaching_memory ADD COLUMN recurring_issues JSONB DEFAULT '[]';
  END IF;
END $$;

COMMENT ON COLUMN v2_student_coaching_memory.recurring_issues IS 'Derived from last 5 recording_1_performance_profile: e.g. too_fast if pace_level==too_fast in >=3 of 5, high_fillers if filler_level==high in >=3. Used for need-based task selection.';
