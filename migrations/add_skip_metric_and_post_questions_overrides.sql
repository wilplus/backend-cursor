-- Flow-step overrides: allow admin to skip metric questions (step 2) and/or post questions (step 4).
-- Frontend sends skip_metric_questions, skip_post_questions in PUT overrides; backend must persist and return them.
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'skip_metric_questions') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN skip_metric_questions BOOLEAN DEFAULT false;
  END IF;
END $$;

COMMENT ON COLUMN v2_student_overrides.skip_metric_questions IS 'When true, student skips step 2 (metric questions) and goes from recording 1 to final task / recording 2.';

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'skip_post_questions') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN skip_post_questions BOOLEAN DEFAULT false;
  END IF;
END $$;

COMMENT ON COLUMN v2_student_overrides.skip_post_questions IS 'When true, student skips step 4 (post questions) and goes from recording 2 to completed + report.';
