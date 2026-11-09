-- a_question_joins_its_bundle (one recording answers everyone who asked the
-- same thing; N584, the speaking coach's exercises made universal)
--
-- Two new tables, read and written only by services/question_bundles.py
-- (service role), behind the ring row chat_builder (N579 item 2):
--
--   question_bundles        A host's bundle of questions that ask the same
--                           thing (N584 item 1): once the host records one
--                           answer, the Take that answer is (answer_take)
--                           and when. It keeps no asker's words: a bundle
--                           reads as its earliest question still kept, so
--                           an asker's erasure takes their words with them.
--   question_bundle_askers  Each question in a bundle: who asked, in which
--                           chat, by which message, its words, and how sure
--                           the match is, as a colour (N580 item 3, never a
--                           number); answered_message_id is the answer the
--                           asker got in their own chat (N584 items 3, 4),
--                           so nobody is sent the same answer twice (N103).
--
-- Deleting: each row goes with its host's or its asker's account (ON DELETE
-- CASCADE from auth.users, and the purge registry names both), with the
-- chat or the message it points at, and an asker's rows with their bundle.
--
-- Grants: RLS on, nothing for anon or authenticated; the service role reads
-- and writes. No environment variable is needed.
--
-- Idempotent and additive: CREATE TABLE / INDEX IF NOT EXISTS; nothing is
-- dropped, no existing row is written. One transaction; lock_timeout keeps
-- the foreign keys' brief locks on chat_threads and chat_messages from
-- queueing behind a long transaction.
--
-- Rollback (a new forward migration): leave the tables; dropping them is a
-- separate, previewed retention operation.

BEGIN;

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.question_bundles (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    host_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    answer_take  UUID,
    answered_at  TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS question_bundles_host_idx
    ON public.question_bundles (host_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.question_bundle_askers (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    bundle_id            UUID NOT NULL REFERENCES public.question_bundles(id) ON DELETE CASCADE,
    asker_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    thread_id            UUID NOT NULL REFERENCES public.chat_threads(id) ON DELETE CASCADE,
    message_id           UUID NOT NULL REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    words                TEXT NOT NULL,
    mark                 TEXT NOT NULL,
    answered_message_id  UUID REFERENCES public.chat_messages(id) ON DELETE SET NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT question_bundle_askers_words_len CHECK (char_length(words) BETWEEN 1 AND 2000),
    CONSTRAINT question_bundle_askers_mark CHECK (mark IN ('green', 'yellow', 'red'))
);

-- A question is in one bundle.
CREATE UNIQUE INDEX IF NOT EXISTS question_bundle_askers_message_once
    ON public.question_bundle_askers (message_id);
CREATE INDEX IF NOT EXISTS question_bundle_askers_bundle_idx
    ON public.question_bundle_askers (bundle_id);
CREATE INDEX IF NOT EXISTS question_bundle_askers_asker_idx
    ON public.question_bundle_askers (asker_id);
-- Deleting a chat message sets answered_message_id to NULL: indexed, so
-- that delete never scans this table.
CREATE INDEX IF NOT EXISTS question_bundle_askers_answered_idx
    ON public.question_bundle_askers (answered_message_id)
    WHERE answered_message_id IS NOT NULL;

ALTER TABLE public.question_bundles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.question_bundle_askers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.question_bundles FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.question_bundle_askers FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.question_bundles TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.question_bundle_askers TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
