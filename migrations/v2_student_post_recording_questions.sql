-- ============================================================================
-- Per-student post-recording questions (same mechanism as focus_tasks)
-- Pool = v2_post_recording_questions (existing). This table = assigned list
-- per student. Homework flow reads from here instead of overrides.
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_student_post_recording_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  pool_question_id UUID REFERENCES v2_post_recording_questions(id) ON DELETE SET NULL,
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  answer_type TEXT NOT NULL DEFAULT 'text' CHECK (answer_type IN ('yes_no', 'scale_1_5', 'text')),
  code TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_student_post_recording_questions_user ON v2_student_post_recording_questions(user_id);

COMMENT ON TABLE v2_student_post_recording_questions IS 'Per-student post-recording questions. Admin syncs from pool (same UX as task_focus). Homework step 4 reads from here.';
