-- people_chat_with_each_other (the chats between people, first slice;
-- founder, the Claude Code chat, 31 October 2026, N298 to N316)
--
-- A chat between two people: a person and a colleague, or a person and a
-- customer (N299 item 1). No group chats (N302 item 1). Separate from the
-- Lounge, the chat with Will (lounge_messages), which this file does not
-- touch. Founder only for now (ring 6).
--
--   chat_threads    One row per chat: its kind (a colleague's, 'team', or a
--                   customer's, 'customer') and a title. demo_user_id names
--                   the person a demo chat was made for (NULL for a real
--                   chat), so it is made once and goes with their account.
--   chat_members    Who is in a chat: a person with an account (user_id), or
--                   a guest with none (a customer, a demo person; user_id
--                   NULL), with the name and the line shown for them. A
--                   person is in a chat once.
--   chat_messages   What was said in a chat, oldest first: an emoji, words or
--                   a voice note, by one member, with a small meta (the
--                   emoji's label, N311 item 1).
--   feature_rings row   chats, ring 6 (the founder's ring).
--
-- Deleted with the account: the purge registry
-- (services/data_purge_registry.py) deletes a person's memberships
-- (chat_members.user_id) and their demo chats (chat_threads.demo_user_id);
-- their messages go with them (ON DELETE CASCADE). Read and written by the
-- backend (service role) only. No environment variable needed. Idempotent
-- and additive: IF NOT EXISTS / ON CONFLICT DO NOTHING everywhere, nothing
-- dropped. One transaction; explicit grants to service_role.

BEGIN;

CREATE TABLE IF NOT EXISTS public.chat_threads (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    demo_user_id  UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_threads_kind_check CHECK (kind IN ('team', 'customer')),
    CONSTRAINT chat_threads_title_len CHECK (char_length(title) BETWEEN 1 AND 200)
);

-- A person's demo chats: one of each kind, made once.
CREATE UNIQUE INDEX IF NOT EXISTS chat_threads_demo_once
    ON public.chat_threads (demo_user_id, kind)
    WHERE demo_user_id IS NOT NULL;

ALTER TABLE public.chat_threads ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.chat_threads FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_threads TO service_role;

CREATE TABLE IF NOT EXISTS public.chat_members (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id     UUID NOT NULL REFERENCES public.chat_threads(id) ON DELETE CASCADE,
    user_id       UUID REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name  TEXT NOT NULL,
    subtitle      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_members_name_len CHECK (char_length(display_name) BETWEEN 1 AND 120),
    CONSTRAINT chat_members_subtitle_len CHECK (char_length(subtitle) <= 200)
);

-- A person is in a chat once; guests (no account) are not keyed.
CREATE UNIQUE INDEX IF NOT EXISTS chat_members_one_per_person
    ON public.chat_members (thread_id, user_id)
    WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS chat_members_user_idx
    ON public.chat_members (user_id);

ALTER TABLE public.chat_members ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.chat_members FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_members TO service_role;

CREATE TABLE IF NOT EXISTS public.chat_messages (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id         UUID NOT NULL REFERENCES public.chat_threads(id) ON DELETE CASCADE,
    author_member_id  UUID NOT NULL REFERENCES public.chat_members(id) ON DELETE CASCADE,
    kind              TEXT NOT NULL,
    body              TEXT NOT NULL,
    meta              JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_messages_kind_check CHECK (kind IN ('emoji', 'text', 'voice')),
    CONSTRAINT chat_messages_body_len CHECK (char_length(body) <= 4000),
    CONSTRAINT chat_messages_meta_size CHECK (octet_length(meta::text) <= 16384)
);

CREATE INDEX IF NOT EXISTS chat_messages_thread_idx
    ON public.chat_messages (thread_id, created_at);
CREATE INDEX IF NOT EXISTS chat_messages_author_idx
    ON public.chat_messages (author_member_id);

ALTER TABLE public.chat_messages ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.chat_messages FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_messages TO service_role;

INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('chats', 6,
        'The chats between people (N298 to N316), first slice: a '
        'colleague''s chat and a customer''s, emoji only, with demo chats.',
        'migration:people_chat_with_each_other')
ON CONFLICT (feature) DO NOTHING;

-- The ring row's first entry in its audit trail, as 0394 wrote for its seeds.
INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.feature = 'chats'
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

COMMIT;
