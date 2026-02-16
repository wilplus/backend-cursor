-- ============================================================================
-- Step 4: task metadata for multi-factor scoring (weakness match).
-- targets: e.g. ["pacing", "fillers"] for need-based selection.
-- difficulty: 0..1 for future progression (optional).
-- Run after v2_focus_tasks exists.
-- ============================================================================

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_focus_tasks'
    AND column_name = 'targets'
  ) THEN
    ALTER TABLE v2_focus_tasks ADD COLUMN targets JSONB DEFAULT '[]';
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'v2_focus_tasks'
    AND column_name = 'difficulty'
  ) THEN
    ALTER TABLE v2_focus_tasks ADD COLUMN difficulty FLOAT DEFAULT 0.5;
  END IF;
END $$;

COMMENT ON COLUMN v2_focus_tasks.targets IS 'Task focus areas for weakness match: e.g. ["pacing"], ["fillers"], ["pacing","fillers"]. Recurring issue too_fast/too_slow -> pacing; high_fillers -> fillers.';
COMMENT ON COLUMN v2_focus_tasks.difficulty IS '0..1; for future difficulty alignment. Default 0.5.';
