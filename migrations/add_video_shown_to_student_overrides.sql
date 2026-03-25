-- Idempotent: coach/student UI flag for assignment video vs waiting screen.
-- Run in Supabase SQL Editor after v2_student_overrides exists.
--
-- Semantics (integer 0 or 1):
--   video_shown = 0 → student should see waiting / reviewing; hide coach assignment video in status payload.
--   video_shown = 1 → student may see coach video when tutor_video_url (or legacy assigned_exercises) is present.
--
-- Backend sets:
--   0 when a homework session is marked completed (student finished).
--   1 when admin POST send-assignment succeeds (homework email to student).

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'v2_student_overrides'
      AND column_name = 'video_shown'
  ) THEN
    ALTER TABLE v2_student_overrides
      ADD COLUMN video_shown SMALLINT NOT NULL DEFAULT 1
      CHECK (video_shown IN (0, 1));
  END IF;
END $$;

COMMENT ON COLUMN v2_student_overrides.video_shown IS
  '0 = hide coach assignment video (waiting UI); 1 = allow showing coach video. Set 0 on homework completion; set 1 on send-assignment.';
