-- ============================================================================
-- DROP V1 TABLES (run on existing DBs that had the old schema; backup first)
-- ============================================================================
-- After running this, only v2 + recordings + admin_users remain. Run in Supabase SQL Editor.
-- Order respects foreign keys.
-- ============================================================================

-- 1) Tables that reference recording_sessions or each other
DROP TABLE IF EXISTS content_exposures CASCADE;
DROP TABLE IF EXISTS session_command_options CASCADE;
DROP TABLE IF EXISTS admin_notifications CASCADE;
DROP TABLE IF EXISTS post_recording_answers CASCADE;
DROP TABLE IF EXISTS pre_recording_answers CASCADE;
DROP TABLE IF EXISTS performance_scores CASCADE;

-- 2) Break FKs only if tables exist (safe when DB is already v2-only)
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'recordings') THEN
    ALTER TABLE recordings DROP CONSTRAINT IF EXISTS fk_session;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'recording_sessions') THEN
    ALTER TABLE recording_sessions DROP CONSTRAINT IF EXISTS fk_recording;
  END IF;
END $$;

-- 3) Drop v1 session and question tables
DROP TABLE IF EXISTS recording_sessions CASCADE;
DROP TABLE IF EXISTS post_recording_questions CASCADE;
DROP TABLE IF EXISTS pre_recording_questions CASCADE;

-- 4) Admin/professional (v1-only)
DROP TABLE IF EXISTS admin_session_overrides CASCADE;
DROP TABLE IF EXISTS professional_notes_specific_questions CASCADE;
DROP TABLE IF EXISTS professional_notes_report_tech CASCADE;
DROP TABLE IF EXISTS professional_notes CASCADE;

-- 5) Filler patterns (v1)
DROP TABLE IF EXISTS user_filler_patterns CASCADE;

-- Kept: auth.users, admin_users, recordings, all v2_* tables.
NOTIFY pgrst, 'reload schema';
