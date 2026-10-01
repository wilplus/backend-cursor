-- 0407 · A practice remembers where it landed (founder 2026-10-01, F7).
--
-- F7, label spec §3.5 item 3: "The endpoint of a practice is its first valid
-- attempt, fixed in advance. Later attempts are stored and never replace it,
-- so when the speaker stops cannot change whether the exercise helped."
--
-- The scorekeeper (exercise-adequacy-label-v2) reads the FIRST valid attempt
-- of at most three. This column is the other side of that rule: the attempt
-- on which the speaker answered Yes or In-between, written when the loop
-- closes, kept for reading only. No scorer reads it: not the adequacy label,
-- not the fair test, not the evaluation. It is descriptive, never a label.
--
-- Idempotent. No env var. Nothing here reaches a speaker (AC-9).

ALTER TABLE public.confident_voice_practice
    ADD COLUMN IF NOT EXISTS landed_attempt_index INTEGER NULL;

COMMENT ON COLUMN public.confident_voice_practice.landed_attempt_index IS
    'F7 (2026-10-01): the attempt the speaker answered Yes or In-between on. '
    'Descriptive only; the scorekeeper reads the first valid attempt instead.';
