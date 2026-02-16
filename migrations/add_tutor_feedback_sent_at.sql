-- When the admin sends new homework (POST send-assignment), set tutor_feedback_sent_at on the
-- user's last completed session so GET session/status omits tutor_feedback_deadline and the
-- frontend hides the countdown immediately.
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'tutor_feedback_sent_at') THEN
    ALTER TABLE v2_sessions ADD COLUMN tutor_feedback_sent_at TIMESTAMPTZ DEFAULT NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.tutor_feedback_sent_at IS 'Set when admin sends new homework (POST send-assignment). When set, tutor_feedback_deadline is omitted from session/status so frontend hides the countdown.';
