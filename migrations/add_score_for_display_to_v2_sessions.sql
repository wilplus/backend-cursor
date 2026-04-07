-- Canonical student-visible score fields.
-- Safe to run multiple times.

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'score_for_display'
  ) THEN
    ALTER TABLE public.v2_sessions ADD COLUMN score_for_display SMALLINT;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'score_ready_at'
  ) THEN
    ALTER TABLE public.v2_sessions ADD COLUMN score_ready_at TIMESTAMPTZ;
  END IF;

  IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'score_components'
  ) THEN
    ALTER TABLE public.v2_sessions ADD COLUMN score_components JSONB DEFAULT '{}'::jsonb;
  END IF;
END $$;

ALTER TABLE public.v2_sessions
  DROP CONSTRAINT IF EXISTS v2_sessions_score_for_display_range;

ALTER TABLE public.v2_sessions
  ADD CONSTRAINT v2_sessions_score_for_display_range
  CHECK (
    score_for_display IS NULL
    OR (score_for_display >= 0 AND score_for_display <= 100)
  );

COMMENT ON COLUMN public.v2_sessions.score_for_display IS
'Canonical student-visible score 0-100 used by report header and chart.';
COMMENT ON COLUMN public.v2_sessions.score_ready_at IS
'Timestamp when score_for_display became final and safe to show.';
COMMENT ON COLUMN public.v2_sessions.score_components IS
'Debug payload with weighted component scores used to compute score_for_display.';

-- Backfill from existing score for completed sessions where possible.
UPDATE public.v2_sessions
SET
  score_for_display = GREATEST(0, LEAST(100, ROUND(COALESCE(score, 0) * 100)::int)),
  score_ready_at = COALESCE(score_ready_at, completed_at, NOW()),
  score_components = COALESCE(score_components, '{}'::jsonb) || jsonb_build_object(
    'backfilled_from_score', true,
    'score_01', COALESCE(score, 0),
    'score_100', GREATEST(0, LEAST(100, ROUND(COALESCE(score, 0) * 100)::int))
  )
WHERE status = 'completed'
  AND score_for_display IS NULL
  AND score IS NOT NULL;
