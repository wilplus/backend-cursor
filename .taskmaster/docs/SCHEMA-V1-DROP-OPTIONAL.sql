-- ============================================================================
-- OPTIONAL: Drop v1-only tables (run ONLY after removing all v1 code and backing up)
-- ============================================================================
-- Use this only if the app is homework-only (v2) and you have removed or disabled:
--   routes/session.py (v1 session), routes/recordings.py (v1 flow), routes/questions.py (v1),
--   v1 paths in routes/user.py, routes/admin.py (or refactored admin to v2 only).
-- Back up the database before running. Order respects foreign keys.
-- ============================================================================

-- 1) Tables that reference recording_sessions or each other (drop first)
DROP TABLE IF EXISTS content_exposures CASCADE;
DROP TABLE IF EXISTS session_command_options CASCADE;
DROP TABLE IF EXISTS admin_notifications CASCADE;
DROP TABLE IF EXISTS post_recording_answers CASCADE;
DROP TABLE IF EXISTS pre_recording_answers CASCADE;
DROP TABLE IF EXISTS performance_scores CASCADE;

-- 2) Break FKs: recordings.session_id -> recording_sessions; recording_sessions.recording_id -> recordings
ALTER TABLE recordings DROP CONSTRAINT IF EXISTS fk_session;
ALTER TABLE recording_sessions DROP CONSTRAINT IF EXISTS fk_recording;

-- 3) Drop v1 session and question tables
DROP TABLE IF EXISTS recording_sessions CASCADE;
DROP TABLE IF EXISTS post_recording_questions CASCADE;
DROP TABLE IF EXISTS pre_recording_questions CASCADE;

-- 4) Admin/professional (v1-only; keep admin_users if you use it for admin auth)
DROP TABLE IF EXISTS admin_session_overrides CASCADE;
DROP TABLE IF EXISTS professional_notes_specific_questions CASCADE;
DROP TABLE IF EXISTS professional_notes_report_tech CASCADE;
DROP TABLE IF EXISTS professional_notes CASCADE;

-- 5) Filler patterns (v1 analytics)
DROP TABLE IF EXISTS user_filler_patterns CASCADE;

-- Kept: auth.users, admin_users, recordings, all v2_* tables (v2_sessions, v2_reports, v2_tasks, etc.)
