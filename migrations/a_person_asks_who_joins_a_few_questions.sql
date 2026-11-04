-- a_person_asks_who_joins_a_few_questions (the questions a person who shares
-- sets for everyone who joins through their link; founder, the Claude Code
-- chat, 4 November 2026, N487, its words signed in N491, N496 and N502)
--
-- A person who shares what they know sets, in Will's chat, a few practical
-- questions; whoever joins through their link is asked them in their chat
-- with that person, one at a time, answered by tapping (N487 item 4). The
-- questions are what a person says to the people they chat with, so they
-- live on that person's profile row (0507).
--
--   people_profiles.join_questions   One JSON object, or NULL. NULL: the
--                     person has not been through Will's setup yet (N503),
--                     and nobody who joins them is asked anything. An object
--                     with no lines: they went through it and set none (the
--                     joiner sees only the line at the top, N496 item 2).
--                     Its shape, written and read by services/join_questions.py
--                     (and services/join_setup.py, Will's setup):
--                     {"v": 1, "plan": "week" | "month" | "quarter" | null,
--                      "lines": [{"q": "...", "answers": ["...", ...],
--                                 "multi": bool, "kind": "say"|"hurry"|"date"
--                                 |"languages"|"tap"}, ...],
--                      "updated_at": "..."}.
--                     The CHECKs keep it an object, and its JSON text
--                     (join_questions::text) at most 8192 bytes: a backstop
--                     to the backend's own limits (8 lines, 160 characters
--                     a question, 2 to 6 answers of 40), not its storage size.
--
-- Deleted with the account, as the rest of the row: the purge registry
-- (services/data_purge_registry.py) already deletes people_profiles by
-- user_id, and ON DELETE CASCADE from auth.users does the same.
-- Read and written by the backend (service role) only, as the table already
-- is; no grant changes. No environment variable needed.
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS; each CHECK added only
-- when missing, and validated whenever it is there but not yet validated
-- (DO block), so it can run twice, and a constraint left NOT VALID by any
-- earlier run is validated by the next. Nothing is dropped; no row is
-- written, rewritten or removed (the column starts NULL everywhere).
-- Locks: ACCESS EXCLUSIVE on people_profiles for the ADD COLUMN (no default,
-- so no rewrite) and the two ADD CONSTRAINT ... NOT VALID, SHARE UPDATE
-- EXCLUSIVE for the VALIDATEs; one transaction, so they are held until
-- COMMIT, a moment on a small table (one row per person with a profile).
--
-- Rollback (a new forward migration): leave the column; NULL means no
-- questions, which is how the app behaves without it.

BEGIN;

ALTER TABLE public.people_profiles
    ADD COLUMN IF NOT EXISTS join_questions JSONB;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'people_profiles_join_questions_object'
          AND conrelid = 'public.people_profiles'::regclass
    ) THEN
        ALTER TABLE public.people_profiles
            ADD CONSTRAINT people_profiles_join_questions_object
            CHECK (join_questions IS NULL OR jsonb_typeof(join_questions) = 'object')
            NOT VALID;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'people_profiles_join_questions_object'
          AND conrelid = 'public.people_profiles'::regclass
          AND NOT convalidated
    ) THEN
        ALTER TABLE public.people_profiles
            VALIDATE CONSTRAINT people_profiles_join_questions_object;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'people_profiles_join_questions_size'
          AND conrelid = 'public.people_profiles'::regclass
    ) THEN
        ALTER TABLE public.people_profiles
            ADD CONSTRAINT people_profiles_join_questions_size
            CHECK (join_questions IS NULL OR octet_length(join_questions::text) <= 8192)
            NOT VALID;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'people_profiles_join_questions_size'
          AND conrelid = 'public.people_profiles'::regclass
          AND NOT convalidated
    ) THEN
        ALTER TABLE public.people_profiles
            VALIDATE CONSTRAINT people_profiles_join_questions_size;
    END IF;
END
$$;

COMMENT ON COLUMN public.people_profiles.join_questions IS
    'N487: the questions this person sets for everyone who joins through their link; NULL until they have been through Will''s setup (N503), an object with no lines when they set none. Written by services/join_questions.py.';

COMMIT;
