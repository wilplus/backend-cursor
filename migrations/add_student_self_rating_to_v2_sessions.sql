-- Denormalized copy of homework self-rating (1–5) for admin/history when session_sniper_metrics is overwritten by the recording job upsert.
-- Run in Supabase SQL Editor; reload PostgREST schema if NOTIFY does not run.

ALTER TABLE public.v2_sessions
  ADD COLUMN IF NOT EXISTS student_self_rating SMALLINT;

COMMENT ON COLUMN public.v2_sessions.student_self_rating IS
  'Student 1–5 self-rating after recording-1; set on POST .../self-rating with a numeric rating. Mirrors session_sniper_metrics.student_rating_1_10.';

NOTIFY pgrst, 'reload schema';
