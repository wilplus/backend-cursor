-- ============================================================================
-- Complete Supabase Schema Setup
-- Run this script in Supabase SQL Editor to set up the entire database schema
-- This script is idempotent - safe to run multiple times
-- ============================================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- CORE TABLES
-- ============================================================================

-- Pre-recording questions (static, global)
CREATE TABLE IF NOT EXISTS pre_recording_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  question_text TEXT NOT NULL,
  order_index INT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Post-recording questions (dynamic selection)
CREATE TABLE IF NOT EXISTS post_recording_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  question_text TEXT NOT NULL,
  question_type TEXT,  -- Can be 'reflective', 'amplifying', 'scale', 'binary', 'free_text'
  created_at TIMESTAMP DEFAULT NOW()
);

-- Add columns to post_recording_questions if they don't exist
DO $$ 
BEGIN
  -- question_set_id
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'post_recording_questions' AND column_name = 'question_set_id'
  ) THEN
    ALTER TABLE public.post_recording_questions ADD COLUMN question_set_id INTEGER;
  END IF;

  -- order_index
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'post_recording_questions' AND column_name = 'order_index'
  ) THEN
    ALTER TABLE public.post_recording_questions ADD COLUMN order_index INTEGER;
  END IF;
END $$;

-- Recording sessions (state tracking)
CREATE TABLE IF NOT EXISTS recording_sessions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  status TEXT CHECK (status IN (
    'pre_questions_pending',
    'recording_ready',
    'recording_uploaded',
    'post_questions_pending',
    'generating_report',
    'completed',
    'abandoned',
    'report_generation_failed'
  )) DEFAULT 'pre_questions_pending',
  recording_id UUID,
  abandon_reason TEXT,
  abandoned_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW(),
  completed_at TIMESTAMP,
  last_activity_at TIMESTAMP DEFAULT NOW()
);

-- Recordings table (create base structure first)
CREATE TABLE IF NOT EXISTS recordings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  session_id UUID,
  audio_url TEXT NOT NULL,
  duration INT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- ============================================================================
-- ADD ALL RECORDINGS TABLE COLUMNS (idempotent)
-- ============================================================================

-- Add columns that might not exist, or alter if they exist with wrong type
DO $$ 
BEGIN
  -- transcription_text (prefer over old 'transcription' column)
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'transcription_text'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN transcription_text TEXT;
    -- Migrate data from old 'transcription' column if it exists
    IF EXISTS (
      SELECT 1 FROM information_schema.columns 
      WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'transcription'
    ) THEN
      UPDATE public.recordings 
      SET transcription_text = transcription 
      WHERE transcription_text IS NULL AND transcription IS NOT NULL;
    END IF;
  END IF;

  -- duration_seconds (NUMERIC to accept decimals)
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'duration_seconds'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN duration_seconds NUMERIC;
    -- Initialize from duration if available
    UPDATE public.recordings 
    SET duration_seconds = duration 
    WHERE duration_seconds IS NULL AND duration IS NOT NULL;
  ELSE
    -- Ensure it's NUMERIC type (not INTEGER)
    IF EXISTS (
      SELECT 1 FROM information_schema.columns 
      WHERE table_schema = 'public' AND table_name = 'recordings' 
      AND column_name = 'duration_seconds' 
      AND data_type = 'integer'
    ) THEN
      ALTER TABLE public.recordings ALTER COLUMN duration_seconds TYPE NUMERIC;
    END IF;
  END IF;

  -- words_per_minute
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'words_per_minute'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN words_per_minute NUMERIC;
  END IF;

  -- filler_words_count
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'filler_words_count'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN filler_words_count JSONB;
  END IF;

  -- classification
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'classification'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN classification TEXT;
  END IF;

  -- confidence (TEXT type, not NUMERIC)
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'confidence'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN confidence TEXT;
  ELSE
    -- If it exists as wrong type, change it
    IF EXISTS (
      SELECT 1 FROM information_schema.columns 
      WHERE table_schema = 'public' AND table_name = 'recordings' 
      AND column_name = 'confidence' 
      AND data_type != 'text'
    ) THEN
      ALTER TABLE public.recordings ALTER COLUMN confidence TYPE TEXT USING confidence::TEXT;
    END IF;
  END IF;

  -- storage_path
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'storage_path'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN storage_path TEXT;
  END IF;

  -- coaching_report
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'coaching_report'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN coaching_report TEXT;
  END IF;

  -- trend_sentence
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'trend_sentence'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN trend_sentence TEXT;
  END IF;

  -- analysis_report (legacy column, keep for backward compatibility)
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'analysis_report'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN analysis_report TEXT;
  END IF;

  -- transcription (legacy column, keep for backward compatibility)
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recordings' AND column_name = 'transcription'
  ) THEN
    ALTER TABLE public.recordings ADD COLUMN transcription TEXT;
  END IF;
END $$;

-- ============================================================================
-- ADD RECORDING_SESSIONS BOOLEAN COLUMNS
-- ============================================================================

DO $$ 
BEGIN
  -- pre_questions_completed
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'pre_questions_completed'
  ) THEN
    ALTER TABLE public.recording_sessions 
    ADD COLUMN pre_questions_completed BOOLEAN DEFAULT FALSE NOT NULL;
  END IF;

  -- recording_completed
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'recording_completed'
  ) THEN
    ALTER TABLE public.recording_sessions 
    ADD COLUMN recording_completed BOOLEAN DEFAULT FALSE NOT NULL;
  END IF;

  -- post_questions_completed
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'post_questions_completed'
  ) THEN
    ALTER TABLE public.recording_sessions 
    ADD COLUMN post_questions_completed BOOLEAN DEFAULT FALSE NOT NULL;
  END IF;

  -- Questionnaire columns
  -- mood
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'mood'
  ) THEN
    ALTER TABLE public.recording_sessions ADD COLUMN mood TEXT;
  END IF;

  -- readiness
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'readiness'
  ) THEN
    ALTER TABLE public.recording_sessions ADD COLUMN readiness INTEGER;
  END IF;

  -- inspiration_needed
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'inspiration_needed'
  ) THEN
    ALTER TABLE public.recording_sessions ADD COLUMN inspiration_needed BOOLEAN;
  END IF;

  -- cursor
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'cursor'
  ) THEN
    ALTER TABLE public.recording_sessions ADD COLUMN cursor NUMERIC;
  END IF;

  -- mode
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_schema = 'public' AND table_name = 'recording_sessions' AND column_name = 'mode'
  ) THEN
    ALTER TABLE public.recording_sessions ADD COLUMN mode TEXT;
  END IF;
END $$;

-- ============================================================================
-- FOREIGN KEY CONSTRAINTS
-- ============================================================================

-- Add FK from sessions to recordings
DO $$ 
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints 
    WHERE constraint_name = 'fk_recording' AND table_name = 'recording_sessions'
  ) THEN
    ALTER TABLE recording_sessions 
    ADD CONSTRAINT fk_recording 
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE SET NULL;
  END IF;
END $$;

-- Add FK from recordings to sessions
DO $$ 
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints 
    WHERE constraint_name = 'fk_session' AND table_name = 'recordings'
  ) THEN
    ALTER TABLE recordings 
    ADD CONSTRAINT fk_session 
    FOREIGN KEY (session_id) REFERENCES recording_sessions(id) ON DELETE CASCADE;
  END IF;
END $$;

-- ============================================================================
-- REMAINING TABLES
-- ============================================================================

-- Pre-recording answers
CREATE TABLE IF NOT EXISTS pre_recording_answers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  recording_session_id UUID REFERENCES recording_sessions(id) ON DELETE CASCADE,
  question_id UUID REFERENCES pre_recording_questions(id),
  answer_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Post-recording answers
CREATE TABLE IF NOT EXISTS post_recording_answers (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  recording_id UUID REFERENCES recordings(id) ON DELETE CASCADE,
  session_id UUID REFERENCES recording_sessions(id) ON DELETE CASCADE,
  question_id UUID REFERENCES post_recording_questions(id),
  answer_text TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- User filler patterns (learning over time)
CREATE TABLE IF NOT EXISTS user_filler_patterns (
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  filler_word TEXT NOT NULL,
  frequency INT DEFAULT 0,
  last_updated TIMESTAMP DEFAULT NOW(),
  PRIMARY KEY (user_id, filler_word)
);

-- Admin notes per user
CREATE TABLE IF NOT EXISTS professional_notes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  notes TEXT,
  updated_at TIMESTAMP DEFAULT NOW()
);

-- Report generation constraints per user
CREATE TABLE IF NOT EXISTS professional_notes_report_tech (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  max_words INT DEFAULT 120,
  custom_instructions TEXT,
  updated_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(user_id)
);

-- User-specific questions
CREATE TABLE IF NOT EXISTS professional_notes_specific_questions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  question_text TEXT NOT NULL,
  question_type TEXT CHECK (question_type IN ('pre', 'post')),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Admin users (for future multi-admin)
CREATE TABLE IF NOT EXISTS admin_users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email TEXT UNIQUE NOT NULL,
  role TEXT CHECK (role IN ('super_admin', 'coach', 'reviewer')),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Admin notifications (email audit log)
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

-- Performance scores (calculated after post-answers submitted)
CREATE TABLE IF NOT EXISTS performance_scores (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  recording_id UUID NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
  performance NUMERIC NOT NULL,  -- Core score (0.0-1.0)
  final_kpi NUMERIC NOT NULL,    -- Final KPI (0.0-1.0)
  resilience_bonus NUMERIC DEFAULT 0,
  awareness_bonus NUMERIC DEFAULT 0,
  progress_bonus NUMERIC DEFAULT 0,
  streak_bonus NUMERIC DEFAULT 0,
  filler_score NUMERIC NOT NULL,
  pacing_score NUMERIC NOT NULL,
  attitude_score NUMERIC NOT NULL,
  reflection_score NUMERIC NOT NULL,
  created_at TIMESTAMP DEFAULT NOW(),
  UNIQUE(recording_id)  -- One score per recording
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_sessions_user_status ON recording_sessions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_recordings_user ON recordings(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_active_sessions ON recording_sessions(user_id, status) 
  WHERE status NOT IN ('completed', 'abandoned');
CREATE INDEX IF NOT EXISTS idx_performance_scores_recording ON performance_scores(recording_id);

-- ============================================================================
-- SEED DATA (only if tables are empty)
-- ============================================================================

-- Seed default pre-recording questions
INSERT INTO pre_recording_questions (question_text, order_index)
SELECT * FROM (VALUES
  ('How are you feeling today?', 1),
  ('What is your main goal for this recording session?', 2),
  ('Are there any specific challenges you want to work on?', 3)
) AS v(question_text, order_index)
WHERE NOT EXISTS (SELECT 1 FROM pre_recording_questions LIMIT 1);

-- Seed initial post-recording questions
INSERT INTO post_recording_questions (question_text, question_type)
SELECT * FROM (VALUES
  ('What was most challenging about this recording?', 'reflective'),
  ('What felt natural or easy during your recording?', 'amplifying'),
  ('How would you rate your confidence level (1-10)?', 'reflective'),
  ('What specific improvement did you notice?', 'amplifying'),
  ('What will you focus on in your next session?', 'reflective')
) AS v(question_text, question_type)
WHERE NOT EXISTS (SELECT 1 FROM post_recording_questions LIMIT 1);

-- Insert super admin (only if not exists)
INSERT INTO admin_users (email, role)
SELECT 'artur@willonski.com', 'super_admin'
WHERE NOT EXISTS (
  SELECT 1 FROM admin_users WHERE email = 'artur@willonski.com'
);

-- ============================================================================
-- VERIFICATION QUERY
-- ============================================================================

-- Verify all recordings table columns exist with correct types
SELECT 
    column_name, 
    data_type, 
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = 'public' 
  AND table_name = 'recordings'
ORDER BY ordinal_position;
