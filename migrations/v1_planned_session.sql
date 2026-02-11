-- ============================================================================
-- v1 Planned Session Flow — migrations (idempotent)
-- Run after .taskmaster/docs/schema.sql. Use uuid_generate_v4().
-- ============================================================================

-- 1.1 Extend pre_recording_questions (template table)
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

-- Backfill codes for existing rows
UPDATE public.pre_recording_questions SET code = 'global_seed_01' WHERE code IS NULL AND order_index = 1;
UPDATE public.pre_recording_questions SET code = 'global_seed_02' WHERE code IS NULL AND order_index = 2;
UPDATE public.pre_recording_questions SET code = 'global_seed_03' WHERE code IS NULL AND order_index = 3;
UPDATE public.pre_recording_questions SET code = 'global_seed_' || id::text WHERE code IS NULL;

-- 1.2 Add planning fields to recording_sessions (and structure for rollout)
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

-- 1.3 session_command_options
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

-- 1.4 pre_recording_answers snapshot columns
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

-- 1.5 content_exposures
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

-- 1.6 admin_session_overrides
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

-- 1.7 performance_scores.self_rating_score
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'performance_scores' AND column_name = 'self_rating_score') THEN
    ALTER TABLE public.performance_scores ADD COLUMN self_rating_score NUMERIC NULL;
  END IF;
END $$;

-- ============================================================================
-- 2) Seed 21 theme-specific pre-question templates (upsert on code)
-- ============================================================================
INSERT INTO public.pre_recording_questions (code, theme_code, question_type, question_text, order_index, active)
VALUES
  ('presence_grounding_1', 'presence_grounding', 'scale_1_5', 'How grounded do you feel right now? (1-5)', 1, true),
  ('presence_grounding_2', 'presence_grounding', 'binary_yes_no', 'Do you feel present in your body?', 2, true),
  ('presence_grounding_3', 'presence_grounding', 'text_short', 'What would help you feel more present before speaking?', 3, true),
  ('clarity_simplicity_1', 'clarity_simplicity', 'scale_1_5', 'How clear is your mind right now? (1-5)', 1, true),
  ('clarity_simplicity_2', 'clarity_simplicity', 'binary_yes_no', 'Do you have one main idea you want to share?', 2, true),
  ('clarity_simplicity_3', 'clarity_simplicity', 'text_short', 'In one sentence, what do you want to say?', 3, true),
  ('pacing_rhythm_1', 'pacing_rhythm', 'scale_1_5', 'How comfortable is your usual speaking pace? (1-5)', 1, true),
  ('pacing_rhythm_2', 'pacing_rhythm', 'binary_choice', 'Today do you prefer: Personal or Neutral?', 2, true),
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
  ('story_narrative_2', 'story_narrative', 'binary_choice', 'Do you prefer: Personal or Neutral?', 2, true),
  ('story_narrative_3', 'story_narrative', 'text_short', 'What story or example could you share?', 3, true)
ON CONFLICT (code) DO UPDATE SET
  theme_code = EXCLUDED.theme_code,
  question_type = EXCLUDED.question_type,
  question_text = EXCLUDED.question_text,
  order_index = EXCLUDED.order_index,
  active = EXCLUDED.active,
  updated_at = NOW();
