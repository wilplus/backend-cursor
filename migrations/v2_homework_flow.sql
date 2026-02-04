-- ============================================================================
-- Homework Flow v2: warm-up tasks, metric questions, session context/scores
-- Run after v2_flow.sql. See docs/FLOW-HOMEWORK-V2.md.
-- ============================================================================

-- 1) Warm-up tasks (per student; admin CRUD on student profile)
CREATE TABLE IF NOT EXISTS v2_warm_up_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_warm_up_tasks_user ON v2_warm_up_tasks(user_id);

-- 2) Metric questions (2 questions: metric_question_1, metric_question_2; admin CRUD in Metrics section)
CREATE TABLE IF NOT EXISTS v2_metric_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  position INT NOT NULL CHECK (position IN (1, 2)),
  text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Seed two metric questions if none exist
INSERT INTO v2_metric_questions (position, text)
SELECT 1, 'How would you rate your pacing in that take?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 1);
INSERT INTO v2_metric_questions (position, text)
SELECT 2, 'How would you rate your vocal strength?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 2);

-- 3) Session columns for homework flow (context, scores, two recordings)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_short') THEN
    ALTER TABLE v2_sessions ADD COLUMN context_short TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_long') THEN
    ALTER TABLE v2_sessions ADD COLUMN context_long TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_1') THEN
    ALTER TABLE v2_sessions ADD COLUMN performance_score_1 FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_2') THEN
    ALTER TABLE v2_sessions ADD COLUMN performance_score_2 FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_end') THEN
    ALTER TABLE v2_sessions ADD COLUMN performance_score_end FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'recording_1_id') THEN
    ALTER TABLE v2_sessions ADD COLUMN recording_1_id UUID REFERENCES recordings(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'recording_2_id') THEN
    ALTER TABLE v2_sessions ADD COLUMN recording_2_id UUID REFERENCES recordings(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'metric_answers') THEN
    ALTER TABLE v2_sessions ADD COLUMN metric_answers JSONB;
  END IF;
END $$;
