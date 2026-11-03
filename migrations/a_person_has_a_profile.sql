-- a_person_has_a_profile (a person's profile, as on WhatsApp; founder, the
-- Claude Code chat, 3 November 2026: "We need to design user profile, just
-- like on WhatsApp ... your name, and files you shared", then "make it just
-- like on WhatsApp, that you can edit your name, you can edit your role";
-- N366, locked in docs/LOCKS.md with the prototype "One bar")
--
-- What a person says about themselves, shown on their profile to the people
-- they chat with: their name, who they are, their About, and their photo.
-- The photos and files of the profile are the chat's own (0506); nothing
-- here copies them.
--
--   people_profiles   One row per person, made the first time they save
--                     anything. name: shown instead of the account's name
--                     (1 to 40 characters); role: who they are (up to 60);
--                     about: their About (up to 300); about_edited_at: when
--                     they last changed it; photo and photo_type: their
--                     circle, the bytes in the database so the account
--                     purge takes it as an ordinary row
--                     (services/data_purge_registry.py), as
--                     chat_message_files (0506). The row goes with the
--                     account.
--
-- Read only through the backend, after it checks the caller may see it (the
-- person themselves, or someone in a chat with them; services/people_profiles.py).
-- Read and written by the backend (service role) only; nothing for anon or
-- authenticated. No environment variable needed.
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS; nothing is dropped and no
-- row is written, rewritten or removed. One transaction; explicit grants to
-- service_role, as 0505 and 0506.
--
-- Rollback (a new forward migration): leave the table; dropping it is a
-- separate, previewed retention operation.

BEGIN;

CREATE TABLE IF NOT EXISTS public.people_profiles (
    user_id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    name             TEXT,
    role             TEXT,
    about            TEXT,
    about_edited_at  TIMESTAMPTZ,
    photo            BYTEA,
    photo_type       TEXT,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT people_profiles_name_len CHECK (name IS NULL OR char_length(name) BETWEEN 1 AND 40),
    CONSTRAINT people_profiles_role_len CHECK (role IS NULL OR char_length(role) BETWEEN 1 AND 60),
    CONSTRAINT people_profiles_about_len CHECK (about IS NULL OR char_length(about) BETWEEN 1 AND 300),
    CONSTRAINT people_profiles_photo_type CHECK (photo_type IS NULL OR char_length(photo_type) BETWEEN 3 AND 100),
    CONSTRAINT people_profiles_photo_size CHECK (photo IS NULL OR octet_length(photo) <= 5242880)
);

ALTER TABLE public.people_profiles ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.people_profiles FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.people_profiles TO service_role;

COMMIT;
