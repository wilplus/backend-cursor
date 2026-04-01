-- AI Task Scoring: Shadow Mode columns for RLHF pipeline.
-- ai_task_score: GPT-4o-mini contextual evaluation (0-100) based on task prompt + transcript.
-- ai_scoring_justification: 1-2 sentence explanation from the LLM.
-- coach_override_score: Manual score set by coach in admin panel (overrides both legacy and AI).

ALTER TABLE v2_sessions
  ADD COLUMN IF NOT EXISTS ai_task_score integer,
  ADD COLUMN IF NOT EXISTS ai_scoring_justification text,
  ADD COLUMN IF NOT EXISTS coach_override_score integer;

-- Index for admin queries (find sessions where AI diverges from legacy)
CREATE INDEX IF NOT EXISTS idx_v2_sessions_ai_task_score ON v2_sessions(ai_task_score) WHERE ai_task_score IS NOT NULL;

COMMENT ON COLUMN v2_sessions.ai_task_score IS 'Shadow AI score (0-100) from GPT-4o-mini evaluating transcript against task prompt. Not shown to students in shadow mode.';
COMMENT ON COLUMN v2_sessions.ai_scoring_justification IS 'LLM justification for ai_task_score. 1-2 sentences.';
COMMENT ON COLUMN v2_sessions.coach_override_score IS 'Manual coach override (0-100). When set, this is the authoritative score.';
