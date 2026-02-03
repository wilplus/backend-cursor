-- Per-student: admin decides whether this student sees the exercise step (on student profile, not on Exercises tab).
-- When false, student skips the exercise step; when true (default), flow uses assigned_next_exercise_id or task_score.
ALTER TABLE v2_student_overrides
  ADD COLUMN IF NOT EXISTS show_exercise_step BOOLEAN DEFAULT true;

COMMENT ON COLUMN v2_student_overrides.show_exercise_step IS 'When false, this student never sees the exercise step. Set per student on their profile.';
