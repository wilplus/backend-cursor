-- Speed up "last 4 completed sessions" query used by v2_upsert_student_coaching_memory.
-- Query: WHERE user_id = ? AND status = 'completed' AND id != ? ORDER BY completed_at DESC LIMIT 4
-- Run after v2_sessions has completed_at (add_tutor_feedback_deadline.sql).

CREATE INDEX IF NOT EXISTS idx_v2_sessions_user_status_completed_at
  ON v2_sessions (user_id, status, completed_at DESC NULLS LAST);
