-- ============================================================================
-- WILLAB — COMPLETE APP SCHEMA (single file)
-- Run in Supabase SQL Editor. Requires: auth.users (Supabase default).
-- Idempotent: safe to run multiple times (CREATE IF NOT EXISTS, ADD COLUMN IF NOT EXISTS).
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- PART 1: BASE (v1) — Recording sessions, recordings, questions, answers
-- ============================================================================

CREATE TABLE IF NOT EXISTS pre_recording_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  question_text TEXT NOT NULL,
  order_index INT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  code TEXT UNIQUE,
  theme_code TEXT,
  question_type TEXT NOT NULL DEFAULT 'text_short',
  active BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS post_recording_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  question_text TEXT NOT NULL,
  question_type TEXT,
  question_set_id INTEGER,
  order_index INTEGER,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recording_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  status TEXT CHECK (status IN (
    'pre_questions_pending','recording_ready','recording_uploaded','post_questions_pending',
    'generating_report','completed','abandoned','report_generation_failed'
  )) DEFAULT 'pre_questions_pending',
  recording_id UUID,
  abandon_reason TEXT,
  abandoned_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP,
  last_activity_at TIMESTAMP DEFAULT NOW(),
  pre_questions_completed BOOLEAN DEFAULT FALSE NOT NULL,
  recording_completed BOOLEAN DEFAULT FALSE NOT NULL,
  post_questions_completed BOOLEAN DEFAULT FALSE NOT NULL,
  mood TEXT,
  readiness INTEGER,
  inspiration_needed BOOLEAN,
  cursor NUMERIC,
  mode TEXT,
  structure TEXT,
  theme_recommended_code TEXT,
  theme_recommended_reason TEXT,
  theme_chosen_code TEXT,
  theme_chosen_source TEXT,
  planned_pre_question_id UUID REFERENCES pre_recording_questions(id),
  planned_pre_question_text_snapshot TEXT,
  planned_pre_question_type_snapshot TEXT,
  planned_pre_question_code_snapshot TEXT,
  selected_command_option_id TEXT,
  selected_intent TEXT,
  selected_tier INTEGER,
  selected_mode TEXT,
  selected_prompt_text_snapshot TEXT,
  post_question_set_id INTEGER,
  admin_override_id_applied UUID,
  admin_override_consumed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recordings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id UUID,
  audio_url TEXT NOT NULL,
  duration INT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  transcription_text TEXT,
  duration_seconds NUMERIC,
  words_per_minute NUMERIC,
  filler_words_count JSONB,
  classification TEXT,
  confidence TEXT,
  storage_path TEXT,
  coaching_report TEXT,
  trend_sentence TEXT,
  command_option_id TEXT,
  biofeedback_summary JSONB,
  voice_stability NUMERIC,
  energy_score NUMERIC,
  pacing_score NUMERIC
);

DO $$ BEGIN
  ALTER TABLE recording_sessions ADD CONSTRAINT fk_recording FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
  ALTER TABLE recordings ADD CONSTRAINT fk_session FOREIGN KEY (session_id) REFERENCES recording_sessions(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS pre_recording_answers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  recording_session_id UUID REFERENCES recording_sessions(id) ON DELETE CASCADE,
  question_id UUID REFERENCES pre_recording_questions(id),
  answer_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  question_text_snapshot TEXT,
  question_type_snapshot TEXT,
  question_code_snapshot TEXT,
  order_index_snapshot INTEGER
);

CREATE TABLE IF NOT EXISTS post_recording_answers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  recording_id UUID REFERENCES recordings(id) ON DELETE CASCADE,
  session_id UUID REFERENCES recording_sessions(id) ON DELETE CASCADE,
  question_id UUID REFERENCES post_recording_questions(id),
  answer_text TEXT NOT NULL,
  reflection_text TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS performance_scores (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  recording_id UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
  performance NUMERIC NOT NULL,
  final_kpi NUMERIC NOT NULL,
  resilience_bonus NUMERIC DEFAULT 0,
  awareness_bonus NUMERIC DEFAULT 0,
  progress_bonus NUMERIC DEFAULT 0,
  streak_bonus NUMERIC DEFAULT 0,
  filler_score NUMERIC NOT NULL,
  pacing_score NUMERIC NOT NULL,
  attitude_score NUMERIC NOT NULL,
  reflection_score NUMERIC NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  self_rating_score NUMERIC,
  voice_stability_score NUMERIC DEFAULT 0,
  energy_score NUMERIC DEFAULT 0,
  awareness_score NUMERIC DEFAULT 0,
  mood_multiplier NUMERIC,
  readiness_score NUMERIC,
  UNIQUE(recording_id)
);

-- ============================================================================
-- PART 2: PROFESSIONAL NOTES & ADMIN (v1)
-- ============================================================================

CREATE TABLE IF NOT EXISTS professional_notes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  notes TEXT,
  updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS professional_notes_report_tech (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  max_words INT DEFAULT 120,
  custom_instructions TEXT,
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id)
);

CREATE TABLE IF NOT EXISTS professional_notes_specific_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  question_text TEXT NOT NULL,
  question_type TEXT CHECK (question_type IN ('pre', 'post')),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email TEXT UNIQUE NOT NULL,
  role TEXT CHECK (role IN ('super_admin', 'coach', 'reviewer')),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_notifications (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id UUID REFERENCES recording_sessions(id) ON DELETE CASCADE,
  recording_id UUID REFERENCES recordings(id) ON DELETE SET NULL,
  sent_to TEXT NOT NULL,
  subject TEXT NOT NULL,
  payload_json JSONB,
  status TEXT CHECK (status IN ('pending', 'sent', 'failed')) DEFAULT 'pending',
  error TEXT,
  sent_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS admin_session_overrides (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  force_theme_code TEXT,
  force_mode TEXT,
  force_tier INTEGER,
  force_intent TEXT,
  force_post_question_set_id INTEGER,
  remaining_sessions INTEGER,
  expires_at TIMESTAMP,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  set_by_admin_id UUID REFERENCES admin_users(id) ON DELETE SET NULL,
  reason TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS session_command_options (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_id UUID NOT NULL REFERENCES recording_sessions(id) ON DELETE CASCADE,
  option_id TEXT NOT NULL,
  intent TEXT NOT NULL,
  tier INTEGER NOT NULL,
  mode TEXT NOT NULL,
  cursor_min NUMERIC,
  cursor_max NUMERIC,
  prompt_text_snapshot TEXT NOT NULL,
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(session_id, option_id)
);

CREATE TABLE IF NOT EXISTS content_exposures (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id UUID REFERENCES recording_sessions(id) ON DELETE CASCADE,
  recording_id UUID REFERENCES recordings(id) ON DELETE SET NULL,
  content_type TEXT NOT NULL,
  content_code TEXT NOT NULL,
  content_id UUID,
  tier INTEGER,
  was_selected BOOLEAN NOT NULL DEFAULT FALSE,
  exposed_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_filler_patterns (
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  filler_word TEXT NOT NULL,
  frequency INT DEFAULT 0,
  last_updated TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (user_id, filler_word)
);

-- ============================================================================
-- PART 3: V2 HOMEWORK FLOW
-- ============================================================================

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

-- Per-student post-recording questions (same mechanism as focus_tasks). Homework step 4 reads from here.
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
COMMENT ON TABLE v2_student_post_recording_questions IS 'Per-student post-recording questions. Admin syncs from pool. Homework step 4 reads from here.';
COMMENT ON COLUMN v2_student_post_recording_questions.code IS 'Copied from pool (e.g. emotion_achieved_check). Used when submitting post-answers.';

CREATE TABLE IF NOT EXISTS v2_warm_up_task_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS v2_warm_up_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  pool_task_id UUID REFERENCES v2_warm_up_task_pool(id) ON DELETE SET NULL,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);

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

CREATE TABLE IF NOT EXISTS v2_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'warm_up',
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS v2_reports (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  session_v2_id UUID NOT NULL REFERENCES v2_sessions(id) ON DELETE CASCADE,
  recording_id UUID REFERENCES recordings(id) ON DELETE SET NULL,
  report_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

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

-- V2 columns on recordings (if table already existed without them)
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

-- V2 sessions: add columns if table was created minimal (idempotent)
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
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'post_question_ids') THEN ALTER TABLE v2_sessions ADD COLUMN post_question_ids UUID[]; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'warm_up_task_id') THEN ALTER TABLE v2_sessions ADD COLUMN warm_up_task_id UUID REFERENCES v2_warm_up_tasks(id) ON DELETE SET NULL; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'warm_up_task_text') THEN ALTER TABLE v2_sessions ADD COLUMN warm_up_task_text TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'final_task_text') THEN ALTER TABLE v2_sessions ADD COLUMN final_task_text TEXT; END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_sessions' AND column_name = 'post_answers') THEN ALTER TABLE v2_sessions ADD COLUMN post_answers JSONB; END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'v2_sessions_report_id_fkey' AND table_name = 'v2_sessions') THEN
    ALTER TABLE v2_sessions ADD CONSTRAINT v2_sessions_report_id_fkey FOREIGN KEY (report_id) REFERENCES v2_reports(id) ON DELETE SET NULL;
  END IF;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 4: FOCUS TASKS (pool + per-student, same as warm-up). No legacy focus_questions.
-- ============================================================================

CREATE TABLE IF NOT EXISTS v2_focus_task_pool (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_v2_focus_task_pool_order ON v2_focus_task_pool(order_index);
COMMENT ON TABLE v2_focus_task_pool IS 'Global pool of focus tasks. Admin assigns per student (same pattern as warm-up tasks).';

CREATE TABLE IF NOT EXISTS v2_focus_tasks (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  order_index INT NOT NULL DEFAULT 0,
  pool_task_id UUID REFERENCES v2_focus_task_pool(id) ON DELETE SET NULL,
  max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1),
  created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_v2_focus_tasks_user ON v2_focus_tasks(user_id);
COMMENT ON TABLE v2_focus_tasks IS 'Per-student focus tasks. Admin adds/edits on student profile (same UX as warm-up tasks).';

-- Idempotent: add max_performance_score to tables that may have been created without it (DECIMAL 0–1)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_warm_up_tasks' AND column_name = 'max_performance_score') THEN
    ALTER TABLE public.v2_warm_up_tasks ADD COLUMN max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_warm_up_task_pool' AND column_name = 'max_performance_score') THEN
    ALTER TABLE public.v2_warm_up_task_pool ADD COLUMN max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_focus_tasks' AND column_name = 'max_performance_score') THEN
    ALTER TABLE public.v2_focus_tasks ADD COLUMN max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_focus_task_pool' AND column_name = 'max_performance_score') THEN
    ALTER TABLE public.v2_focus_task_pool ADD COLUMN max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_tasks' AND column_name = 'max_performance_score') THEN
    ALTER TABLE public.v2_tasks ADD COLUMN max_performance_score DECIMAL(3,2) DEFAULT 1.00 CHECK (max_performance_score >= 0 AND max_performance_score <= 1);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'v2_student_post_recording_questions' AND column_name = 'code') THEN
    ALTER TABLE public.v2_student_post_recording_questions ADD COLUMN code TEXT;
    COMMENT ON COLUMN public.v2_student_post_recording_questions.code IS 'Copied from pool (e.g. emotion_achieved_check). Used when submitting post-answers.';
  END IF;
END $$;

-- ============================================================================
-- PART 5: INDEXES
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_sessions_user_status ON recording_sessions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_recordings_user ON recordings(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_active_sessions ON recording_sessions(user_id, status) WHERE status NOT IN ('completed', 'abandoned');
CREATE INDEX IF NOT EXISTS idx_performance_scores_recording ON performance_scores(recording_id);
CREATE INDEX IF NOT EXISTS idx_content_exposures_user_type_at ON content_exposures(user_id, content_type, exposed_at DESC);

CREATE INDEX IF NOT EXISTS idx_v2_warm_up_task_pool_order ON v2_warm_up_task_pool(order_index);
CREATE INDEX IF NOT EXISTS idx_v2_warm_up_tasks_user ON v2_warm_up_tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_v2_sessions_user ON v2_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_v2_sessions_status ON v2_sessions(user_id, status) WHERE status != 'completed';
CREATE INDEX IF NOT EXISTS idx_v2_speaker_profiles_updated ON v2_speaker_profiles(updated_at);

-- ============================================================================
-- PART 6: SEED (minimal)
-- ============================================================================

INSERT INTO admin_users (email, role, is_active)
VALUES ('artur@willonski.com', 'super_admin', true)
ON CONFLICT (email) DO UPDATE SET is_active = true;

INSERT INTO pre_recording_questions (question_text, order_index)
SELECT * FROM (VALUES
  ('How are you feeling today?', 1),
  ('What is your main goal for this recording session?', 2),
  ('Are there any specific challenges you want to work on?', 3)
) AS v(question_text, order_index)
WHERE NOT EXISTS (SELECT 1 FROM pre_recording_questions LIMIT 1);

GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated, service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO anon, authenticated, service_role;

-- Reload PostgREST schema cache (run after migrations; wait a few seconds before retrying admin Save if you had PGRST204)
NOTIFY pgrst, 'reload schema';
