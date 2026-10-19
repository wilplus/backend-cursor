-- speakers_tell_us_if_feedback_helped_and_goals_keep_history (WIL-74, phase 1)
--
-- Two small tables, and one nullable column on lounge_messages.
--
--   take_feedback_checks  After the Feedback walk the chat asks "Did this
--                         feedback help you?" (Yes / Not really). One row per
--                         Take: the answer and, after "Not really", what was
--                         missing in the speaker's own words. Never shown to
--                         the speaker as a number or a verdict.
--   user_goal_history     Every goal a speaker has had, oldest first. The
--                         current goal stays in user_settings.profile_goal;
--                         this table only ever gets new rows.
--
-- Read and written by the backend (service role) only. Both are purged with
-- the account (services/data_purge_registry.py). No environment variable
-- needed. Idempotent and additive: IF NOT EXISTS everywhere, nothing dropped.

CREATE TABLE IF NOT EXISTS public.take_feedback_checks (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID NOT NULL,
    arc_id           UUID,
    take_session_id  UUID NOT NULL,
    helped           BOOLEAN,
    missing          TEXT,
    skipped          BOOLEAN NOT NULL DEFAULT false,
    asked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    answered_at      TIMESTAMPTZ,
    CONSTRAINT take_feedback_checks_one_per_take UNIQUE (user_id, take_session_id),
    CONSTRAINT take_feedback_checks_missing_len CHECK (missing IS NULL OR char_length(missing) <= 2000)
);

CREATE INDEX IF NOT EXISTS take_feedback_checks_answered_idx
    ON public.take_feedback_checks (answered_at);

ALTER TABLE public.take_feedback_checks ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.take_feedback_checks FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS public.user_goal_history (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID NOT NULL,
    goal           TEXT NOT NULL,
    previous_goal  TEXT,
    source         TEXT NOT NULL DEFAULT 'chat',
    changed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT user_goal_history_source_check CHECK (source IN ('chat', 'profile'))
);

CREATE INDEX IF NOT EXISTS user_goal_history_user_idx
    ON public.user_goal_history (user_id, changed_at);

ALTER TABLE public.user_goal_history ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.user_goal_history FROM anon, authenticated;

-- The coach's card about a speaker's new goal sits in the coach's Lounge.
-- about_user_id names the speaker it is about, so deleting that speaker's
-- account deletes the card too (purge registry: lounge_about).
ALTER TABLE public.lounge_messages
    ADD COLUMN IF NOT EXISTS about_user_id UUID;

CREATE INDEX IF NOT EXISTS lounge_messages_about_user_idx
    ON public.lounge_messages (about_user_id) WHERE about_user_id IS NOT NULL;
