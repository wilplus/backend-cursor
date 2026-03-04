-- Coach grade (1-10): admin can grade a completed session/recording.
-- Run after v2_sessions exists.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'coach_grade'
  ) THEN
    ALTER TABLE v2_sessions ADD COLUMN coach_grade SMALLINT DEFAULT NULL
      CHECK (coach_grade >= 1 AND coach_grade <= 10);
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.coach_grade IS 'Admin/coach grade for this session (1-10). Set in admin panel when reviewing the report.';
