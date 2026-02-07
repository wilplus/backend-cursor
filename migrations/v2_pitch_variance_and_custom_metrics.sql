-- ============================================================================
-- Pitch variance + custom metric questions (per user, LLM-analyzed per session)
-- - User stores 3 editable questions (metric_question_1, 2, 3).
-- - Session stores snapshot of questions at start + LLM results at end.
-- ============================================================================

-- 1) Per-user metric questions (Metrics editor)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'metric_question_1') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN metric_question_1 TEXT DEFAULT '';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'metric_question_2') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN metric_question_2 TEXT DEFAULT '';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'metric_question_3') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN metric_question_3 TEXT DEFAULT '';
  END IF;
END $$;

-- Optional: pitch_variance display config (e.g. ideal or scale)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'pitch_variance_ideal') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN pitch_variance_ideal FLOAT;
  END IF;
END $$;

-- 2) Session: snapshot of 3 questions at start (used for LLM at end)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'session_metric_question_1') THEN
    ALTER TABLE v2_sessions ADD COLUMN session_metric_question_1 TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'session_metric_question_2') THEN
    ALTER TABLE v2_sessions ADD COLUMN session_metric_question_2 TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'session_metric_question_3') THEN
    ALTER TABLE v2_sessions ADD COLUMN session_metric_question_3 TEXT;
  END IF;
END $$;

-- 3) Session: post-recording LLM analysis (filled when session ends)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_1_analysis') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_1_analysis TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_1_score') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_1_score FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_2_analysis') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_2_analysis TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_2_score') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_2_score FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_3_analysis') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_3_analysis TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_3_score') THEN
    ALTER TABLE v2_sessions ADD COLUMN question_3_score FLOAT;
  END IF;
END $$;

-- 4) Session: optional average pitch_variance from real-time stream
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'pitch_variance_avg') THEN
    ALTER TABLE v2_sessions ADD COLUMN pitch_variance_avg FLOAT;
  END IF;
END $$;
