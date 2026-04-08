-- ============================================================================
-- Enable Row Level Security (RLS) on all public tables exposed via PostgREST
-- Run in Supabase SQL Editor. Idempotent (safe to run multiple times).
--
-- Why: Without RLS, anyone with the anon key could read/write all data via the
-- Data API. Your Flask backend uses SUPABASE_SERVICE_ROLE_KEY, which bypasses
-- RLS, so enabling RLS does not affect the backend — only direct API access.
--
-- Effect: anon and authenticated roles will have no access (no permissive
-- policies). Service role keeps full access. Add policies later if you expose
-- any table to the client (e.g. realtime or direct PostgREST from frontend).
-- ============================================================================

DO $$
DECLARE
  r RECORD;
  tables text[] := ARRAY[
    'admin_users',
    'recordings',
    'v2_metric_definitions',
    'v2_metric_questions',
    'v2_post_recording_questions',
    'v2_post_recording_questions_pool',
    'v2_reports',
    'v2_speaker_profiles',
    'v2_student_overrides',
    'tasks',
    'tasks_pool',
    'v2_deprecated_prompt_tasks_archive',
    'v2_exercises',
    'v2_sessions',
    'v2_focus_question_pool',
    'v2_focus_questions',
    'v2_student_post_recording_questions',
    'v2_student_coaching_memory',
    'v2_universal_questions',
    'v2_metric_questions_pool',
    'recording_sessions',
    'v2_student_details',
    'recording_reviews',
    'recording_review_annotations',
    'student_profile',
    'acoustic_labels',
    'admin_annotation_events',
    'admin_student_send_drafts'
  ];
  t text;
BEGIN
  FOREACH t IN ARRAY tables
  LOOP
    IF EXISTS (SELECT 1 FROM pg_tables WHERE schemaname = 'public' AND tablename = t) THEN
      EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
      RAISE NOTICE 'RLS enabled on public.%', t;
    END IF;
  END LOOP;
END $$;
