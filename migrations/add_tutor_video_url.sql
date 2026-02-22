-- Tutor video URL: admin can attach a video link to an assignment; it is shown to the student on the homework page.
-- Run in Supabase SQL Editor. Idempotent (PostgreSQL: IF NOT EXISTS pattern).
-- Rollback: to revert, run ALTER TABLE v2_sessions DROP COLUMN IF EXISTS tutor_video_url;
--           and ALTER TABLE v2_student_overrides DROP COLUMN IF EXISTS pending_tutor_video_url;

-- Session: store the video URL for this homework run (set when student starts a session from pending).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'tutor_video_url') THEN
    ALTER TABLE v2_sessions ADD COLUMN tutor_video_url TEXT;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.tutor_video_url IS 'Optional video URL from the coach for this homework session. Set from pending_tutor_video_url when the student starts the session.';

-- Overrides: store "video URL for the next session" until the student starts (then copy to session and clear).
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'pending_tutor_video_url') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN pending_tutor_video_url TEXT;
  END IF;
END $$;

COMMENT ON COLUMN v2_student_overrides.pending_tutor_video_url IS 'When admin sends assignment with video_url, store it here. On POST session/start, copy to v2_sessions.tutor_video_url and clear. Optional: use a PL/pgSQL function + RPC for atomic get-and-clear under concurrency.';
