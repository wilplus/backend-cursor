-- a_person_keeps_their_chat_recipe (every inviter's own chat, answered by
-- "{name}'s assistant"; N578 item 7, N579, N586 item 1, N588 item 2)
--
-- One addition to a person's profile (people_profiles,
-- a_person_has_a_profile.sql):
--
--   chat_recipe   The recipe of the person's own chat, one per chat (N578
--                 item 7): {"v", "welcome": [lines], "questions": [{"q",
--                 "title"?, "under"?, "answers"}], "answer_with": {"tap",
--                 "type", "record"}, "about": [lines], "fit"?: {"coaches",
--                 "needs", "topics", "skill"?}, "updated_at"}, written and
--                 read only by services/assistants.py, behind the ring row
--                 chat_builder (N579 item 2). NULL means none set: the
--                 person's chat is as it was. It goes with the profile row,
--                 so the account purge takes it with the row.
--
-- Profiles are read and written by the backend (service role) only; the
-- table's grants (a_person_has_a_profile.sql) cover the new column. No
-- environment variable is needed.
--
-- The same shape as a_person_keeps_their_join_questions.sql, reviewed
-- outside (Grok, 6 November 2026): lock_timeout, a guarded CHECK that the
-- value is an object or NULL, and a PostgREST schema reload.
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS, nullable, no default,
-- so no row is rewritten; nothing is dropped and no row is written or
-- removed. One transaction.
--
-- Rollback (a new forward migration): leave the column; dropping it is a
-- separate, previewed retention operation.

BEGIN;

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.people_profiles ADD COLUMN IF NOT EXISTS chat_recipe JSONB;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'public.people_profiles'::regclass
          AND conname = 'people_profiles_chat_recipe_is_object'
    ) THEN
        ALTER TABLE public.people_profiles
            ADD CONSTRAINT people_profiles_chat_recipe_is_object
            CHECK (chat_recipe IS NULL OR jsonb_typeof(chat_recipe) = 'object');
    END IF;
END
$$;

NOTIFY pgrst, 'reload schema';

COMMIT;
