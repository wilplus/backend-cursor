-- ============================================================================
-- CLEANUP: Remove unused / stale session data (paste into Supabase SQL Editor)
-- ============================================================================
-- This script:
--   1. Deletes incomplete v2_sessions (homework) older than 1 hour.
--      - v2_reports are removed automatically (ON DELETE CASCADE).
--      - recordings.session_v2_id is set to NULL automatically (ON DELETE SET NULL).
--   2. Deletes incomplete recording_sessions (v1/legacy) older than 10 days,
--      and their recordings (and related rows via your schema).
--
-- Optional: Run the "DRY RUN" block first to see what would be deleted, then
-- run the "ACTUAL DELETES" block.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- DRY RUN (optional): see what would be deleted (no changes)
-- ----------------------------------------------------------------------------
-- Uncomment and run first if you want to inspect:

/*
SELECT 'v2_sessions (incomplete, >1h)' AS what, id, user_id, status, created_at
FROM v2_sessions
WHERE status != 'completed'
  AND created_at < (NOW() AT TIME ZONE 'UTC' - INTERVAL '1 hour');

SELECT 'recording_sessions (incomplete, >10d)' AS what, id, user_id, created_at
FROM recording_sessions
WHERE completed_at IS NULL
  AND created_at < (NOW() AT TIME ZONE 'UTC' - INTERVAL '10 days');
*/

-- ----------------------------------------------------------------------------
-- ACTUAL DELETES
-- ----------------------------------------------------------------------------

BEGIN;

-- 1) Incomplete v2_sessions (homework) older than 1 hour
--    CASCADE deletes v2_reports; recordings.session_v2_id set to NULL
DELETE FROM v2_sessions
WHERE status != 'completed'
  AND created_at < (NOW() AT TIME ZONE 'UTC' - INTERVAL '1 hour');

-- 2) v1/legacy: recordings for incomplete recording_sessions older than 10 days
--    (Do this before deleting recording_sessions so FK doesn’t block.)
DELETE FROM recordings
WHERE session_id IN (
  SELECT id FROM recording_sessions
  WHERE completed_at IS NULL
    AND created_at < (NOW() AT TIME ZONE 'UTC' - INTERVAL '10 days')
);

-- 3) Incomplete recording_sessions (v1) older than 10 days
--    Child tables (pre_recording_answers, post_recording_answers,
--    session_command_options, content_exposures) are often ON DELETE CASCADE;
--    if you get an FK violation, delete from those tables first where
--    session_id IN (same subquery).
DELETE FROM recording_sessions
WHERE completed_at IS NULL
  AND created_at < (NOW() AT TIME ZONE 'UTC' - INTERVAL '10 days');

COMMIT;

-- ============================================================================
-- Done. To re-run later (e.g. weekly for v1, or rely on backend/cron for v2),
-- run this script again.
-- ============================================================================
