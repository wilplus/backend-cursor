-- ============================================================================
-- v2_student_coaching_memory: per-student rolling memory for need-based coaching.
-- Step 2 of coaching redesign. Minimal version: last_5_scores, recent_focus_task_ids.
-- Run after v2_sessions exists (completed_at, performance_score_end, selected_task_id).
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_student_coaching_memory (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  last_5_scores JSONB DEFAULT '[]',
  recent_focus_task_ids JSONB DEFAULT '[]',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE v2_student_coaching_memory IS 'Per-student coaching memory. last_5_scores: performance_score_end from last 5 completed sessions (oldest first). recent_focus_task_ids: selected_task_id from last 5 (oldest first). Updated on each session completion.';
COMMENT ON COLUMN v2_student_coaching_memory.last_5_scores IS 'Array of 0-5 floats (0-1), oldest first. From v2_sessions.performance_score_end.';
COMMENT ON COLUMN v2_student_coaching_memory.recent_focus_task_ids IS 'Array of up to 5 task UUID strings, oldest first. From v2_sessions.selected_task_id.';
