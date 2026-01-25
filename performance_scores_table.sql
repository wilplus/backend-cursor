-- ============================================================================
-- Performance Scores Table
-- Run this in Supabase SQL Editor to create the performance_scores table
-- ============================================================================

-- Performance scores (calculated after post-answers submitted)
CREATE TABLE IF NOT EXISTS performance_scores (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  recording_id UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
  performance NUMERIC NOT NULL,  -- Core score (0.0-1.0)
  final_kpi NUMERIC NOT NULL,    -- Final KPI (0.0-1.0)
  resilience_bonus NUMERIC DEFAULT 0,
  awareness_bonus NUMERIC DEFAULT 0,
  progress_bonus NUMERIC DEFAULT 0,
  streak_bonus NUMERIC DEFAULT 0,
  filler_score NUMERIC NOT NULL,
  pacing_score NUMERIC NOT NULL,
  attitude_score NUMERIC NOT NULL,
  reflection_score NUMERIC NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(recording_id)  -- One score per recording
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_performance_scores_recording 
ON performance_scores(recording_id);

-- Verify the table was created
SELECT 
    column_name, 
    data_type, 
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public' 
  AND table_name = 'performance_scores'
ORDER BY ordinal_position;
