-- a_host_keeps_taught_replies (the chat builder's visitor try)
--
-- Two tables, read and written by the backend only (service role). The
-- browser never sees them. A host's taught pairs are what the person asked
-- and the words the host sent instead. A draft is a reply the visitor must
-- not see yet: shadow, or a chat about health, law or money, or an
-- assistant that has not yet been sent twenty of the host's own answers.
--
--   chat_reply_examples   host_id, the browser's chat id (text, not a
--                         thread uuid), the question and the host's words.
--   chat_reply_drafts     the same, plus the unsent reply and an optional
--                         walk (a list), status draft or sent.
--
-- Both go with the account (ON DELETE CASCADE from auth.users, and the
-- purge registry). No environment variable is needed.
--
-- Idempotent and additive: CREATE TABLE IF NOT EXISTS. Nothing is dropped
-- and no row is written. One transaction.
--
-- Rollback (a new forward migration): leave both tables. Removing them is
-- a separate, previewed retention operation.

BEGIN;

SET LOCAL lock_timeout = '5s';

CREATE TABLE IF NOT EXISTS public.chat_reply_examples (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    host_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    chat_id     TEXT NOT NULL,
    ask         TEXT NOT NULL,
    answer      TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS chat_reply_examples_host_idx
    ON public.chat_reply_examples (host_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public.chat_reply_drafts (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    host_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    chat_id     TEXT NOT NULL,
    said        TEXT NOT NULL DEFAULT '',
    answer      TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'draft',
    walk        JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_reply_drafts_status CHECK (status IN ('draft', 'sent')),
    CONSTRAINT chat_reply_drafts_walk_is_a_list
        CHECK (walk IS NULL OR jsonb_typeof(walk) = 'array')
);

CREATE INDEX IF NOT EXISTS chat_reply_drafts_host_idx
    ON public.chat_reply_drafts (host_id, status, created_at);

ALTER TABLE public.chat_reply_examples ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_reply_drafts ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.chat_reply_examples FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.chat_reply_drafts FROM PUBLIC, anon, authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_reply_examples TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_reply_drafts TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
