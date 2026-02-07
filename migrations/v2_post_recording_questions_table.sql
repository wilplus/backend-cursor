-- ============================================================================
-- Post-recording questions: use dedicated table v2_post_recording_questions.
-- Rename v2_post_recording_questions_pool -> v2_post_recording_questions.
-- ============================================================================

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'v2_post_recording_questions_pool')
     AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'v2_post_recording_questions') THEN
    ALTER TABLE v2_post_recording_questions_pool RENAME TO v2_post_recording_questions;
  END IF;
END $$;

COMMENT ON TABLE v2_post_recording_questions IS 'Post-recording reflective questions. Admin CRUD; assigned per student via assigned_post_question_ids.';
