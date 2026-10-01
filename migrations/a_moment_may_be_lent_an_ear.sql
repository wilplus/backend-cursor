-- 0410 · a moment may be lent an ear (founder 2026-10-01, F3, F4; Phases 4
-- and 5 of the after-practice paths)
--
-- WHY. F3: "A blind 'Lend your ear' step reopens the peer lane. Speakers
-- judge up to three short shared or licensed clips, audio only, never their
-- own, at most once per Take after a practice that lands. Their answers
-- count toward the coach + peer quorum. The retired Game stays retired."
-- F4: "Licensed corpus clips may be played to speakers, without names, in
-- 'Lend your ear' and 'Bold voices'." Phase 5: the delayed blind human
-- measure exercise-human-delayed-v1, defined in
-- docs/MEASURE-exercise-human-delayed-v1.md BEFORE any data.
--
-- WHAT. Tables for the share toggle (one live view both pools read, so a
-- revocation leaves both at once), the licensed corpus, the sets and the
-- answers, the measure's pairs and votes. Additive; idempotent; no env var.
-- DARK AND GATED: Config.PEER_LANE_ENABLED and Config.DELAYED_MEASURE_ENABLED
-- are False and stay so until counsel answers C1 to C3 and the founder signs
-- the measure; nothing is written until then.
--
-- Rollback (a new forward migration): drop the view and the six tables.

BEGIN;

CREATE TABLE IF NOT EXISTS public.voice_album_shares (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id   text        NOT NULL,
    arc_id          text        NOT NULL,
    snippet_id      text        NOT NULL,
    take_session_id text        NULL,
    shared_at       timestamptz NOT NULL DEFAULT now(),
    revoked_at      timestamptz NULL,
    CONSTRAINT voice_album_shares_one_per_moment UNIQUE (snippet_id)
);
ALTER TABLE public.voice_album_shares ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.voice_album_shares IS
    'The speaker lent this Voice Album moment to other ears (0410, F3): off '
    'by default, per recording, revocable; revoked_at withdraws it from both '
    'pools at once. Purged with the Take.';

-- Both pools read this and nothing else: shared, not revoked, still in the
-- Album (three yes). A moment that leaves the Album leaves the pools. The
-- view needs voice_album (add_voice_album.sql); a database without it (the
-- rehearsal's narrow lane) gets the tables and a notice, never a failure.
DO $$
BEGIN
    IF to_regclass('public.voice_album') IS NOT NULL THEN
        EXECUTE $view$
            CREATE OR REPLACE VIEW public.shared_clips_live AS
                SELECT s.snippet_id, s.owner_user_id, s.arc_id, s.take_session_id, s.shared_at
                  FROM public.voice_album_shares s
                  JOIN public.voice_album a
                    ON a.snippet_id = s.snippet_id AND a.arc_id::text = s.arc_id
                 WHERE s.revoked_at IS NULL
        $view$;
    ELSE
        RAISE NOTICE 'shared_clips_live: public.voice_album is not here; the view waits for it';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.corpus_clips (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    added_by     text        NOT NULL,
    licence      text        NOT NULL,
    passage      text        NOT NULL,
    audio_url    text        NOT NULL,
    duration_ms  integer     NULL,
    machine_stratum text     NULL,
    coach_value  text        NULL,
    coach_id     text        NULL,
    labelled_at  timestamptz NULL,
    active       boolean     NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT corpus_clips_coach_value_check CHECK (coach_value IS NULL OR coach_value IN ('yes', 'no')),
    CONSTRAINT corpus_clips_stratum_check CHECK (machine_stratum IS NULL OR machine_stratum IN ('confident', 'weak', 'unknown'))
);
ALTER TABLE public.corpus_clips ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.corpus_clips IS
    'The licensed corpus (0410, F4): clips a coach filed with their licence, '
    'played to speakers without names. Not about any speaker; the licence '
    'row says who may be asked to take one down.';

CREATE TABLE IF NOT EXISTS public.lend_your_ear_sets (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    listener_user_id text        NOT NULL,
    take_session_id  text        NOT NULL,
    clips            jsonb       NOT NULL DEFAULT '[]'::jsonb,
    size             integer     NOT NULL DEFAULT 0,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT lend_your_ear_sets_once_per_take UNIQUE (take_session_id)
);
ALTER TABLE public.lend_your_ear_sets ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.lend_your_ear_sets IS
    'The up-to-three clips one Take lent an ear to (0410, F3), in the order '
    'shown; once per Take. Purged with the listener''s Take.';

CREATE TABLE IF NOT EXISTS public.lend_your_ear_answers (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    set_id           uuid        NOT NULL,
    listener_user_id text        NOT NULL,
    clip_id          text        NOT NULL,
    clip_source      text        NOT NULL,
    pair_id          text        NULL,
    value            text        NOT NULL,
    label_id         text        NULL,
    label_outcome    text        NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT lend_your_ear_answers_source_check CHECK (clip_source IN ('shared', 'corpus', 'delayed')),
    CONSTRAINT lend_your_ear_answers_value_check
        CHECK (value IN ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear')),
    CONSTRAINT lend_your_ear_answers_once UNIQUE (listener_user_id, clip_id)
);
CREATE INDEX IF NOT EXISTS lend_your_ear_answers_created_idx
    ON public.lend_your_ear_answers (created_at);
ALTER TABLE public.lend_your_ear_answers ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.lend_your_ear_answers IS
    'One listener''s answer on one lent clip (0410, F3): one per person per '
    'clip. A shared recording''s answer also lands in confidence_labels under '
    'lane game_peer (label_id); a corpus or delayed-measure clip keeps its '
    'answer here alone. Purged with the listener.';

CREATE TABLE IF NOT EXISTS public.delayed_measure_pairs (
    id                 uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id        text        NOT NULL,
    owner_user_id      text        NOT NULL,
    take_session_id    text        NOT NULL,
    before_snippet_id  text        NOT NULL,
    after_attempt_id   text        NOT NULL,
    exercise_id        text        NULL,
    exercise_version   integer     NULL,
    measure_version    text        NOT NULL,
    practice_closed_at timestamptz NULL,
    status             text        NOT NULL DEFAULT 'open',
    created_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT delayed_measure_pairs_once UNIQUE (practice_id),
    CONSTRAINT delayed_measure_pairs_status_check CHECK (status IN ('open', 'closed'))
);
ALTER TABLE public.delayed_measure_pairs ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.delayed_measure_pairs IS
    'One practice, one pair (0410; exercise-human-delayed-v1): the original '
    'clip and the FIRST VALID attempt (F7), fixed when the practice closes. '
    'Purged with the Take.';

CREATE TABLE IF NOT EXISTS public.delayed_measure_votes (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    pair_id         uuid        NOT NULL,
    clip            text        NOT NULL,
    rater_id        text        NOT NULL,
    rater_kind      text        NOT NULL,
    value           text        NOT NULL,
    blind           boolean     NOT NULL DEFAULT true,
    measure_version text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT delayed_measure_votes_clip_check CHECK (clip IN ('before', 'after')),
    CONSTRAINT delayed_measure_votes_kind_check CHECK (rater_kind IN ('peer', 'coach')),
    CONSTRAINT delayed_measure_votes_value_check
        CHECK (value IN ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear')),
    CONSTRAINT delayed_measure_votes_once UNIQUE (pair_id, clip, rater_id)
);
ALTER TABLE public.delayed_measure_votes ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.delayed_measure_votes IS
    'One blind vote per rater per clip of a pair (0410; '
    'exercise-human-delayed-v1). Never the speaker, never the coach who '
    'handled the moment, never an exposed rater. Purged with the rater.';

COMMIT;
