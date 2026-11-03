-- a_chat_keeps_its_photos_and_files (the "+" in a chat with a person;
-- founder, the Claude Code chat, 2 November 2026: "The + should be opening
-- smth… photos or files or screen shots… the files and photos though are
-- certain. So build that", then "Ok build the top bar and the bottom bar";
-- N351, with N335 item 3, N337 and N341 item 2)
--
-- A photo or a file sent in a chat between people is a message of its own,
-- kept with its bytes, as a voice note is kept with its recording (0504).
--
--   chat_messages.kind   Holds 'photo' and 'file' besides 'emoji', 'text'
--                        and 'voice'. The CHECK is swapped, DROP CONSTRAINT
--                        IF EXISTS then ADD CONSTRAINT under the same name,
--                        as 0397 and 0459 widened theirs. Every existing row
--                        satisfies the wider CHECK.
--   chat_message_files   One row per photo or file: its bytes, in the
--                        database so the account purge takes it as an
--                        ordinary row (services/data_purge_registry.py), as
--                        chat_message_audio; its type, and its own file name
--                        as it came. Its message is the chat_messages row of
--                        kind 'photo' or 'file'; the row goes when the
--                        message, the chat or the person who sent it goes.
--
-- Read only through the backend, after it checks that the caller is a member
-- of the chat (services/chats.py). Read and written by the backend (service
-- role) only; nothing for anon or authenticated. No environment variable
-- needed.
--
-- Idempotent: CREATE ... IF NOT EXISTS, and the CHECK swapped by DROP
-- CONSTRAINT IF EXISTS then ADD CONSTRAINT; applied twice it changes nothing.
-- Nothing is dropped but that one CHECK, replaced in the same transaction by
-- a wider one; no row is written, rewritten or removed. Locks: chat_messages
-- briefly ACCESS EXCLUSIVE for the swap and one validating scan (a few
-- hundred rows at most, ring 6 only). One transaction; explicit grants to
-- service_role, as 0503 and 0504.
--
-- Rollback (a new forward migration): narrow the CHECK back to the three
-- kinds (refused while a photo or a file exists, which is the point) and
-- leave the table (dropping it is a separate, previewed retention operation).

BEGIN;

ALTER TABLE public.chat_messages
    DROP CONSTRAINT IF EXISTS chat_messages_kind_check;
ALTER TABLE public.chat_messages
    ADD CONSTRAINT chat_messages_kind_check
    CHECK (kind IN ('emoji', 'text', 'voice', 'photo', 'file'));

CREATE TABLE IF NOT EXISTS public.chat_message_files (
    message_id    UUID PRIMARY KEY
                  REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    thread_id     UUID NOT NULL
                  REFERENCES public.chat_threads(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL
                  REFERENCES auth.users(id) ON DELETE CASCADE,
    content_type  TEXT NOT NULL,
    file_name     TEXT NOT NULL DEFAULT '',
    data          BYTEA NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_message_files_type
        CHECK (char_length(content_type) BETWEEN 3 AND 100),
    CONSTRAINT chat_message_files_name_len
        CHECK (char_length(file_name) <= 255),
    CONSTRAINT chat_message_files_size
        CHECK (octet_length(data) BETWEEN 1 AND 10485760)
);

CREATE INDEX IF NOT EXISTS chat_message_files_thread_idx
    ON public.chat_message_files (thread_id);
CREATE INDEX IF NOT EXISTS chat_message_files_user_idx
    ON public.chat_message_files (user_id);

ALTER TABLE public.chat_message_files ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.chat_message_files FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_message_files TO service_role;

COMMIT;
