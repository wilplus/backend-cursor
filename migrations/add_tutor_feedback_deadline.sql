-- Tutor feedback deadline: completion timestamp + configurable window (e.g. 24h) for "tutor has until X to send feedback" notice.
-- Run in Supabase SQL Editor. Idempotent.

-- Add completed_at to v2_sessions so we can compute deadline = completed_at + TUTOR_FEEDBACK_WINDOW_HOURS
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'completed_at') THEN
    ALTER TABLE v2_sessions ADD COLUMN completed_at TIMESTAMPTZ DEFAULT NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.completed_at IS 'When the lesson was completed (report generated). Used with TUTOR_FEEDBACK_WINDOW_HOURS to compute tutor_feedback_deadline for the frontend countdown.';

-- Backfill: set completed_at from the report's created_at for existing completed sessions
UPDATE v2_sessions s
SET completed_at = r.created_at
FROM v2_reports r
WHERE r.id = s.report_id
  AND s.status = 'completed'
  AND s.completed_at IS NULL;
