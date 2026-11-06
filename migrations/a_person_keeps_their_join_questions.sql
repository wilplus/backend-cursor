-- a_person_keeps_their_join_questions (the questions asked when someone
-- joins, N487, N503; found missing while building N530, 6 November 2026)
--
-- One addition to a person's profile (a_person_has_a_profile, 0507):
--
--   people_profiles.join_questions
--                  The questions a person set in Will's chat for whoever
--                  joins through their link, or opens their chat on a
--                  website (N530): {"v": 1, "plan", "lines": [{q, answers,
--                  multi, kind}], "updated_at"} (services/join_questions.py).
--                  NULL until they set them.
--
-- services/join_questions.py has read and written this column since N487,
-- but no migration made it: on a database without it, saving the questions
-- failed quietly and nobody who joined was asked them. This makes the
-- column every database's.
--
-- The profile row is the backend's alone (service role only, as 0507); no
-- grant changes. It goes with the account, as the row does (the purge
-- registry's people_profiles). No environment variable is needed.
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS, so a database where
-- the column was already added by hand is left as it is. Nothing is
-- dropped and no row is written, rewritten or removed. One transaction.
--
-- Rollback (a new forward migration): leave it; dropping it is a separate,
-- previewed retention operation.

BEGIN;

ALTER TABLE public.people_profiles
    ADD COLUMN IF NOT EXISTS join_questions JSONB;

COMMIT;
