-- Store 2-sentence AI coach insight for the report view (context + fillers, progress + relevancy).
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'coach_insight') THEN
    ALTER TABLE v2_sessions ADD COLUMN coach_insight TEXT DEFAULT NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.coach_insight IS 'Two sentences from AI: (1) context from 1st recording + filler words, (2) progress from chart + relevancy to task. Shown on homework report.';
