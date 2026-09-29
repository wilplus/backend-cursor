-- 0390 · one practice per moment (founder 2026-09-29)
--
-- WHY. "They can carry as many exercises as bookmark indicates." Until today
-- a Take carried one exercise, on the item V3 marked for it, and this table
-- pinned that with UNIQUE (take_session_id): a second moment on the same Take
-- could never open its own practice. Every Confident Voice bookmark may now
-- carry the exercise matched to its own clip, so the unit becomes the moment.
--
-- WHAT. The one-per-Take constraint goes; one-per-moment takes its place.
-- Every existing row satisfies the new constraint (each Take had at most one
-- row, so each (Take, moment) has at most one). Nothing is dropped but a
-- constraint; no column, no row, no table. Idempotent. No env var.
--
-- Rollback (a new forward migration, never an edit of this file):
--   ALTER TABLE public.confident_voice_practice
--       DROP CONSTRAINT IF EXISTS confident_voice_practice_one_per_moment;
--   -- and re-add confident_voice_practice_one_per_take only once every Take
--   -- again has at most one row.

BEGIN;

ALTER TABLE public.confident_voice_practice
    DROP CONSTRAINT IF EXISTS confident_voice_practice_one_per_take;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'confident_voice_practice_one_per_moment'
           AND conrelid = 'public.confident_voice_practice'::regclass
    ) THEN
        ALTER TABLE public.confident_voice_practice
            ADD CONSTRAINT confident_voice_practice_one_per_moment
            UNIQUE (take_session_id, snippet_id);
    END IF;
END $$;

COMMIT;
