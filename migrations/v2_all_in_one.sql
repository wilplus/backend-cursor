-- ============================================================================
-- V2 MIGRATIONS — ALL IN ONE (run in order)
-- Run this after your base schema (.taskmaster/docs/schema.sql) so that
-- tables like recording_sessions and recordings exist.
-- Execute in Supabase SQL Editor; then Settings → API → Reload schema cache.
-- ============================================================================

-- ============================================================================
-- 1) V2 FLOW — Major Flow v2 + Admin CRUD
-- ============================================================================

-- 1) Universal questions (3 fixed; seed only, no admin CRUD)
CREATE TABLE IF NOT EXISTS v2_universal_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  code TEXT UNIQUE NOT NULL,
  text TEXT NOT NULL,
  answer_type TEXT NOT NULL CHECK (answer_type IN ('slider_0_1', 'scale_1_10', 'binary')),
  position INT NOT NULL
);

INSERT INTO v2_universal_questions (code, text, answer_type, position) VALUES
  ('mood', 'Do you feel more like: Good or Not great?', 'binary', 1),
  ('readiness', 'How ready is your body and mind to present? (1-10)', 'scale_1_10', 2),
  ('mode_preference', 'Do you want to be guided?', 'binary', 3)
ON CONFLICT (code) DO UPDATE SET text = EXCLUDED.text, answer_type = EXCLUDED.answer_type, position = EXCLUDED.position;

-- 2) Exercises
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

-- 3) Tasks (recording prompts)
CREATE TABLE IF NOT EXISTS v2_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  title TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  min_task_score FLOAT DEFAULT 0,
  max_task_score FLOAT DEFAULT 1,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW()
);

-- 4) Post-recording questions pool (admin CRUD; one row per question definition)
CREATE TABLE IF NOT EXISTS v2_post_recording_questions_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  code TEXT UNIQUE,
  text TEXT NOT NULL,
  answer_type TEXT NOT NULL CHECK (answer_type IN ('yes_no', 'scale_1_5', 'text')),
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT NOW()
);

-- 5) Metric definitions (exactly 5 fixed codes; labels admin-editable)
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

-- 6) Student overrides (per user)
CREATE TABLE IF NOT EXISTS v2_student_overrides (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  intended_emotion_prompt TEXT,
  keywords_prompt TEXT,
  emotion_check_question_text TEXT,
  assigned_post_question_ids UUID[],
  assigned_next_exercise_id UUID REFERENCES v2_exercises(id) ON DELETE SET NULL,
  assigned_next_task_ids UUID[],
  updated_at TIMESTAMP DEFAULT NOW()
);

-- 7) V2 sessions (v1_session_id links to recording_sessions for "same flow as v1" after universal-answers)
CREATE TABLE IF NOT EXISTS v2_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  created_at TIMESTAMP DEFAULT NOW(),
  universal_answers JSONB,
  task_score FLOAT,
  mode_preference INT CHECK (mode_preference IN (0, 1)),
  v1_session_id UUID REFERENCES recording_sessions(id) ON DELETE SET NULL,
  selected_exercise_id UUID REFERENCES v2_exercises(id) ON DELETE SET NULL,
  exercise_liked BOOLEAN,
  selected_task_id UUID REFERENCES v2_tasks(id) ON DELETE SET NULL,
  task_option_ids UUID[],
  intended_emotion TEXT,
  keywords TEXT[],
  post_question_ids UUID[],
  post_answers JSONB,
  recording_id UUID,
  report_id UUID,
  status TEXT NOT NULL DEFAULT 'universal_questions'
);

CREATE INDEX IF NOT EXISTS idx_v2_sessions_user ON v2_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_v2_sessions_status ON v2_sessions(user_id, status) WHERE status != 'completed';

-- 8) Recordings: add v2 columns (do not remove existing columns)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'session_v2_id') THEN
    ALTER TABLE public.recordings ADD COLUMN session_v2_id UUID REFERENCES v2_sessions(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'task_id') THEN
    ALTER TABLE public.recordings ADD COLUMN task_id UUID REFERENCES v2_tasks(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'performance_score_v2') THEN
    ALTER TABLE public.recordings ADD COLUMN performance_score_v2 FLOAT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'performance_metrics_v2') THEN
    ALTER TABLE public.recordings ADD COLUMN performance_metrics_v2 JSONB;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'metric_labels_snapshot_v2') THEN
    ALTER TABLE public.recordings ADD COLUMN metric_labels_snapshot_v2 JSONB;
  END IF;
END $$;

-- 9) Reports (v2)
CREATE TABLE IF NOT EXISTS v2_reports (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_v2_id UUID NOT NULL REFERENCES v2_sessions(id) ON DELETE CASCADE,
  recording_id UUID REFERENCES recordings(id) ON DELETE SET NULL,
  report_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Seed post-recording questions pool (must include emotion_achieved_check)
INSERT INTO v2_post_recording_questions_pool (code, text, answer_type, is_active) VALUES
  ('emotion_achieved_check', 'Did you achieve the intended emotion?', 'yes_no', true),
  ('how_was_it', 'How was this recording for you? (1-5)', 'scale_1_5', true),
  ('reflection', 'Any reflection to add?', 'text', true)
ON CONFLICT (code) DO NOTHING;


-- ============================================================================
-- 2) Speaker profiles (admin-editable per student)
-- ============================================================================

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


-- ============================================================================
-- 3) Per-student: show_exercise_step (admin toggle on student profile)
-- ============================================================================

ALTER TABLE v2_student_overrides
  ADD COLUMN IF NOT EXISTS show_exercise_step BOOLEAN DEFAULT true;

COMMENT ON COLUMN v2_student_overrides.show_exercise_step IS 'When false, this student never sees the exercise step. Set per student on their profile.';


-- ============================================================================
-- 4) Homework flow: warm-up tasks, metric questions, session context/scores
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_warm_up_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_warm_up_tasks_user ON v2_warm_up_tasks(user_id);

CREATE TABLE IF NOT EXISTS v2_metric_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  position INT NOT NULL CHECK (position IN (1, 2)),
  text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO v2_metric_questions (position, text)
SELECT 1, 'How would you rate your pacing in that take?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 1);
INSERT INTO v2_metric_questions (position, text)
SELECT 2, 'How would you rate your vocal strength?'
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions WHERE position = 2);

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


-- ============================================================================
-- 5) Homework flow: assigned_warm_up_task_id + context_long_entries
-- ============================================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_overrides' AND column_name = 'assigned_warm_up_task_id') THEN
    ALTER TABLE v2_student_overrides
    ADD COLUMN assigned_warm_up_task_id UUID REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'context_long_entries') THEN
    ALTER TABLE v2_sessions ADD COLUMN context_long_entries JSONB DEFAULT '[]';
  END IF;
END $$;

COMMENT ON COLUMN v2_student_overrides.assigned_warm_up_task_id IS 'The single warm-up task the student sees for the next homework run. Admin sets this on student profile.';
COMMENT ON COLUMN v2_sessions.context_long_entries IS 'Append-only list of report entries: [{ "at": "ISO8601", "text": "..." }]. Latest = last element.';

-- ============================================================================
-- 6) Warm-up selection by last performance_score (max_performance_score)
-- ============================================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_warm_up_tasks' AND column_name = 'max_performance_score') THEN
    ALTER TABLE v2_warm_up_tasks ADD COLUMN max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1);
  END IF;
END $$;

COMMENT ON COLUMN v2_warm_up_tasks.max_performance_score IS 'Show this warm-up to students with last performance_score_end <= this value (0-1). Easiest = 1.0. Selection: eligible where max_performance_score >= last_score; then closest ±3%%; random if ties.';

-- ============================================================================
-- 7) Warm-up task pool (global pool; admin selects which apply per student)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_warm_up_task_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_warm_up_task_pool_order ON v2_warm_up_task_pool(order_index);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_warm_up_tasks' AND column_name = 'pool_task_id') THEN
    ALTER TABLE v2_warm_up_tasks
    ADD COLUMN pool_task_id UUID REFERENCES v2_warm_up_task_pool(id) ON DELETE SET NULL;
  END IF;
END $$;

-- ============================================================================
-- 8) Metric questions pool (metric_question_1, 2, 3; editable in admin, same mechanics as warm-up-task-pool)
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_metric_questions_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_v2_metric_questions_pool_order ON v2_metric_questions_pool(order_index);

INSERT INTO v2_metric_questions_pool (text, order_index)
SELECT 'How would you rate your pacing in that take?', 1
WHERE NOT EXISTS (SELECT 1 FROM v2_metric_questions_pool LIMIT 1);
INSERT INTO v2_metric_questions_pool (text, order_index)
SELECT 'How would you rate your vocal strength?', 2
WHERE (SELECT COUNT(*) FROM v2_metric_questions_pool) = 1;
INSERT INTO v2_metric_questions_pool (text, order_index)
SELECT 'How would you rate your clarity and articulation?', 3
WHERE (SELECT COUNT(*) FROM v2_metric_questions_pool) = 2;
