-- Optional bucket + object path for tutor video when URL alone is not playable (e.g. only internal refs).
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'pending_tutor_video_bucket'
  ) THEN
    ALTER TABLE public.v2_student_overrides ADD COLUMN pending_tutor_video_bucket TEXT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'pending_tutor_video_storage_path'
  ) THEN
    ALTER TABLE public.v2_student_overrides ADD COLUMN pending_tutor_video_storage_path TEXT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'tutor_video_bucket'
  ) THEN
    ALTER TABLE public.v2_sessions ADD COLUMN tutor_video_bucket TEXT;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'tutor_video_storage_path'
  ) THEN
    ALTER TABLE public.v2_sessions ADD COLUMN tutor_video_storage_path TEXT;
  END IF;
END $$;

COMMENT ON COLUMN public.v2_student_overrides.pending_tutor_video_bucket IS 'Supabase Storage bucket for pending coach video (optional if pending_tutor_video_url is storage:// or https).';
COMMENT ON COLUMN public.v2_student_overrides.pending_tutor_video_storage_path IS 'Object path within bucket for pending coach video.';
COMMENT ON COLUMN public.v2_sessions.tutor_video_bucket IS 'Copied from pending on session/start; used with tutor_video_storage_path to sign playback URLs.';
COMMENT ON COLUMN public.v2_sessions.tutor_video_storage_path IS 'Copied from pending on session/start; used with tutor_video_bucket to sign playback URLs.';
