-- Step 0 always shows an exercise: when assigned_next_exercise_id is set we show it and remember it;
-- when admin clears assignment we keep showing last_assigned_exercise_id until a new one is assigned;
-- if never assigned we fall back to 0-intro (by title). Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'last_assigned_exercise_id') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN last_assigned_exercise_id UUID REFERENCES v2_exercises(id) ON DELETE SET NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_student_overrides.last_assigned_exercise_id IS 'Last exercise assigned for step 0; shown when assigned_next_exercise_id is null until admin assigns a new one.';
