-- add_pet_phrase_to_v2_sessions (0477)
--
-- WHY. The founder (2026-10-19, Linear WIL-26, decision tree
-- https://claude.ai/artifact/QpvRaEfH4bRGM9E85dtmYF: "add one new, empty
-- column to each Take"). A phrase a speaker uses three or more times in one
-- Take ("at the end of the day") gets one AI-written alternative. The
-- analysis job writes it (services/pet_phrase.py, inside the Take's
-- provider-authorization scope); the feedback read offers it in the shared
-- wording slot. The suggestions table holds one row per moment, so the
-- alternative needs its own place.
--
-- WHAT. One nullable JSONB column on the take session:
--   {"version", "phrase", "alternative", "model", "generated_at"}.
-- NULL for every existing Take and for every Take while PET_PHRASE_ENABLED
-- is off (the default).
--
-- ERASURE. Nothing to add: a speaker's purge empties every nullable
-- v2_sessions column that is not on the keep-list
-- (a_take_keeps_an_empty_receipt, 0379), and this column is not on it.
--
-- DEPLOY. No environment variable is needed for this to run. The code that
-- writes the column ships in the same change and is off by default.
--
-- Idempotent + additive: safe to re-run, drops nothing.

ALTER TABLE public.v2_sessions
    ADD COLUMN IF NOT EXISTS pet_phrase JSONB;

COMMENT ON COLUMN public.v2_sessions.pet_phrase IS
    'WIL-26 pet phrase: the phrase used 3+ times in this Take and one AI '
    'alternative. Written by services/pet_phrase.py. Speaker text: erased '
    'by the purge with the other nullable columns.';
