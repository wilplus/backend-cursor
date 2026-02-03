-- Link v2 session to v1 recording_session so v2 can use v1 flow after universal-answers.
ALTER TABLE v2_sessions
  ADD COLUMN IF NOT EXISTS v1_session_id UUID REFERENCES recording_sessions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_v2_sessions_v1_session_id ON v2_sessions(v1_session_id);
