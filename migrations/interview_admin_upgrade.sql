-- ============================================================================
-- Migration: Interview Admin Upgrade
-- Adds: user LLM instructions, snippet boundaries/metrics columns,
--        session-level global metrics, AI alignment evaluation.
-- ============================================================================

-- 1. Users: custom LLM prompt injection per user
-- (auth.users is managed by Supabase Auth; we use a separate profile table
--  or add to an existing custom users table. Using v2_sessions user metadata.)
ALTER TABLE auth.users
  ADD COLUMN IF NOT EXISTS raw_user_meta_data JSONB DEFAULT '{}'::jsonb;
-- NOTE: Supabase auth.users already has raw_user_meta_data. We'll store
-- custom_llm_instructions in a dedicated column on a profiles/settings table instead.

-- Create user_settings table for custom LLM instructions
CREATE TABLE IF NOT EXISTS user_settings (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  custom_llm_instructions TEXT DEFAULT NULL,
  created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE user_settings IS 'Per-user settings including custom LLM prompt injections for interview sessions.';
COMMENT ON COLUMN user_settings.custom_llm_instructions IS 'Admin-defined text appended to the LLM system prompt when generating questions for this user.';

-- Add learning_profile to existing user_admin_context table
ALTER TABLE user_admin_context
  ADD COLUMN IF NOT EXISTS learning_profile VARCHAR(50) DEFAULT NULL;
COMMENT ON COLUMN user_admin_context.learning_profile IS 'Admin-assigned profile type: stressor, racer, freezer, etc. Affects session tuning.';

-- 2. Snippets: add start_time, end_time, is_skipped, and individual metric columns
ALTER TABLE charisma_snippets
  ADD COLUMN IF NOT EXISTS start_time FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS end_time FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS is_skipped BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS question_text TEXT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS question_tone VARCHAR(20) DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS turn_number INTEGER DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS wpm FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS fillers INTEGER DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS pause_ms FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS dynamic_db FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS pitch_center FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS energy FLOAT DEFAULT NULL;

COMMENT ON COLUMN charisma_snippets.start_time IS 'Start boundary of audio slice in seconds (adjustable by admin +/- 2s).';
COMMENT ON COLUMN charisma_snippets.end_time IS 'End boundary of audio slice in seconds (adjustable by admin +/- 2s).';
COMMENT ON COLUMN charisma_snippets.is_skipped IS 'Admin can hide a snippet from the user results view.';
COMMENT ON COLUMN charisma_snippets.question_text IS 'The bot question that prompted this answer.';
COMMENT ON COLUMN charisma_snippets.question_tone IS 'charisma or stress — the tone category of the question.';
COMMENT ON COLUMN charisma_snippets.turn_number IS 'Sequential turn index within the interview session.';
COMMENT ON COLUMN charisma_snippets.wpm IS 'Words per minute (from transcript).';
COMMENT ON COLUMN charisma_snippets.fillers IS 'Count of filler words (um, uh, like, etc).';
COMMENT ON COLUMN charisma_snippets.pause_ms IS 'Average pause duration in milliseconds.';
COMMENT ON COLUMN charisma_snippets.dynamic_db IS 'Dynamic range in dB (P95 - P5 of voiced frames).';
COMMENT ON COLUMN charisma_snippets.pitch_center IS 'Median pitch in semitones above 100Hz reference.';
COMMENT ON COLUMN charisma_snippets.energy IS 'Voiced energy ratio (0-1).';

-- 3. Sessions: global acoustic metrics + AI alignment evaluation
ALTER TABLE v2_sessions
  ADD COLUMN IF NOT EXISTS global_wpm FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS global_fillers INTEGER DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS global_pause_ms FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS global_dynamic_db FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS global_pitch_center FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS global_energy FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS kpi_score FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS ai_task_alignment_score FLOAT DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS ai_task_alignment_comment TEXT DEFAULT NULL;

COMMENT ON COLUMN v2_sessions.global_wpm IS 'Session-wide average WPM across all snippets.';
COMMENT ON COLUMN v2_sessions.global_fillers IS 'Total filler word count across the entire session.';
COMMENT ON COLUMN v2_sessions.global_pause_ms IS 'Average pause duration across the session.';
COMMENT ON COLUMN v2_sessions.global_dynamic_db IS 'Average dynamic range across the session.';
COMMENT ON COLUMN v2_sessions.global_pitch_center IS 'Average pitch center across the session.';
COMMENT ON COLUMN v2_sessions.global_energy IS 'Average energy ratio across the session.';
COMMENT ON COLUMN v2_sessions.kpi_score IS 'Quantitative KPI (0-100) computed from energy, fillers, and WPM via metrics_v2 formula.';
COMMENT ON COLUMN v2_sessions.ai_task_alignment_score IS 'LLM-generated overall performance score (0-100), incorporating the KPI.';
COMMENT ON COLUMN v2_sessions.ai_task_alignment_comment IS 'LLM-generated summary of the user performance across the interview.';

-- Index for efficient admin queries
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_turn ON charisma_snippets(session_id, turn_number);
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_not_skipped ON charisma_snippets(session_id) WHERE is_skipped = FALSE;
