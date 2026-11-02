-- a_person_has_a_link_to_join_them (the join link, the chats' second slice;
-- founder, the Claude Code chat, 2 November 2026: "go, build the join link
-- slice"; N308, N328, N335)
--
-- Everyone has their own link to join them in a chat (N308). Whoever opens it
-- and joins gets a chat with them; nobody can reach a person any other way
-- (N328). Founder only for now: the chats' ring row (chats, ring 6) gates it
-- as it gates the rest.
--
--   chat_links           One row per link: whose it is (user_id), the
--                        secret in the link (token, random, unique), the
--                        first name shown on the join page (display_name),
--                        and when it was replaced (revoked_at). A person has
--                        one live link at a time.
--   chat_threads.link_id The link a chat was made through (NULL for a demo
--                        chat). ON DELETE SET NULL: the chat stays when its
--                        link goes.
--   chat_threads.pair_key The two people of a chat made through a link, as
--                        "<smaller id>:<larger id>"; unique, so two people
--                        have one such chat however often either opens a
--                        link.
--
-- Deleted with the account: the purge registry
-- (services/data_purge_registry.py) deletes a person's links
-- (chat_links.user_id); ON DELETE CASCADE from auth.users does the same.
-- Read and written by the backend (service role) only. No environment
-- variable needed. Idempotent and additive: IF NOT EXISTS everywhere,
-- nothing dropped. One transaction; explicit grants to service_role.

BEGIN;

CREATE TABLE IF NOT EXISTS public.chat_links (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    token         TEXT NOT NULL,
    display_name  TEXT NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at    TIMESTAMPTZ,
    CONSTRAINT chat_links_token_len CHECK (char_length(token) BETWEEN 16 AND 64),
    CONSTRAINT chat_links_name_len CHECK (char_length(display_name) BETWEEN 1 AND 120)
);

CREATE UNIQUE INDEX IF NOT EXISTS chat_links_token_once
    ON public.chat_links (token);
-- One live link per person.
CREATE UNIQUE INDEX IF NOT EXISTS chat_links_one_live
    ON public.chat_links (user_id)
    WHERE revoked_at IS NULL;

ALTER TABLE public.chat_links ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.chat_links FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_links TO service_role;

ALTER TABLE public.chat_threads
    ADD COLUMN IF NOT EXISTS link_id UUID REFERENCES public.chat_links(id) ON DELETE SET NULL;
ALTER TABLE public.chat_threads
    ADD COLUMN IF NOT EXISTS pair_key TEXT;

-- Two people have one chat made through a link.
CREATE UNIQUE INDEX IF NOT EXISTS chat_threads_pair_once
    ON public.chat_threads (pair_key)
    WHERE pair_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS chat_threads_link_idx
    ON public.chat_threads (link_id);

COMMIT;
