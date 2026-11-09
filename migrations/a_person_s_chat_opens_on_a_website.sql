-- a_person_s_chat_opens_on_a_website (your chat on any website, the same link
-- as one line of code; founder, the Claude Code chat, 5 November 2026, N565)
--
-- Two additions to the chats (people_chat_with_each_other, 0503; the join
-- link, a_person_has_a_link_to_join_them, 0505):
--
--   chat_threads.widget_owner_id
--                  The person whose website chat this is, for a chat a
--                  visitor opened through the widget (`w.js`, N565 item 3).
--                  NULL for every other chat. With the account: a widget
--                  chat goes when its owner's account goes (ON DELETE
--                  CASCADE, and the purge registry names it), its messages,
--                  members and guest row with it.
--
--   chat_widget_guests
--                  One row per visitor who tapped "Agree and start" in a
--                  person's widget (N565 item 4): the link it came through,
--                  the chat and the visitor's seat in it, a hash of the
--                  visitor's secret (the secret itself lives only in the
--                  visitor's browser, on willpowerlab.com), the site the
--                  widget was opened on (a host name, for "From {site}"), the
--                  visitor's number among the owner's ("Widget / Visitor
--                  {n}"), when they agreed, and when they kept the chat by
--                  joining (N565 item 7). No name, no number, no email: the
--                  visitor can only tap.
--
-- The widget's chats do not set chat_threads.link_id, so they never count
-- toward the day's joins through a link (membership.link_is_full, N471
-- item 7); the guest row carries the link instead.
--
-- Read and written by the service role only; nothing for anon or
-- authenticated. No environment variable is needed.
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS, CREATE ... IF NOT
-- EXISTS; nothing is dropped and no row is written, rewritten or removed.
-- One transaction; explicit grants to service_role, as 0509 and 0512.
--
-- lock_timeout: ADD COLUMN on chat_threads takes a brief ACCESS EXCLUSIVE
-- lock; on a live table a long wait would queue every chat read behind it,
-- so the migration gives up after 5 seconds and the release retries it, as
-- 0514 does.
--
-- NOTIFY pgrst: the backend reaches these tables through PostgREST, whose
-- schema cache would otherwise miss the new column and table until its next
-- reload, as 0514 does.
--
-- Reviewed outside (Grok, 9 November 2026): approved with one change,
-- indexes on chat_widget_guests.thread_id and member_id so the deletes that
-- cascade through them do not scan. They are there already: the UNIQUE
-- constraints on both columns are unique btree indexes (checked with
-- pg_indexes on PostgreSQL 16), so no second index is added; every foreign
-- key a delete cascades through (link_id, owner_user_id, thread_id,
-- member_id; chat_threads.widget_owner_id) has one.
--
-- Rollback (a new forward migration): leave them; dropping them is a
-- separate, previewed retention operation.

BEGIN;

SET LOCAL lock_timeout = '5s';

ALTER TABLE public.chat_threads
    ADD COLUMN IF NOT EXISTS widget_owner_id UUID REFERENCES auth.users(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS chat_threads_widget_owner_idx
    ON public.chat_threads (widget_owner_id) WHERE widget_owner_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.chat_widget_guests (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    link_id        UUID NOT NULL REFERENCES public.chat_links(id) ON DELETE CASCADE,
    owner_user_id  UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    thread_id      UUID NOT NULL REFERENCES public.chat_threads(id) ON DELETE CASCADE,
    member_id      UUID NOT NULL REFERENCES public.chat_members(id) ON DELETE CASCADE,
    secret_hash    TEXT NOT NULL,
    site           TEXT,
    number         INTEGER NOT NULL,
    consented_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    kept_at        TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_widget_guests_secret_unique UNIQUE (secret_hash),
    CONSTRAINT chat_widget_guests_thread_unique UNIQUE (thread_id),
    CONSTRAINT chat_widget_guests_member_unique UNIQUE (member_id),
    CONSTRAINT chat_widget_guests_secret_check CHECK (char_length(secret_hash) = 64),
    CONSTRAINT chat_widget_guests_site_check CHECK (site IS NULL OR char_length(site) BETWEEN 1 AND 120),
    CONSTRAINT chat_widget_guests_number_check CHECK (number > 0)
);

CREATE INDEX IF NOT EXISTS chat_widget_guests_owner_idx ON public.chat_widget_guests (owner_user_id);
CREATE INDEX IF NOT EXISTS chat_widget_guests_link_idx ON public.chat_widget_guests (link_id);

ALTER TABLE public.chat_widget_guests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.chat_widget_guests FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.chat_widget_guests TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
