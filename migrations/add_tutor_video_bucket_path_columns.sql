-- Tutor video from Supabase Storage (bucket + path). Run once in Supabase SQL Editor.
-- Fixes: 42703 column v2_student_overrides.pending_tutor_video_bucket does not exist
-- After running: Dashboard → Settings → API → Reload schema (if PostgREST cache is stale).

ALTER TABLE public.v2_student_overrides
  ADD COLUMN IF NOT EXISTS pending_tutor_video_bucket TEXT,
  ADD COLUMN IF NOT EXISTS pending_tutor_video_storage_path TEXT;

ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS tutor_video_bucket TEXT,
  ADD COLUMN IF NOT EXISTS tutor_video_storage_path TEXT;

COMMENT ON COLUMN public.v2_student_overrides.pending_tutor_video_bucket IS 'Supabase Storage bucket for pending coach video (optional if pending_tutor_video_url is storage:// or https).';
COMMENT ON COLUMN public.v2_student_overrides.pending_tutor_video_storage_path IS 'Object path within bucket for pending coach video.';
COMMENT ON COLUMN public.v2_sessions.tutor_video_bucket IS 'Copied from pending on session/start; used with tutor_video_storage_path to sign playback URLs.';
COMMENT ON COLUMN public.v2_sessions.tutor_video_storage_path IS 'Copied from pending on session/start; used with tutor_video_bucket to sign playback URLs.';
