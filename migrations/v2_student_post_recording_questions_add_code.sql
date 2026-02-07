-- Add code to per-student post-recording questions (copied from pool) for emotion_achieved_check detection in homework.
-- Run v2_student_post_recording_questions.sql first to create the table. This migration is safe if table already has code.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'v2_student_post_recording_questions') THEN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_post_recording_questions' AND column_name = 'code') THEN
      ALTER TABLE v2_student_post_recording_questions ADD COLUMN code TEXT;
      COMMENT ON COLUMN v2_student_post_recording_questions.code IS 'Copied from pool (e.g. emotion_achieved_check). Used when submitting post-answers.';
    END IF;
  END IF;
END $$;
