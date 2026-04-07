-- Add optional AI/coach override fields used by admin review UI.
-- Safe to run multiple times.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'ai_task_score'
  ) THEN
    ALTER TABLE v2_sessions ADD COLUMN ai_task_score SMALLINT DEFAULT NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'ai_scoring_justification'
  ) THEN
    ALTER TABLE v2_sessions ADD COLUMN ai_scoring_justification TEXT DEFAULT NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'coach_override_score'
  ) THEN
    ALTER TABLE v2_sessions ADD COLUMN coach_override_score SMALLINT DEFAULT NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'coach_override_justification'
  ) THEN
    ALTER TABLE v2_sessions ADD COLUMN coach_override_justification TEXT DEFAULT NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.ai_task_score IS 'AI score (0-100) for session task quality, shown in admin review.';
COMMENT ON COLUMN v2_sessions.ai_scoring_justification IS 'AI explanation for ai_task_score.';
COMMENT ON COLUMN v2_sessions.coach_override_score IS 'Coach override score (0-100), authoritative when set.';
COMMENT ON COLUMN v2_sessions.coach_override_justification IS 'Coach reason for overriding AI score (used for training feedback).';
