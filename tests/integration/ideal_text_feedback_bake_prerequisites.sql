-- Narrow copies of the tables the bake's freshness rule reads.
--
-- `ideal_text_feedback_surface_touched_at_v1` (0345, widened by 0351) is a
-- LANGUAGE sql function, so every table it names must exist when the
-- migration is applied — Postgres parses SQL-language bodies at creation.
-- The released migrations that create these tables sit deep in chains this
-- lane has no other reason to build (`add_feedback_manager_and_part_commits`
-- alone carries the whole Manager commit path), so the lane lays down the
-- shapes the rule reads and the tests insert into, and nothing more.
--
-- Same discipline as the other *_prerequisites.sql files: a narrow copy
-- keeps the released column names and types for the columns it carries, and
-- the FK the join needs, and stays out of the way of the released CREATE
-- TABLE IF NOT EXISTS should one ever be applied on top.
--
-- The fifth table the rule reads since 0428, `exercise_coach_requests`, is
-- not copied here: its released chain (0385-0408) is shallow, and the lane
-- applies it as released (scripts/rehearsal_tier.sh), real writers included.
-- So is the sixth, `moment_events` (0408), which the skip-and-practice
-- re-issue (the_bake_knows_about_skips_and_practice.sql) reads. The seventh,
-- `confident_voice_practice`, is copied narrow at the end of this file.
\set ON_ERROR_STOP on

CREATE TABLE IF NOT EXISTS public.intervention_decisions (
    id BIGSERIAL PRIMARY KEY,
    arc_id TEXT NOT NULL,
    take_session_id TEXT NOT NULL DEFAULT '',
    change_key TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('approved', 'disregarded')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (arc_id, take_session_id, change_key)
);

CREATE TABLE IF NOT EXISTS public.user_suggestion_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    snippet_id UUID NOT NULL,
    session_id UUID NULL,
    user_id UUID NULL,
    target TEXT NOT NULL,
    action TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- The legacy answer route's row. `arc_id` is on the row, as released.
CREATE TABLE IF NOT EXISTS public.take_feedback_self_report (
    id BIGSERIAL PRIMARY KEY,
    arc_id TEXT NOT NULL,
    take_session_id UUID NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
    owner_user_id UUID NOT NULL,
    feedback_id TEXT NOT NULL,
    feedback_family TEXT NOT NULL,
    response TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (take_session_id, owner_user_id, feedback_id)
);

-- The service answer route's rows: an answer names its membership, the
-- membership names its take. Only the columns the join walks.
CREATE TABLE IF NOT EXISTS public.feedback_v3_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    take_id UUID NOT NULL REFERENCES public.v2_sessions(id) ON DELETE RESTRICT,
    document_snapshot_id UUID NULL,
    frozen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS public.feedback_v3_owner_responses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    membership_id UUID NOT NULL REFERENCES public.feedback_v3_memberships(id)
        ON DELETE RESTRICT,
    candidate_id UUID NOT NULL,
    owner_user_id UUID NOT NULL,
    response TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

-- The practice a speaker opens on a moment (released 0279; reshaped by
-- 0374, 0396, 0400, 0407, 0409). The rule reads its start (`created_at`)
-- and its close (`closed_at`), reaching the arc through its take
-- (the_bake_knows_about_skips_and_practice.sql). Copied narrow because 0279
-- references the snippets table and the exercise library, which this lane
-- has no other reason to build. Kept: the columns the rule reads and the
-- columns the speaker's writers set at the start, the dismissal and the close
-- after a judged attempt, under their released names, types and checks.
CREATE TABLE IF NOT EXISTS public.confident_voice_practice (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id        UUID NOT NULL REFERENCES auth.users(id)
                         ON DELETE CASCADE,
    take_session_id      UUID NOT NULL REFERENCES public.v2_sessions(id)
                         ON DELETE CASCADE,
    snippet_id           UUID NOT NULL,
    status               TEXT NOT NULL DEFAULT 'open'
                         CHECK (status IN ('open', 'completed', 'dismissed')),
    selected_attempt_id  UUID NULL,
    final_user_answer    TEXT NULL,
    landed_attempt_index INTEGER NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at            TIMESTAMPTZ NULL,
    CONSTRAINT cvp_final_user_answer_five CHECK (final_user_answer IN (
        'yes', 'in_between', 'no', 'not_sure', 'audio_unclear')),
    CONSTRAINT confident_voice_practice_one_per_moment
        UNIQUE (take_session_id, snippet_id)
);
