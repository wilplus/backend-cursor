-- ============================================================================
-- V2 HOMEWORK SCHEMA — ONE FILE
-- Prerequisites: auth.users, recordings table (from base Supabase schema).
--
-- Drops (brutal): v2_metric_questions_pool, v2_post_recording_questions_pool.
-- Creates: v2_metric_questions (3 questions), v2_post_recording_questions,
--          v2_tasks, v2_exercises, v2_metric_definitions, v2_warm_up_*,
--          v2_student_overrides, v2_sessions, v2_reports, v2_speaker_profiles.
-- Idempotent: safe to run on existing DB (adds missing columns; drops old
-- metric columns from overrides). Data in dropped pool tables is lost.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) DROP UNUSED TABLES (brutal)
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS v2_metric_questions_pool CASCADE;
DROP TABLE IF EXISTS v2_post_recording_questions_pool CASCADE;

-- ----------------------------------------------------------------------------
-- 2) TASKS & EXERCISES (focus task pool; exercises for optional step)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v2_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  title TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  min_task_score FLOAT DEFAULT 0,
  max_task_score FLOAT DEFAULT 1,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS v2_exercises (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  title TEXT NOT NULL,
  video_url TEXT,
  description TEXT,
  min_task_score FLOAT DEFAULT 0,
  max_task_score FLOAT DEFAULT 1,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW()
);

-- ----------------------------------------------------------------------------
-- 3) METRIC DEFINITIONS (5 fixed codes; labels admin-editable)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v2_metric_definitions (
  code TEXT PRIMARY KEY,
  left_label TEXT NOT NULL,
  right_label TEXT NOT NULL,
  updated_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO v2_metric_definitions (code, left_label, right_label) VALUES
  ('pace', 'slow', 'fast'),
  ('strength', 'weak', 'strong'),
  ('fillers', '0-3', 'more than 3'),
  ('emotion_achieved', 'no', 'yes'),
  ('keywords_used', '<2', '>=2')
ON CONFLICT (code) DO UPDATE SET left_label = EXCLUDED.left_label, right_label = EXCLUDED.right_label, updated_at = NOW();

-- ----------------------------------------------------------------------------
-- 4) METRIC QUESTIONS (exactly 3 for task block; stored here only)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v2_metric_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  position INT NOT NULL CHECK (position IN (1, 2, 3)),
  text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO v2_metric_questions (position, text)
SELECT 1, 'What is the one thing you want your audience to understand?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 1);
INSERT INTO v2_metric_questions (position, text)
SELECT 2, 'What do you want to improve in your delivery?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 2);
INSERT INTO v2_metric_questions (position, text)
SELECT 3, 'How do you want your audience to feel?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 3);

-- ----------------------------------------------------------------------------
-- 5) POST-RECORDING QUESTIONS (one table; admin CRUD; assigned per student)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v2_post_recording_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  code TEXT UNIQUE,
  text TEXT NOT NULL,
  answer_type TEXT NOT NULL CHECK (answer_type IN ('yes_no', 'scale_1_5', 'text')),
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO v2_post_recording_questions (code, text, answer_type, is_active) VALUES
  ('emotion_achieved_check', 'Did you achieve the intended emotion?', 'yes_no', true),
  ('how_was_it', 'How was this recording for you? (1-5)', 'scale_1_5', true),
  ('reflection', 'Any reflection to add?', 'text', true)
ON CONFLICT (code) DO NOTHING;

-- ----------------------------------------------------------------------------
-- 6) WARM-UP TASK POOL + PER-STUDENT WARM-UP TASKS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v2_warm_up_task_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_warm_up_task_pool_order ON v2_warm_up_task_pool(order_index);

CREATE TABLE IF NOT EXISTS v2_warm_up_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  pool_task_id UUID REFERENCES v2_warm_up_task_pool(id) ON DELETE SET NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_warm_up_tasks_user ON v2_warm_up_tasks(user_id);

-- ----------------------------------------------------------------------------
-- 7) STUDENT OVERRIDES (no metric_question_1/2/3 — those live in v2_metric_questions)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v2_student_overrides (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  intended_emotion_prompt TEXT,
  keywords_prompt TEXT,
  emotion_check_question_text TEXT,
  assigned_post_question_ids UUID[],
  assigned_next_exercise_id UUID REFERENCES v2_exercises(id) ON DELETE SET NULL,
  assigned_next_task_ids UUID[],
  assigned_warm_up_task_id UUID REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL,
  show_exercise_step BOOLEAN DEFAULT true,
  pitch_variance_ideal FLOAT,
  updated_at TIMESTAMP DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'assigned_warm_up_task_id') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN assigned_warm_up_task_id UUID REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'show_exercise_step') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN show_exercise_step BOOLEAN DEFAULT true;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'pitch_variance_ideal') THEN
    ALTER TABLE v2_student_overrides ADD COLUMN pitch_variance_ideal FLOAT;
  END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 8) SESSIONS (homework flow: warm_up → task_block → final_task_ready → post_questions → completed)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v2_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'warm_up',
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_sessions_user ON v2_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_v2_sessions_status ON v2_sessions(user_id, status) WHERE status != 'completed';

-- Add homework columns (idempotent)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_short') THEN ALTER TABLE v2_sessions ADD COLUMN context_short TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_long') THEN ALTER TABLE v2_sessions ADD COLUMN context_long TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_long_entries') THEN ALTER TABLE v2_sessions ADD COLUMN context_long_entries JSONB DEFAULT '[]'; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'selected_task_id') THEN ALTER TABLE v2_sessions ADD COLUMN selected_task_id UUID REFERENCES v2_tasks(id) ON DELETE SET NULL; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'recording_1_id') THEN ALTER TABLE v2_sessions ADD COLUMN recording_1_id UUID REFERENCES recordings(id) ON DELETE SET NULL; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'recording_2_id') THEN ALTER TABLE v2_sessions ADD COLUMN recording_2_id UUID REFERENCES recordings(id) ON DELETE SET NULL; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_1') THEN ALTER TABLE v2_sessions ADD COLUMN performance_score_1 FLOAT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_2') THEN ALTER TABLE v2_sessions ADD COLUMN performance_score_2 FLOAT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'performance_score_end') THEN ALTER TABLE v2_sessions ADD COLUMN performance_score_end FLOAT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'session_metric_question_1') THEN ALTER TABLE v2_sessions ADD COLUMN session_metric_question_1 TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'session_metric_question_2') THEN ALTER TABLE v2_sessions ADD COLUMN session_metric_question_2 TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'session_metric_question_3') THEN ALTER TABLE v2_sessions ADD COLUMN session_metric_question_3 TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'metric_answers') THEN ALTER TABLE v2_sessions ADD COLUMN metric_answers JSONB; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_1_analysis') THEN ALTER TABLE v2_sessions ADD COLUMN question_1_analysis TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_1_score') THEN ALTER TABLE v2_sessions ADD COLUMN question_1_score FLOAT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_2_analysis') THEN ALTER TABLE v2_sessions ADD COLUMN question_2_analysis TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_2_score') THEN ALTER TABLE v2_sessions ADD COLUMN question_2_score FLOAT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_3_analysis') THEN ALTER TABLE v2_sessions ADD COLUMN question_3_analysis TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'question_3_score') THEN ALTER TABLE v2_sessions ADD COLUMN question_3_score FLOAT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'pitch_variance_avg') THEN ALTER TABLE v2_sessions ADD COLUMN pitch_variance_avg FLOAT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'report_id') THEN ALTER TABLE v2_sessions ADD COLUMN report_id UUID; END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 9) REPORTS
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v2_reports (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_v2_id UUID NOT NULL REFERENCES v2_sessions(id) ON DELETE CASCADE,
  recording_id UUID REFERENCES recordings(id) ON DELETE SET NULL,
  report_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Add FK from sessions to reports if you use report_id on session
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'v2_sessions_report_id_fkey' AND table_name = 'v2_sessions') THEN
    ALTER TABLE v2_sessions ADD CONSTRAINT v2_sessions_report_id_fkey FOREIGN KEY (report_id) REFERENCES v2_reports(id) ON DELETE SET NULL;
  END IF;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ----------------------------------------------------------------------------
-- 10) RECORDINGS — add v2 columns (recordings table must already exist)
-- ----------------------------------------------------------------------------
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'session_v2_id') THEN
    ALTER TABLE recordings ADD COLUMN session_v2_id UUID REFERENCES v2_sessions(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'task_id') THEN
    ALTER TABLE recordings ADD COLUMN task_id UUID REFERENCES v2_tasks(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'performance_score_v2') THEN
    ALTER TABLE recordings ADD COLUMN performance_score_v2 FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'performance_metrics_v2') THEN
    ALTER TABLE recordings ADD COLUMN performance_metrics_v2 JSONB;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'metric_labels_snapshot_v2') THEN
    ALTER TABLE recordings ADD COLUMN metric_labels_snapshot_v2 JSONB;
  END IF;
END $$;

-- ----------------------------------------------------------------------------
-- 11) SPEAKER PROFILES (admin per-student)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS v2_speaker_profiles (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  main_goal TEXT,
  motivation TEXT,
  strong_points TEXT,
  weak_points TEXT,
  charismatic_traits TEXT,
  hobbies_interests TEXT,
  personality_type TEXT,
  coach_notes TEXT,
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_speaker_profiles_updated ON v2_speaker_profiles(updated_at);

-- ----------------------------------------------------------------------------
-- 12) REMOVE metric_question_1/2/3 FROM OVERRIDES (if they exist from old migration)
-- ----------------------------------------------------------------------------
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

-- ----------------------------------------------------------------------------
-- COMMENTS
-- ----------------------------------------------------------------------------
COMMENT ON TABLE v2_metric_questions IS 'The 3 metric questions in the task block (e.g. What is the one thing you want your audience to understand?). Positions 1, 2, 3.';
COMMENT ON TABLE v2_post_recording_questions IS 'Post-recording reflective questions. Admin CRUD; assigned per student via assigned_post_question_ids.';
