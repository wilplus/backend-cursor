-- =============================================================================
-- Homework session step: canonical status value `task` (no `warm_up` in DB)
-- =============================================================================
-- Run after deploy prep (idempotent). Safe to run multiple times.
-- Pair with backend that inserts new sessions with status = 'task'.
-- =============================================================================

BEGIN;

UPDATE public.v2_sessions
SET status = 'task'
WHERE status = 'warm_up';

NOTIFY pgrst, 'reload schema';

COMMIT;
