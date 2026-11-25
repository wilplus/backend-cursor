-- a_person_s_own_chats_are_one_kind (founder, the Claude Code chat, 25
-- November 2026, N700)
--
-- Every chat of a person's own is the same kind of chat, in one flat list,
-- and becomes what it is used for. One row per chat:
--
--   own_chats     its name; the project it holds once a Take or slides are
--                 added there (one project per chat); the section of the
--                 old Lounge it carries on for (speaking, principles, will),
--                 so rows written before this change are read into it; when
--                 it was last used (Will's unprompted messages go there).
--
-- Messages stay in lounge_messages: a row written in a chat names it in its
-- metadata (``chat_id``), so that table does not change. Rows written before
-- this change are placed at read time by their project or their section
-- (services/own_chats.py).
--
-- Account deletion takes these rows (services/data_purge_registry.py). Read
-- and written by the backend (service role) only. No environment variable
-- needed. Idempotent and additive: IF NOT EXISTS everywhere, nothing
-- dropped. One transaction; explicit grants to service_role.

BEGIN;

-- gen_random_uuid(): core since PostgreSQL 13; kept explicit, as earlier files do.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS public.own_chats (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL,
    title         TEXT NOT NULL,
    arc_id        UUID,
    legacy_place  TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT own_chats_title_len CHECK (char_length(title) BETWEEN 1 AND 200),
    CONSTRAINT own_chats_legacy_place_check
        CHECK (legacy_place IS NULL OR legacy_place IN ('speaking', 'principles', 'will'))
);

-- One chat per project, and one per old section, per person.
CREATE UNIQUE INDEX IF NOT EXISTS own_chats_one_per_project
    ON public.own_chats (user_id, arc_id)
    WHERE arc_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS own_chats_one_per_place
    ON public.own_chats (user_id, legacy_place)
    WHERE legacy_place IS NOT NULL;
-- The list, the newest used first.
CREATE INDEX IF NOT EXISTS own_chats_by_use
    ON public.own_chats (user_id, last_used_at DESC);

ALTER TABLE public.own_chats ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.own_chats FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.own_chats TO service_role;

COMMIT;
