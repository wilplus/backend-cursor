-- willab — durable free-intro marker (review must-fix, 2026-07-06).
--
-- The one-time free intro (take-1 coach HUMAN feedback on the user's
-- FIRST-EVER arc) must NOT be derived from surviving v2_sessions rows: the
-- user-facing take delete hard-deletes them, so deleting the first arc's takes
-- would promote the NEXT arc to "first" and re-open the free intro on every
-- subsequent arc (fail-open). This SET-ONCE marker is claimed at the user's
-- first take-1 upload and never moves; a missing column reads as "no intro"
-- (fail-closed — hidden, never open).
ALTER TABLE public.v2_student_details
    ADD COLUMN IF NOT EXISTS free_intro_arc_id UUID NULL;

-- Rollback (manual):
--   ALTER TABLE public.v2_student_details DROP COLUMN IF EXISTS free_intro_arc_id;
