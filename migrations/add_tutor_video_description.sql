-- Optional description text for the tutor video (admin writes a short message to the student alongside the video link).
-- Run after add_tutor_video_url.sql. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'tutor_video_description') THEN
    ALTER TABLE v2_sessions ADD COLUMN tutor_video_description TEXT;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.tutor_video_description IS 'Optional message from the coach about the video (e.g. what to focus on). Shown with tutor_video_url in email and on homework page.';

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'pending_tutor_video_description') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN pending_tutor_video_description TEXT;
  END IF;
END $$;

COMMENT ON COLUMN v2_student_overrides.pending_tutor_video_description IS 'Description for the pending video; copied to v2_sessions.tutor_video_description on session/start and cleared.';
