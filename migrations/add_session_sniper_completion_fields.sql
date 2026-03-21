-- Persist richer sniper completion payloads and authoritative session step snapshots.
-- Run after add_user_sniper_profile.sql and after v2_sessions/recordings exist.

ALTER TABLE session_sniper_metrics
  ADD COLUMN IF NOT EXISTS recording_id UUID NULL REFERENCES recordings(id) ON DELETE SET NULL,
  ADD COLUMN IF NOT EXISTS duration_seconds FLOAT NULL,
  ADD COLUMN IF NOT EXISTS pitch_center_st FLOAT NULL,
  ADD COLUMN IF NOT EXISTS pitch_frame_count INT NULL,
  ADD COLUMN IF NOT EXISTS frontend_level INT NULL,
  ADD COLUMN IF NOT EXISTS frontend_step INT NULL,
  ADD COLUMN IF NOT EXISTS completed BOOLEAN NULL,
  ADD COLUMN IF NOT EXISTS valid_for_progression BOOLEAN NULL,
  ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_session_sniper_metrics_recording_id ON session_sniper_metrics(recording_id);

COMMENT ON COLUMN session_sniper_metrics.recording_id IS 'Optional recording linkage for the completion payload; session_id remains the authoritative key.';
COMMENT ON COLUMN session_sniper_metrics.duration_seconds IS 'Frontend-reported session duration in seconds.';
COMMENT ON COLUMN session_sniper_metrics.pitch_center_st IS 'Frontend-reported measured pitch center in semitones for this session.';
COMMENT ON COLUMN session_sniper_metrics.pitch_frame_count IS 'Number of pitch-valid frames used to compute pitch_center_st.';
COMMENT ON COLUMN session_sniper_metrics.frontend_level IS 'Frontend-reported level shown when the session completed; useful for debugging drift.';
COMMENT ON COLUMN session_sniper_metrics.frontend_step IS 'Frontend-reported step shown when the session completed; useful for debugging drift.';
COMMENT ON COLUMN session_sniper_metrics.completed IS 'True when the frontend marked this session summary as a completed practice.';
COMMENT ON COLUMN session_sniper_metrics.valid_for_progression IS 'True when the frontend says this completion should count toward progression.';

ALTER TABLE v2_sessions
  ADD COLUMN IF NOT EXISTS realtime_level_at_session INT NULL,
  ADD COLUMN IF NOT EXISTS realtime_step_at_session INT NULL;

COMMENT ON COLUMN v2_sessions.realtime_level_at_session IS 'Authoritative backend level snapshot before progression was applied for this session.';
COMMENT ON COLUMN v2_sessions.realtime_step_at_session IS 'Authoritative backend step snapshot before progression was applied for this session.';
