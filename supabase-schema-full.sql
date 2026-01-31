-- ============================================================================
-- FULL SUPABASE SCHEMA — single runnable script (idempotent)
-- Order: (1) Base schema  (2) v1 planned session  (3) Solo/extras  (4) Seed
-- Use uuid_generate_v4() throughout. Run in Supabase SQL Editor.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- PART 1: BASE SCHEMA
-- ============================================================================

CREATE TABLE IF NOT EXISTS pre_recording_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  question_text TEXT NOT NULL,
  order_index INT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

INSERT INTO pre_recording_questions (question_text, order_index)
SELECT * FROM (VALUES
  ('How are you feeling today?', 1),
  ('What is your main goal for this recording session?', 2),
  ('Are there any specific challenges you want to work on?', 3)
) AS v(question_text, order_index)
WHERE NOT EXISTS (SELECT 1 FROM pre_recording_questions LIMIT 1);

CREATE TABLE IF NOT EXISTS post_recording_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  question_text TEXT NOT NULL,
  question_type TEXT,
  created_at TIMESTAMP DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'post_recording_questions' AND column_name = 'question_set_id') THEN
    ALTER TABLE public.post_recording_questions ADD COLUMN question_set_id INTEGER;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'post_recording_questions' AND column_name = 'order_index') THEN
    ALTER TABLE public.post_recording_questions ADD COLUMN order_index INTEGER;
  END IF;
END $$;

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
  last_activity_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS recordings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id UUID,
  audio_url TEXT NOT NULL,
  duration INT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'transcription_text') THEN
    ALTER TABLE public.recordings ADD COLUMN transcription_text TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'duration_seconds') THEN
    ALTER TABLE public.recordings ADD COLUMN duration_seconds NUMERIC;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'words_per_minute') THEN
    ALTER TABLE public.recordings ADD COLUMN words_per_minute NUMERIC;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'filler_words_count') THEN
    ALTER TABLE public.recordings ADD COLUMN filler_words_count JSONB;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'classification') THEN
    ALTER TABLE public.recordings ADD COLUMN classification TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'confidence') THEN
    ALTER TABLE public.recordings ADD COLUMN confidence TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'storage_path') THEN
    ALTER TABLE public.recordings ADD COLUMN storage_path TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'coaching_report') THEN
    ALTER TABLE public.recordings ADD COLUMN coaching_report TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'trend_sentence') THEN
    ALTER TABLE public.recordings ADD COLUMN trend_sentence TEXT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'pre_questions_completed') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN pre_questions_completed BOOLEAN DEFAULT FALSE NOT NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'recording_completed') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN recording_completed BOOLEAN DEFAULT FALSE NOT NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'post_questions_completed') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN post_questions_completed BOOLEAN DEFAULT FALSE NOT NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'mood') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN mood TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'readiness') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN readiness INTEGER;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'inspiration_needed') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN inspiration_needed BOOLEAN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'cursor') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN cursor NUMERIC;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'mode') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN mode TEXT;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'fk_recording' AND table_name = 'recording_sessions') THEN
    ALTER TABLE recording_sessions ADD CONSTRAINT fk_recording FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE SET NULL;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name = 'fk_session' AND table_name = 'recordings') THEN
    ALTER TABLE recordings ADD CONSTRAINT fk_session FOREIGN KEY (session_id) REFERENCES recording_sessions(id) ON DELETE CASCADE;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS pre_recording_answers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  recording_session_id UUID REFERENCES recording_sessions(id) ON DELETE CASCADE,
  question_id UUID REFERENCES pre_recording_questions(id),
  answer_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS post_recording_answers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  recording_id UUID REFERENCES recordings(id) ON DELETE CASCADE,
  session_id UUID REFERENCES recording_sessions(id) ON DELETE CASCADE,
  question_id UUID REFERENCES post_recording_questions(id),
  answer_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_filler_patterns (
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  filler_word TEXT NOT NULL,
  frequency INT DEFAULT 0,
  last_updated TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (user_id, filler_word)
);

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
  UNIQUE(recording_id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_status ON recording_sessions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_recordings_user ON recordings(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_active_sessions ON recording_sessions(user_id, status) WHERE status NOT IN ('completed', 'abandoned');
CREATE INDEX IF NOT EXISTS idx_performance_scores_recording ON performance_scores(recording_id);

-- ============================================================================
-- PART 2: v1 PLANNED SESSION (extends base)
-- ============================================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pre_recording_questions' AND column_name = 'code') THEN
    ALTER TABLE public.pre_recording_questions ADD COLUMN code TEXT UNIQUE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pre_recording_questions' AND column_name = 'theme_code') THEN
    ALTER TABLE public.pre_recording_questions ADD COLUMN theme_code TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pre_recording_questions' AND column_name = 'question_type') THEN
    ALTER TABLE public.pre_recording_questions ADD COLUMN question_type TEXT NOT NULL DEFAULT 'text_short';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pre_recording_questions' AND column_name = 'active') THEN
    ALTER TABLE public.pre_recording_questions ADD COLUMN active BOOLEAN NOT NULL DEFAULT TRUE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pre_recording_questions' AND column_name = 'updated_at') THEN
    ALTER TABLE public.pre_recording_questions ADD COLUMN updated_at TIMESTAMP DEFAULT NOW();
  END IF;
END $$;

UPDATE public.pre_recording_questions SET code = 'global_seed_01' WHERE code IS NULL AND order_index = 1;
UPDATE public.pre_recording_questions SET code = 'global_seed_02' WHERE code IS NULL AND order_index = 2;
UPDATE public.pre_recording_questions SET code = 'global_seed_03' WHERE code IS NULL AND order_index = 3;
UPDATE public.pre_recording_questions SET code = 'global_seed_' || id::text WHERE code IS NULL;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'structure') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN structure TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'theme_recommended_code') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN theme_recommended_code TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'theme_recommended_reason') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN theme_recommended_reason TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'theme_chosen_code') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN theme_chosen_code TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'theme_chosen_source') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN theme_chosen_source TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'planned_pre_question_id') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN planned_pre_question_id UUID REFERENCES pre_recording_questions(id);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'planned_pre_question_text_snapshot') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN planned_pre_question_text_snapshot TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'planned_pre_question_type_snapshot') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN planned_pre_question_type_snapshot TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'planned_pre_question_code_snapshot') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN planned_pre_question_code_snapshot TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'selected_command_option_id') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN selected_command_option_id TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'selected_intent') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN selected_intent TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'selected_tier') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN selected_tier INTEGER;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'selected_mode') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN selected_mode TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'selected_prompt_text_snapshot') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN selected_prompt_text_snapshot TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'post_question_set_id') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN post_question_set_id INTEGER;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'admin_override_id_applied') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN admin_override_id_applied UUID;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'admin_override_consumed_at') THEN
    ALTER TABLE public.recording_sessions ADD COLUMN admin_override_consumed_at TIMESTAMP;
  END IF;
END $$;

-- v1: recordings must store command_option_id from POST /recordings/upload (required form field "A"|"B"|"C")
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'command_option_id') THEN
    ALTER TABLE public.recordings ADD COLUMN command_option_id TEXT;
  END IF;
END $$;

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

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pre_recording_answers' AND column_name = 'question_text_snapshot') THEN
    ALTER TABLE public.pre_recording_answers ADD COLUMN question_text_snapshot TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pre_recording_answers' AND column_name = 'question_type_snapshot') THEN
    ALTER TABLE public.pre_recording_answers ADD COLUMN question_type_snapshot TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pre_recording_answers' AND column_name = 'question_code_snapshot') THEN
    ALTER TABLE public.pre_recording_answers ADD COLUMN question_code_snapshot TEXT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'pre_recording_answers' AND column_name = 'order_index_snapshot') THEN
    ALTER TABLE public.pre_recording_answers ADD COLUMN order_index_snapshot INTEGER;
  END IF;
END $$;

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
CREATE INDEX IF NOT EXISTS idx_content_exposures_user_type_at ON content_exposures(user_id, content_type, exposed_at DESC);

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

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'performance_scores' AND column_name = 'self_rating_score') THEN
    ALTER TABLE public.performance_scores ADD COLUMN self_rating_score NUMERIC NULL;
  END IF;
END $$;

-- v1 seed: 21 theme pre-question templates (requires code column + UNIQUE)
INSERT INTO public.pre_recording_questions (code, theme_code, question_type, question_text, order_index, active)
VALUES
  ('presence_grounding_1', 'presence_grounding', 'scale_1_5', 'How grounded do you feel right now? (1-5)', 1, true),
  ('presence_grounding_2', 'presence_grounding', 'binary_yes_no', 'Do you feel present in your body?', 2, true),
  ('presence_grounding_3', 'presence_grounding', 'text_short', 'What would help you feel more present before speaking?', 3, true),
  ('clarity_simplicity_1', 'clarity_simplicity', 'scale_1_5', 'How clear is your mind right now? (1-5)', 1, true),
  ('clarity_simplicity_2', 'clarity_simplicity', 'binary_yes_no', 'Do you have one main idea you want to share?', 2, true),
  ('clarity_simplicity_3', 'clarity_simplicity', 'text_short', 'In one sentence, what do you want to say?', 3, true),
  ('pacing_rhythm_1', 'pacing_rhythm', 'scale_1_5', 'How comfortable is your usual speaking pace? (1-5)', 1, true),
  ('pacing_rhythm_2', 'pacing_rhythm', 'binary_choice', 'Today do you prefer: Slower and clear, or Natural pace?', 2, true),
  ('pacing_rhythm_3', 'pacing_rhythm', 'text_short', 'What pace do you want to aim for?', 3, true),
  ('energy_conviction_1', 'energy_conviction', 'scale_1_5', 'How much energy do you have to speak? (1-5)', 1, true),
  ('energy_conviction_2', 'energy_conviction', 'binary_yes_no', 'Do you feel ready to speak with conviction?', 2, true),
  ('energy_conviction_3', 'energy_conviction', 'text_short', 'What topic could you speak about with conviction?', 3, true),
  ('confidence_comfort_1', 'confidence_comfort', 'scale_1_5', 'How confident do you feel about speaking now? (1-5)', 1, true),
  ('confidence_comfort_2', 'confidence_comfort', 'binary_yes_no', 'Do you feel comfortable being heard?', 2, true),
  ('confidence_comfort_3', 'confidence_comfort', 'text_short', 'What would make you feel more confident?', 3, true),
  ('structure_organization_1', 'structure_organization', 'scale_1_5', 'How organized do you feel? (1-5)', 1, true),
  ('structure_organization_2', 'structure_organization', 'binary_yes_no', 'Do you have a clear structure in mind?', 2, true),
  ('structure_organization_3', 'structure_organization', 'text_short', 'What is the one point you want to make?', 3, true),
  ('story_narrative_1', 'story_narrative', 'scale_1_5', 'How ready are you to tell a short story? (1-5)', 1, true),
  ('story_narrative_2', 'story_narrative', 'binary_choice', 'Prefer: Personal story or Neutral example?', 2, true),
  ('story_narrative_3', 'story_narrative', 'text_short', 'What story or example could you share?', 3, true)
ON CONFLICT (code) DO UPDATE SET
  theme_code = EXCLUDED.theme_code,
  question_type = EXCLUDED.question_type,
  question_text = EXCLUDED.question_text,
  order_index = EXCLUDED.order_index,
  active = EXCLUDED.active,
  updated_at = NOW();

-- ============================================================================
-- PART 3: SOLO / EXTRAS (recordings metrics, performance_scores extras, structure CHECK)
-- ============================================================================

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'voice_stability') THEN
    ALTER TABLE public.recordings ADD COLUMN voice_stability NUMERIC;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'energy_score') THEN
    ALTER TABLE public.recordings ADD COLUMN energy_score NUMERIC;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'pacing_score') THEN
    ALTER TABLE public.recordings ADD COLUMN pacing_score NUMERIC;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'performance_scores' AND column_name = 'voice_stability_score') THEN
    ALTER TABLE public.performance_scores ADD COLUMN voice_stability_score NUMERIC DEFAULT 0;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'performance_scores' AND column_name = 'energy_score') THEN
    ALTER TABLE public.performance_scores ADD COLUMN energy_score NUMERIC DEFAULT 0;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'performance_scores' AND column_name = 'awareness_score') THEN
    ALTER TABLE public.performance_scores ADD COLUMN awareness_score NUMERIC DEFAULT 0;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'performance_scores' AND column_name = 'mood_multiplier') THEN
    ALTER TABLE public.performance_scores ADD COLUMN mood_multiplier NUMERIC;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'performance_scores' AND column_name = 'readiness_score') THEN
    ALTER TABLE public.performance_scores ADD COLUMN readiness_score NUMERIC;
  END IF;
END $$;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'post_recording_answers' AND column_name = 'reflection_text') THEN
    ALTER TABLE public.post_recording_answers ADD COLUMN reflection_text TEXT;
  END IF;
END $$;

-- Optional: add CHECK on structure if column exists (guided/open)
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'structure') THEN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'public.recording_sessions'::regclass AND conname = 'chk_structure') THEN
      ALTER TABLE public.recording_sessions ADD CONSTRAINT chk_structure CHECK (structure IS NULL OR structure IN ('guided', 'open'));
    END IF;
  END IF;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================================
-- PART 4: SEED (single admin)
-- ============================================================================

INSERT INTO admin_users (email, role, is_active)
VALUES ('artur@willonski.com', 'super_admin', true)
ON CONFLICT (email) DO UPDATE SET is_active = true;
