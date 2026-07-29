-- willab — admit 'training_import' as a v2_sessions.source (2026-07-29).
--
-- THE BUG THIS FIXES. The training-import lane marks its sessions
-- source='training_import' — that one value is the whole isolation, and the
-- corpus index (GET /v2/coach/training-imports) filters on it. But
-- add_foundation_discriminators.sql put an enum-style CHECK on the column:
--
--     CHECK (source IN ('interview', 'audit_upload', 'imported'))
--
-- 'training_import' is not in that list, so every import's
-- set_session_source UPDATE violated the constraint (23514). The setter is
-- best-effort — it caught the error, logged, and returned False — and the
-- import never checked the return value. Result: the import SUCCEEDED (the
-- analysis keys on session_id, not source), the pieces and the label queue
-- were written, and the session kept the default source='interview', so the
-- corpus index found nothing and the coach could not reach their own import
-- after a page reload.
--
-- A near miss worth recording: the ISOLATION happened to survive, because
-- every user-facing list and the per-speaker baseline reader filter
-- source='audit_upload', and 'interview' is not that either. Imports stayed
-- out of the speaker's history and out of their acoustic baseline by luck
-- rather than by design. Had the default been 'audit_upload' this would
-- instead have been silent corpus-into-baseline contamination.
--
-- PART 1 widens the CHECK. PART 2 repairs the imports already on disk.
--
-- Replay note (this codebase has been bitten before): the ORIGINAL migration
-- adds the constraint only `IF NOT EXISTS`, so re-running it after this one
-- is a no-op and cannot narrow the list back. This file is the newest
-- definition of v2_sessions_source_check; if the list ever widens again,
-- edit THIS file rather than adding a third.
--
-- Idempotent; safe to re-run.

-- ── Part 1: admit the value ───────────────────────────────────────────
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'v2_sessions_source_check'
    ) THEN
        ALTER TABLE public.v2_sessions
            DROP CONSTRAINT v2_sessions_source_check;
    END IF;
    ALTER TABLE public.v2_sessions
        ADD CONSTRAINT v2_sessions_source_check
        CHECK (source IN ('interview', 'audit_upload', 'imported',
                          'training_import'));
END$$;

-- ── Part 2: repair the imports that were written before the fix ───────
-- Identified by their recording's provenance marker, which DID land
-- (recordings has no CHECK on recording_origin). Scoped hard: only sessions
-- still carrying the default 'interview' are touched, so a re-run cannot
-- reclassify anything else, and a session that was genuinely an interview
-- has no admin_import recording to match on.
UPDATE public.v2_sessions AS s
   SET source = 'training_import'
  FROM public.recordings AS r
 WHERE r.session_v2_id = s.id
   AND r.recording_origin = 'admin_import'
   AND (s.source IS NULL OR s.source = 'interview');
