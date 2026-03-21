-- Track student completion email delivery per session (idempotent retries).
ALTER TABLE v2_sessions
  ADD COLUMN IF NOT EXISTS student_completion_email_sent_at TIMESTAMPTZ;

ALTER TABLE v2_sessions
  ADD COLUMN IF NOT EXISTS student_completion_email_last_error TEXT;

COMMENT ON COLUMN v2_sessions.student_completion_email_sent_at IS
  'When lesson-complete email to the student was successfully sent.';

COMMENT ON COLUMN v2_sessions.student_completion_email_last_error IS
  'Last error encountered while sending lesson-complete email to the student.';
