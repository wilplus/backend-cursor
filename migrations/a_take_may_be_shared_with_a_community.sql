-- 0432 · a Take may be shared with a community (founder 2026-10-06,
-- decisions log N52.4; docs/FOUNDER-LOCK-feedback-walk-2026-10-06.md,
-- "Communities will work")
--
-- WHY. N52.4: "After every finished review the speaker is asked whether to
-- share that Take; several choices may be ticked: the general community,
-- only my community (with a pass code), or a community of their own (a name
-- and a pass code); 'None' stands alone. A shared Take is judged by the
-- community chosen; with 'None' only the coach judges it. When judging, the
-- speaker hears their community's Takes first, then their own mixed with
-- training clips. Consent is per Take, and taking it back removes the Take
-- from every community queue. Community answers are peer ratings, a
-- provenance of their own (L3), never coach labels, owner routing or
-- training labels by themselves."
--
-- WHAT. The communities (one open 'general' row, seeded here, and private
-- ones a speaker sets up with a name and a pass code kept only as a keyed
-- digest), who belongs to which, the per-Take consent to share with each
-- (revocable: revoked_at), and the answers listeners give. One live view,
-- community_clips_live, is the only thing the queue reads: the moments of
-- Takes shared and not revoked, in communities not closed, so one
-- revocation leaves every queue at once. Additive; idempotent; no env var.
--
-- DARK AND GATED: Config.COMMUNITIES_ENABLED is False (every route answers
-- 404), and sharing also needs Config.COMMUNITY_SHARE_POLICY_VERSION, which
-- is None until counsel approves the sharing words (panel CM2): nothing is
-- shared until then. The general row is the only row this file writes.
--
-- Rollback (a new forward migration): drop the view and the four tables.

BEGIN;

CREATE TABLE IF NOT EXISTS public.communities (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    kind             text        NOT NULL,
    name             text        NULL,
    pass_code_digest text        NULL,
    created_by       text        NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    closed_at        timestamptz NULL,
    CONSTRAINT communities_kind_check CHECK (kind IN ('general', 'private')),
    CONSTRAINT communities_private_is_named CHECK (
        kind <> 'private'
        OR (name IS NOT NULL AND pass_code_digest IS NOT NULL AND created_by IS NOT NULL)),
    CONSTRAINT communities_general_is_open CHECK (
        kind <> 'general'
        OR (name IS NULL AND pass_code_digest IS NULL AND created_by IS NULL)),
    CONSTRAINT communities_name_length CHECK (
        name IS NULL OR char_length(btrim(name)) BETWEEN 1 AND 80)
);
-- Exactly one general community; a pass code opens at most one community.
CREATE UNIQUE INDEX IF NOT EXISTS communities_one_general
    ON public.communities (kind) WHERE kind = 'general';
CREATE UNIQUE INDEX IF NOT EXISTS communities_pass_code_digest_key
    ON public.communities (pass_code_digest) WHERE pass_code_digest IS NOT NULL;
CREATE INDEX IF NOT EXISTS communities_created_by_idx
    ON public.communities (created_by) WHERE created_by IS NOT NULL;
ALTER TABLE public.communities ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.communities IS
    'Where a shared Take is judged (0432, N52.4): the one open general '
    'community and private ones a speaker set up with a name and a pass code. '
    'The pass code is never stored, only its keyed HMAC-SHA256 digest. A '
    'private community goes with the account of the speaker who set it up.';

INSERT INTO public.communities (kind)
SELECT 'general'
 WHERE NOT EXISTS (SELECT 1 FROM public.communities WHERE kind = 'general');

CREATE TABLE IF NOT EXISTS public.community_members (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    community_id uuid        NOT NULL REFERENCES public.communities (id) ON DELETE CASCADE,
    user_id      text        NOT NULL,
    role         text        NOT NULL DEFAULT 'member',
    joined_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT community_members_role_check CHECK (role IN ('owner', 'member')),
    CONSTRAINT community_members_once UNIQUE (community_id, user_id)
);
CREATE INDEX IF NOT EXISTS community_members_user_idx
    ON public.community_members (user_id);
ALTER TABLE public.community_members ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.community_members IS
    'Who belongs to a private community (0432, N52.4): the speaker who set '
    'it up (owner) and those who joined with its pass code (member). The '
    'general community has no rows here: it is open to everyone. Purged with '
    'the member.';

CREATE TABLE IF NOT EXISTS public.take_shares (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    take_session_id text        NOT NULL,
    owner_user_id   text        NOT NULL,
    community_id    uuid        NOT NULL REFERENCES public.communities (id) ON DELETE CASCADE,
    consent_version text        NOT NULL,
    shared_at       timestamptz NOT NULL DEFAULT now(),
    revoked_at      timestamptz NULL,
    CONSTRAINT take_shares_once UNIQUE (take_session_id, community_id)
);
CREATE INDEX IF NOT EXISTS take_shares_owner_idx
    ON public.take_shares (owner_user_id);
CREATE INDEX IF NOT EXISTS take_shares_live_idx
    ON public.take_shares (community_id) WHERE revoked_at IS NULL;
ALTER TABLE public.take_shares ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.take_shares IS
    'The speaker''s consent to share one Take with one community (0432, '
    'N52.4): per Take, stamped with the policy version the speaker accepted '
    '(consent_version); revoked_at withdraws it from that community''s queue, '
    'and "None" revokes every live row of the Take. Purged with the Take and '
    'with its owner.';

CREATE TABLE IF NOT EXISTS public.community_answers (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    clip_source      text        NOT NULL,
    community_id     uuid        NULL,
    listener_user_id text        NOT NULL,
    snippet_id       text        NULL,
    corpus_clip_id   text        NULL,
    take_session_id  text        NULL,
    value            text        NOT NULL,
    label_id         text        NULL,
    label_outcome    text        NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT community_answers_source_check CHECK (clip_source IN ('community', 'corpus')),
    CONSTRAINT community_answers_value_check
        CHECK (value IN ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear')),
    -- A community clip is a moment of a shared Take; a training clip is a
    -- licensed corpus clip, never a snippet, and never takes a label.
    CONSTRAINT community_answers_community_shape CHECK (
        clip_source <> 'community'
        OR (community_id IS NOT NULL AND snippet_id IS NOT NULL
            AND take_session_id IS NOT NULL AND corpus_clip_id IS NULL)),
    CONSTRAINT community_answers_corpus_shape CHECK (
        clip_source <> 'corpus'
        OR (corpus_clip_id IS NOT NULL AND snippet_id IS NULL AND community_id IS NULL
            AND take_session_id IS NULL AND label_id IS NULL AND label_outcome IS NULL)),
    CONSTRAINT community_answers_once UNIQUE (listener_user_id, snippet_id),
    CONSTRAINT community_answers_corpus_once UNIQUE (listener_user_id, corpus_clip_id)
);
CREATE INDEX IF NOT EXISTS community_answers_take_idx
    ON public.community_answers (take_session_id) WHERE take_session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS community_answers_created_idx
    ON public.community_answers (created_at);
ALTER TABLE public.community_answers ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.community_answers IS
    'One listener''s answer on one clip of their community queue (0432, '
    'N52.4): one per person per clip. A community clip''s answer is a PEER '
    'rating (L3) and also lands in confidence_labels under lane game_peer '
    'through the quorum''s access rule (label_outcome); a training clip from '
    'the licensed corpus keeps its answer here alone. Purged with the '
    'listener, and with the Take it is about.';

-- The queue reads this and nothing else: moments of Takes shared and not
-- revoked, in communities not closed. security_invoker, so the view never
-- reads snippets with its owner's rights (the hole
-- rename_charisma_snippets_to_snippets.sql warns about). The view needs
-- snippets, which predates migrations/; a database without it gets the
-- tables and a notice, never a failure.
DO $$
BEGIN
    IF to_regclass('public.snippets') IS NOT NULL THEN
        EXECUTE $view$
            CREATE OR REPLACE VIEW public.community_clips_live
                WITH (security_invoker = true) AS
                SELECT sn.id::text        AS snippet_id,
                       s.take_session_id,
                       s.community_id,
                       c.kind             AS community_kind,
                       s.owner_user_id,
                       s.shared_at
                  FROM public.take_shares s
                  JOIN public.communities c
                    ON c.id = s.community_id AND c.closed_at IS NULL
                  JOIN public.snippets sn
                    ON sn.session_id::text = s.take_session_id
                 WHERE s.revoked_at IS NULL
        $view$;
        REVOKE ALL ON public.community_clips_live FROM PUBLIC;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON public.community_clips_live FROM anon;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            REVOKE ALL ON public.community_clips_live FROM authenticated;
        END IF;
    ELSE
        RAISE NOTICE 'community_clips_live: public.snippets is not here; the view waits for it';
    END IF;
END $$;

-- Browser roles get nothing on the four tables, whatever default
-- privileges the schema carries: RLS with no policy already returns no row,
-- and this makes the boundary explicit. The app reads and writes them with
-- the service key, which keeps its privileges.
DO $$
DECLARE
    v_table text;
    v_role  text;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'communities', 'community_members', 'take_shares', 'community_answers'
    ] LOOP
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC', v_table);
        FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I', v_table, v_role);
            END IF;
        END LOOP;
    END LOOP;
END $$;

COMMIT;
