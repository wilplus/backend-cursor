-- Adaptive Sniper: per-user baseline and per-session metrics for growth score.
-- Run after v2_all_in_one.sql. Backend uses service role (bypasses RLS).

-- Per-user baseline (raw metric means; EMA updated after each valid session).
CREATE TABLE IF NOT EXISTS user_sniper_profile (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  session_count INT NOT NULL DEFAULT 0,
  sessions_with_energy_count INT NOT NULL DEFAULT 0,
  baseline_wpm FLOAT,
  baseline_pause_ms FLOAT,
  baseline_dynamic_db FLOAT,
  baseline_emphasis_per_min FLOAT,
  baseline_energy_ratio FLOAT,
  baseline_fatigue_sec FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE user_sniper_profile IS 'Sniper adaptive layer: per-user baseline metrics (EMA). Growth score = improvement vs baseline.';

-- Per-session metrics (from client sniper-session-complete); merged into baseline when session completes.
CREATE TABLE IF NOT EXISTS session_sniper_metrics (
  session_id UUID PRIMARY KEY REFERENCES v2_sessions(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  wpm FLOAT,
  pause_ms FLOAT,
  dynamic_db FLOAT,
  emphasis_per_min FLOAT,
  energy_ratio FLOAT,
  stage_score FLOAT,
  voiced_duration_sec FLOAT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_session_sniper_metrics_user ON session_sniper_metrics(user_id);
COMMENT ON TABLE session_sniper_metrics IS 'Sniper session aggregates (from client). Used to update user_sniper_profile when session completes.';
