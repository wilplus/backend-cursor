-- Add pre-computed acoustic metrics (JSONB) to charisma_snippets.
-- Metrics are calculated ONCE during snippet extraction and stored here.
-- The admin panel reads from this column — never re-triggers computation.
--
-- Example metrics payload:
-- {
--   "wpm": null,
--   "pause_ms": 320,
--   "dynamic_db": 12.4,
--   "emphasis_per_min": 8.2,
--   "energy_ratio": 0.73,
--   "pitch_center_st": 5.1,
--   "pitch_frame_count": 245,
--   "voiced_duration_sec": 11.3
-- }

ALTER TABLE charisma_snippets
  ADD COLUMN IF NOT EXISTS metrics JSONB DEFAULT NULL;

-- Allow service role to read/write the new column
-- (RLS policies already cover row-level access)
COMMENT ON COLUMN charisma_snippets.metrics IS 'Pre-computed acoustic metrics (WPM, pitch, dB, pause, emphasis, energy). Calculated once during extraction.';
