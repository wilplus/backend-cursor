-- willab — Paid Audits, presentation length sink (BE chunk A5).
--
-- Persist the min-content gate's measured recording duration onto the
-- session row so the upload response can derive audits_needed
-- (= ceil(minutes / 10), founder D5: MINUTES drive the count, NOT slides).
-- Already stored on the recording row (recordings.duration); this mirrors
-- it onto the session for the length→audits read without a join.
--
-- Idempotent; degrades gracefully (the writer no-ops if the column is
-- missing pre-migration).
ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS presentation_duration_seconds INTEGER NULL;

-- Rollback (manual):
--   ALTER TABLE public.v2_sessions DROP COLUMN IF EXISTS presentation_duration_seconds;
