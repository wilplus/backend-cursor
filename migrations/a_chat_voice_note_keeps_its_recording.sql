-- A voice note in a chat between people keeps its recording (founder,
-- 2026-11-02, N321 item 2: "you can always answer with an emoji or a mic").
--
--   chat_message_audio  One row per voice note sent in a chat: the recording,
--                       in the database so the account purge takes it as an
--                       ordinary row (services/data_purge_registry.py), as
--                       plan_answer_audio (the_plan_keeps_each_speakers_plan)
--                       and voice_notebook_audio do. Its message is the
--                       chat_messages row of kind 'voice'; the row goes when
--                       the message, the chat or the person who recorded it
--                       goes. `words` holds what was said, when the voice
--                       note is turned into words; null otherwise.
--
-- Played back only through the backend, after it checks that the caller is a
-- member of the chat (services/chats.py). Read and written by the backend
-- (service role) only; nothing for anon or authenticated. No environment
-- variable needed. Idempotent and additive: IF NOT EXISTS everywhere, nothing
-- dropped or altered on an existing table. One transaction; explicit grants to
-- service_role, as people_chat_with_each_other (0503).

BEGIN;

CREATE TABLE IF NOT EXISTS public.chat_message_audio (
    message_id    UUID PRIMARY KEY
                  REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    thread_id     UUID NOT NULL
                  REFERENCES public.chat_threads(id) ON DELETE CASCADE,
    user_id       UUID NOT NULL
                  REFERENCES auth.users(id) ON DELETE CASCADE,
    content_type  TEXT NOT NULL,
    duration_ms   INTEGER NOT NULL,
    audio         BYTEA NOT NULL,
    words         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_message_audio_type
        CHECK (content_type LIKE 'audio/%' AND char_length(content_type) <= 100),
    CONSTRAINT chat_message_audio_duration
        CHECK (duration_ms BETWEEN 1 AND 600000),
    CONSTRAINT chat_message_audio_size
        CHECK (octet_length(audio) BETWEEN 1 AND 12582912),
    CONSTRAINT chat_message_audio_words_len
        CHECK (char_length(words) <= 20000)
);

CREATE INDEX IF NOT EXISTS chat_message_audio_thread_idx
    ON public.chat_message_audio (thread_id);
CREATE INDEX IF NOT EXISTS chat_message_audio_user_idx
    ON public.chat_message_audio (user_id);

ALTER TABLE public.chat_message_audio ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.chat_message_audio FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_message_audio TO service_role;

COMMIT;
