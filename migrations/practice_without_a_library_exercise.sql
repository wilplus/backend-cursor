-- 0400 · a practice without a library exercise (founder lock 2026-09-30, B6, D1)
--
-- WHY. Practise is the default follow-up for every judgement below
-- In-between (D1): the exercise where one is matched, else the rewrite as
-- the passage to say, else the plain moment said again. Until today a
-- practice row needed a library exercise (`exercise_id NOT NULL`, a foreign
-- key into diagnostic_exercise), so a moment with nothing matched could not
-- be practised at all.
--
-- WHAT. `exercise_id` may be NULL, and `kind` names what the passage is:
-- 'exercise' (a library exercise, every existing row), 'rewrite' (the
-- Manager's clearer version) or 'plain' (the moment's own words). Nothing is
-- dropped but a NOT NULL; no row changes. The one-per-moment constraint
-- (0396, UNIQUE (take_session_id, snippet_id)) still keys the practice, so
-- a NULL exercise_id in the older UNIQUE (snippet_id, exercise_id) — which
-- never fires on NULL — cannot let a second practice through. Idempotent.
-- No env var: the code reads `kind` with a default of 'exercise'.
--
-- Rollback (a new forward migration, never an edit of this file):
--   ALTER TABLE public.confident_voice_practice
--       DROP CONSTRAINT IF EXISTS cvp_kind_check;
--   ALTER TABLE public.confident_voice_practice DROP COLUMN IF EXISTS kind;
--   -- and re-add NOT NULL on exercise_id only once no row has a NULL there.

BEGIN;

ALTER TABLE public.confident_voice_practice
    ALTER COLUMN exercise_id DROP NOT NULL;

ALTER TABLE public.confident_voice_practice
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'exercise';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conname = 'cvp_kind_check'
           AND conrelid = 'public.confident_voice_practice'::regclass
    ) THEN
        ALTER TABLE public.confident_voice_practice
            ADD CONSTRAINT cvp_kind_check
            CHECK (kind IN ('exercise', 'rewrite', 'plain'));
    END IF;
END $$;

COMMIT;
