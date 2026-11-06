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
-- A CHECK keeps the value an object or NULL (the shape the code writes). It
-- is added only if it is not there yet, so the file can run twice; the
-- column is new and NULL in every row, so checking it reads nothing to fail.
--
-- lock_timeout: ADD COLUMN takes a brief ACCESS EXCLUSIVE lock; on a live
-- table it gives up after 5 seconds rather than queue behind a long
-- transaction and hold up every profile read. A timeout fails the file
-- whole (one transaction) and the next release runs it again.
--
-- NOTIFY pgrst: the backend reaches this table through PostgREST, whose
-- schema cache would otherwise miss the column until its next reload, and
-- saving would keep failing. Delivered at COMMIT.
--
-- Reviewed outside (Grok, 6 November 2026): approved with changes, the
-- lock_timeout, the CHECK and the schema reload, made here; the CHECK is
-- guarded so a second run does not fail on it, and added in one step, as
-- NOT VALID then VALIDATE in the same transaction gains nothing.
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS, nullable, no default,
-- so no row is rewritten; nothing is dropped and no row is written or
-- removed. One transaction.
--
-- Rollback (a new forward migration): leave the column; dropping it is a
-- separate, previewed retention operation.

BEGIN;

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.people_profiles ADD COLUMN IF NOT EXISTS join_questions JSONB;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.people_profiles'::regclass
          AND conname = 'people_profiles_join_questions_is_object'
    ) THEN
        ALTER TABLE public.people_profiles
            ADD CONSTRAINT people_profiles_join_questions_is_object
            CHECK (join_questions IS NULL OR jsonb_typeof(join_questions) = 'object');
    END IF;
END
$$;

NOTIFY pgrst, 'reload schema';

COMMIT;
