-- ============================================================================
-- Metric questions: store in v2_metric_questions only (not in v2_student_overrides).
-- Post-recording questions: use separate table v2_post_recording_questions.
-- ============================================================================

-- 1) Ensure v2_metric_questions exists and allows position 1, 2, 3
CREATE TABLE IF NOT EXISTS v2_metric_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  position INT NOT NULL,
  text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Allow position 3 (drop old check that only allowed 1,2; add check for 1,2,3)
DO $$ BEGIN
  ALTER TABLE v2_metric_questions DROP CONSTRAINT IF EXISTS v2_metric_questions_position_check;
EXCEPTION WHEN undefined_object THEN NULL;
END $$;
ALTER TABLE v2_metric_questions ADD CONSTRAINT v2_metric_questions_position_check CHECK (position IN (1, 2, 3));

-- Seed 3 default metric questions if missing (e.g. "What is the one thing you want your audience to understand?")
INSERT INTO v2_metric_questions (position, text)
SELECT 1, 'What is the one thing you want your audience to understand?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 1);
INSERT INTO v2_metric_questions (position, text)
SELECT 2, 'What do you want to improve in your delivery?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 2);
INSERT INTO v2_metric_questions (position, text)
SELECT 3, 'How do you want your audience to feel?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 3);

-- 2) Remove metric_question_1, metric_question_2, metric_question_3 from v2_student_overrides
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'metric_question_1') THEN
    ALTER TABLE v2_student_overrides DROP COLUMN metric_question_1;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'metric_question_2') THEN
    ALTER TABLE v2_student_overrides DROP COLUMN metric_question_2;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'metric_question_3') THEN
    ALTER TABLE v2_student_overrides DROP COLUMN metric_question_3;
  END IF;
END $$;

COMMENT ON TABLE v2_metric_questions IS 'The 3 metric questions shown in the task block (e.g. What is the one thing you want your audience to understand?). One row per position 1, 2, 3.';
