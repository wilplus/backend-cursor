-- a_person_asks_who_joins_a_few_questions (the questions a person who shares
-- sets for everyone who joins through their link; founder, the Claude Code
-- chat, 4 November 2026, N487, its words signed in N491, N496 and N498)
--
-- A person who shares what they know sets, in Will's chat, a few practical
-- questions; whoever joins through their link is asked them in their chat
-- with that person, one at a time, answered by tapping (N487 item 4). The
-- questions are what a person says to the people they chat with, so they
-- live on that person's profile row (0507).
--
--   people_profiles.join_questions   One JSON object, or NULL (no questions:
--                     the joiner sees only the line at the top, N496 item 2).
--                     Its shape, written and read by services/join_questions.py:
--                     {"v": 1, "plan": {"days": 7} | {"months": 1|3} | null,
--                      "lines": [{"q": "...", "answers": ["...", ...],
--                                 "multi": bool, "kind": "say"|"hurry"|"date"
--                                 |"languages"|"tap"}, ...],
--                      "updated_at": "..."}.
--                     The CHECKs keep it an object and under 8 KB.
--
-- Deleted with the account, as the rest of the row: the purge registry
-- (services/data_purge_registry.py) already deletes people_profiles by
-- user_id, and ON DELETE CASCADE from auth.users does the same.
-- Read and written by the backend (service role) only, as the table already
-- is; no grant changes. No environment variable needed.
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS, and each CHECK added
-- only when missing (DO block), so it can run twice. Nothing is dropped; no
-- row is written, rewritten or removed (the column starts NULL everywhere).
-- Locks: people_profiles briefly ACCESS EXCLUSIVE for the ADD COLUMN (no
-- default, so no rewrite) and SHARE UPDATE EXCLUSIVE while the NOT VALID
-- CHECKs are validated (a small table). One transaction.
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
        ALTER TABLE public.people_profiles
            VALIDATE CONSTRAINT people_profiles_join_questions_size;
    END IF;
END
$$;

COMMENT ON COLUMN public.people_profiles.join_questions IS
    'N487: the questions this person sets for everyone who joins through their link; NULL for none. Written by services/join_questions.py.';

COMMIT;
