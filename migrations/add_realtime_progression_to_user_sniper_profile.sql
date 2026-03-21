-- Realtime training progression for Sniper UI.
-- Run after add_user_sniper_profile.sql.

ALTER TABLE user_sniper_profile
  ADD COLUMN IF NOT EXISTS realtime_level INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS realtime_step INT NOT NULL DEFAULT 1,
  ADD COLUMN IF NOT EXISTS realtime_pitch_baseline_st FLOAT NULL,
  ADD COLUMN IF NOT EXISTS sessions_with_pitch_count INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS realtime_last_completed_session_id UUID NULL;

COMMENT ON COLUMN user_sniper_profile.realtime_level IS 'Frontend training progression level for realtime Sniper practice.';
COMMENT ON COLUMN user_sniper_profile.realtime_step IS 'Frontend training progression step within the current level (1-10 pills).';
COMMENT ON COLUMN user_sniper_profile.realtime_pitch_baseline_st IS 'Optional per-user pitch baseline in semitones for future promotion logic.';
COMMENT ON COLUMN user_sniper_profile.sessions_with_pitch_count IS 'How many completed sessions contributed pitch data to realtime_pitch_baseline_st.';
COMMENT ON COLUMN user_sniper_profile.realtime_last_completed_session_id IS 'Last completed session that already advanced realtime progression; used for idempotency.';
