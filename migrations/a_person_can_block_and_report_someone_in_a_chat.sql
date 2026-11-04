-- a_person_can_block_and_report_someone_in_a_chat (Block and Report in the
-- chats between people; founder, the Claude Code chat, 4 November 2026, N466;
-- Apple's rule 1.2 for apps where people message each other)
--
-- Two additions to the chats (people_chat_with_each_other, 0503):
--
--   chat_members.blocked_spans  On a member's own row: when they blocked the
--                  other person in this chat, as a list of spans
--                  [{"from": iso, "to": iso or null}], the open one (to null)
--                  being the block in force. A message the other person sent
--                  inside any span never reaches this member, also after
--                  Unblock (N466 item 2); no push goes to them while blocked.
--                  Empty for everyone until someone blocks.
--
--   chat_reports   One row per report (N466 item 3): the chat, who reported
--                  and whom, whether they also blocked, the last five
--                  messages as the reporter saw them (author, kind, text, a
--                  voice note's words, when), when it was made, and when the
--                  founder marked it read. Read by the founder in the CEO
--                  panel. It goes with either account: its members' rows
--                  cascade.
--
-- The reports hold people's messages, so the table is the backend's alone:
-- read and written by the service role only; nothing for anon or
-- authenticated. No environment variable is needed.
--
-- Idempotent and additive: ADD COLUMN IF NOT EXISTS with a constant default
-- (no table rewrite on Postgres 11+), CREATE ... IF NOT EXISTS; nothing is
-- dropped and no row is written, rewritten or removed. One transaction;
-- explicit grants to service_role, as 0505 to 0508.
--
-- Rollback (a new forward migration): leave both; dropping them is a
-- separate, previewed retention operation.

BEGIN;

ALTER TABLE public.chat_members
    ADD COLUMN IF NOT EXISTS blocked_spans JSONB NOT NULL DEFAULT '[]'::jsonb;

CREATE TABLE IF NOT EXISTS public.chat_reports (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id           UUID NOT NULL REFERENCES public.chat_threads(id) ON DELETE CASCADE,
    reporter_member_id  UUID NOT NULL REFERENCES public.chat_members(id) ON DELETE CASCADE,
    reported_member_id  UUID NOT NULL REFERENCES public.chat_members(id) ON DELETE CASCADE,
    blocked             BOOLEAN NOT NULL DEFAULT false,
    messages            JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    handled_at          TIMESTAMPTZ,
    CONSTRAINT chat_reports_messages_are_a_list CHECK (jsonb_typeof(messages) = 'array'),
    CONSTRAINT chat_reports_two_people CHECK (reporter_member_id <> reported_member_id)
);

CREATE INDEX IF NOT EXISTS chat_reports_created_idx ON public.chat_reports (created_at DESC);
CREATE INDEX IF NOT EXISTS chat_reports_reporter_idx ON public.chat_reports (reporter_member_id);
CREATE INDEX IF NOT EXISTS chat_reports_reported_idx ON public.chat_reports (reported_member_id);

ALTER TABLE public.chat_reports ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.chat_reports FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chat_reports TO service_role;

COMMIT;
