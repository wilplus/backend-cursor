-- a_person_keeps_their_join_questions (the column the join questions are kept
-- in; N487 and N503, built in #1739 and #1742)
--
-- One addition to a person's profile (people_profiles,
-- a_person_has_a_profile.sql):
--
--   join_questions   The questions a person who shares what they know sets
--                    in Will's chat, asked of everyone who joins through
--                    their link (N487, N503): {"v", "plan", "lines",
--                    "updated_at"}, written and read only by
--                    services/join_questions.py. NULL means none set; a set
--                    with no lines means the person answered the setup and
--                    chose none. It goes with the profile row, so the
--                    account purge takes it with the row.
--
-- Why now: services/join_questions.py was merged reading this column, but no
-- migration made it (its docstring named 0511, which is the dump screen's).
-- Without it every read fails quietly, saving the questions fails, and
-- nobody who joins through a link or the website widget (N530) is asked
-- them. If the column was added in production by hand, this is a no-op
-- there and makes a fresh database match.
--
-- Profiles are read and written by the backend (service role) only; the
-- table's grants (a_person_has_a_profile.sql) cover the new column. No
-- environment variable is needed.
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS, nullable, no default,
-- so no row is rewritten; nothing is dropped and no row is written or
-- removed. One transaction.
--
-- Rollback (a new forward migration): leave the column; dropping it is a
-- separate, previewed retention operation.

BEGIN;

ALTER TABLE public.people_profiles ADD COLUMN IF NOT EXISTS join_questions JSONB;

COMMIT;
