-- Canonical single homework score on v2_sessions.
-- Safe to run multiple times.

ALTER TABLE IF EXISTS v2_sessions
  ADD COLUMN IF NOT EXISTS score DOUBLE PRECISION;

-- Backfill from legacy columns when present.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_end'
  ) THEN
    EXECUTE '
      UPDATE v2_sessions
      SET score = COALESCE(score, performance_score_end, performance_score_1, performance_score_2)
      WHERE score IS NULL
    ';
  ELSE
    -- Legacy columns already removed; keep existing score values.
    EXECUTE '
      UPDATE v2_sessions
      SET score = score
      WHERE score IS NULL
    ';
  END IF;
END $$;

ALTER TABLE IF EXISTS v2_sessions
  DROP CONSTRAINT IF EXISTS v2_sessions_score_range;

ALTER TABLE IF EXISTS v2_sessions
  ADD CONSTRAINT v2_sessions_score_range
  CHECK (score IS NULL OR (score >= 0 AND score <= 1));
