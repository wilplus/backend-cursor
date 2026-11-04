-- a_not_now_is_counted (each "Not now" kept as behavioural data; founder,
-- the Claude Code chat, 4 November 2026, N504 item 2: "a person no - maybe a
-- system for tracking who rejected how many times etc. for the behavioral
-- data table that is created from the interaction with the system next to
-- the voice data; it should be also visible in the ceo panel in the user
-- profile below the voice data from the takes")
--
-- One addition to the chats (people_chat_with_each_other, 0503):
--
--   chat_not_now   One row per "Not now" a person taps under a question or a
--                  Take someone asked them in a chat (N483 item 3, N493
--                  item 3): the chat, who declined, whose question or Take,
--                  which message, what it was ('take' or 'question'), the
--                  flow ('list', a Take sent to your list, N470; 'match', a
--                  matched Take, N485), and when. Once per person and
--                  message: a second tap on the same one keeps the first
--                  row. Nobody is ever told (N483 item 3, N485 item 3); the
--                  founder reads it on the person's admin page, under the
--                  voice data from their Takes, and the matching may read it.
--                  It goes with either account: its members' rows cascade.
--
-- Behavioural data about people, so the table is the backend's alone: read
-- and written by the service role only; nothing for anon or authenticated.
-- No environment variable is needed.
--
-- Reviewed outside (4 November 2026): approved with one change, the indexes
-- on thread_id and message_id for the cascading deletes, made here.
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS; nothing is dropped and
-- no row is written, rewritten or removed. One transaction; explicit grants
-- to service_role, as 0509.
--
-- Rollback (a new forward migration): leave it; dropping it is a separate,
-- previewed retention operation.

BEGIN;

CREATE TABLE IF NOT EXISTS public.chat_not_now (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id         UUID NOT NULL REFERENCES public.chat_threads(id) ON DELETE CASCADE,
    member_id         UUID NOT NULL REFERENCES public.chat_members(id) ON DELETE CASCADE,
    asker_member_id   UUID NOT NULL REFERENCES public.chat_members(id) ON DELETE CASCADE,
    message_id        UUID NOT NULL REFERENCES public.chat_messages(id) ON DELETE CASCADE,
    what              TEXT NOT NULL,
    flow              TEXT NOT NULL DEFAULT 'list',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_not_now_what_check CHECK (what IN ('take', 'question')),
    CONSTRAINT chat_not_now_flow_check CHECK (flow IN ('list', 'match')),
    CONSTRAINT chat_not_now_two_people CHECK (member_id <> asker_member_id),
    CONSTRAINT chat_not_now_once UNIQUE (member_id, message_id)
);

CREATE INDEX IF NOT EXISTS chat_not_now_member_idx ON public.chat_not_now (member_id, created_at DESC);
CREATE INDEX IF NOT EXISTS chat_not_now_asker_idx ON public.chat_not_now (asker_member_id);
-- The two other columns a delete cascades through (a chat thread, a
-- message), so those deletes find their rows without a scan (outside
-- review, 4 November 2026).
CREATE INDEX IF NOT EXISTS chat_not_now_thread_idx ON public.chat_not_now (thread_id);
CREATE INDEX IF NOT EXISTS chat_not_now_message_idx ON public.chat_not_now (message_id);

ALTER TABLE public.chat_not_now ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.chat_not_now FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_not_now TO service_role;

COMMIT;
