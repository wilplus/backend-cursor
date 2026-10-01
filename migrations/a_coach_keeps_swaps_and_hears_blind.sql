-- 0411 · a coach keeps, swaps and hears blind (founder 2026-10-01; the coach
-- panel's learning additions: 1b F8, 7 C5-a, 6a to 6d F6, 8 C5-b, task 4)
--
-- WHY. Five lanes, each dark behind its own constant, each append-only
-- with its own provenance, none mixed with another (L3):
--   coach_exercise_preference  F8: the coach kept, swapped or replaced the
--                              exercise the machine served (provenance
--                              coach_preference).
--   coach_clip_exposures       task 4: the first time a coach saw a clip's
--                              non-blind side; a later rating of theirs is
--                              not blind and counts for nothing.
--   error_presence_audit       F6: blind Yes/No per (clip, error), sampled
--                              with its probability; never shown to a
--                              speaker (provenance coach_audit).
--   coach_block_pick           C5-b: the coach's blind pick among a block's
--                              candidates; the Manager's pick stored, never
--                              sent (provenance coach_block_pick).
-- And five additive columns: confidence_labels.blind; the shadow log's
-- clip_kind (practice attempts as well as moments); the Take word's draft
-- and transcript; a pair may hang on a Take word; the surface checks take
-- the coach's two word surfaces (C5-a).
--
-- WHAT. Idempotent; additive; no env var; nothing is written while the
-- constants are False.
--
-- Rollback (a new forward migration): drop the four tables, the columns,
-- and narrow the two checks.

BEGIN;

CREATE TABLE IF NOT EXISTS public.coach_exercise_preference (
    id                       uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    take_session_id          text        NOT NULL,
    snippet_id               text        NOT NULL,
    coach_id                 text        NOT NULL,
    speaker_user_id          text        NOT NULL DEFAULT '',
    served_exercise_id       text        NOT NULL,
    served_exercise_version  integer     NULL,
    draw                     text        NOT NULL,
    fit                      text        NULL,
    fired_errors             jsonb       NOT NULL DEFAULT '[]'::jsonb,
    signal_rules_version     text        NULL,
    action                   text        NOT NULL,
    chosen_exercise_id       text        NULL,
    chosen_in_pool           boolean     NULL,
    provenance               text        NOT NULL DEFAULT 'coach_preference',
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coach_exercise_preference_draw_check
        CHECK (draw IN ('top', 'exploration', 'deterministic_singleton', 'fallback', 'coach_chosen')),
    CONSTRAINT coach_exercise_preference_action_check CHECK (action IN ('kept', 'swapped', 'new')),
    CONSTRAINT coach_exercise_preference_provenance_check CHECK (provenance = 'coach_preference')
);
CREATE INDEX IF NOT EXISTS coach_exercise_preference_served_idx
    ON public.coach_exercise_preference (served_exercise_id, draw);
ALTER TABLE public.coach_exercise_preference ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_exercise_preference IS
    'F8 (0411): the coach kept, swapped or replaced the exercise the machine '
    'served; append-only; may propose a ranking, never decides whether an '
    'exercise helps. Purged with the Take and with the coach.';

CREATE TABLE IF NOT EXISTS public.coach_clip_exposures (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id         text        NOT NULL,
    clip_id          text        NOT NULL,
    clip_kind        text        NOT NULL DEFAULT 'snippet',
    via              text        NOT NULL,
    first_exposed_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coach_clip_exposures_once UNIQUE (coach_id, clip_id),
    CONSTRAINT coach_clip_exposures_kind_check CHECK (clip_kind IN ('snippet', 'practice_attempt')),
    CONSTRAINT coach_clip_exposures_via_check
        CHECK (via IN ('moment_read', 'request', 'audit', 'block_pick', 'walk'))
);
ALTER TABLE public.coach_clip_exposures ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_clip_exposures IS
    'Task 4 (0411): the first time a coach saw a clip''s non-blind side. A '
    'later rating of theirs on it is not blind. Purged with the coach.';

CREATE TABLE IF NOT EXISTS public.error_presence_audit (
    id                   uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id             text        NOT NULL,
    clip_id              text        NOT NULL,
    clip_kind            text        NOT NULL DEFAULT 'snippet',
    take_session_id      text        NULL,
    speaker_user_id      text        NULL,
    error_id             text        NOT NULL,
    fired_at_sampling    boolean     NOT NULL,
    detector_version     text        NULL,
    signal_rules_version text        NULL,
    measurements         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    sampling_probability real        NULL,
    overlap              boolean     NOT NULL DEFAULT false,
    week                 text        NOT NULL,
    answer               text        NULL,
    answered_at          timestamptz NULL,
    provenance           text        NOT NULL DEFAULT 'coach_audit',
    created_at           timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT error_presence_audit_once UNIQUE (coach_id, clip_id, error_id),
    CONSTRAINT error_presence_audit_kind_check CHECK (clip_kind IN ('snippet', 'practice_attempt')),
    CONSTRAINT error_presence_audit_answer_check CHECK (answer IS NULL OR answer IN ('yes', 'no', 'cant_tell')),
    CONSTRAINT error_presence_audit_provenance_check CHECK (provenance = 'coach_audit')
);
CREATE INDEX IF NOT EXISTS error_presence_audit_error_idx
    ON public.error_presence_audit (error_id, answered_at);
CREATE INDEX IF NOT EXISTS error_presence_audit_coach_week_idx
    ON public.error_presence_audit (coach_id, week);
ALTER TABLE public.error_presence_audit ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.error_presence_audit IS
    'F6 (0411): a coach''s blind Yes/No about one error on one clip, sampled '
    'with its probability; fired_at_sampling is never shown. Never mixed with '
    'confidence labels, owner answers or detector verdicts. Purged with the '
    'Take and with the coach.';

CREATE TABLE IF NOT EXISTS public.coach_block_pick (
    id                      uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    coach_id                text        NOT NULL,
    take_session_id         text        NOT NULL,
    block_id                text        NOT NULL,
    candidate_snippet_ids   jsonb       NOT NULL DEFAULT '[]'::jsonb,
    manager_pick_snippet_id text        NOT NULL,
    pick_snippet_id         text        NULL,
    cant_tell               boolean     NOT NULL DEFAULT false,
    policy_version          text        NOT NULL,
    frame_policy_version    text        NULL,
    week                    text        NOT NULL,
    answered_at             timestamptz NULL,
    provenance              text        NOT NULL DEFAULT 'coach_block_pick',
    created_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT coach_block_pick_once UNIQUE (coach_id, block_id),
    CONSTRAINT coach_block_pick_provenance_check CHECK (provenance = 'coach_block_pick')
);
ALTER TABLE public.coach_block_pick ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_block_pick IS
    'C5-b (0411): the coach''s blind pick among a block''s candidate moments; '
    'the Manager''s pick is stored and never sent. Never changes a bookmark. '
    'Purged with the Take and with the coach.';

ALTER TABLE public.confidence_labels
    ADD COLUMN IF NOT EXISTS blind boolean NOT NULL DEFAULT true;
COMMENT ON COLUMN public.confidence_labels.blind IS
    'Task 4 (0411): false when the rater had seen this clip''s non-blind side '
    'before rating; such a row counts for no quorum, no Album leg, no measure.';

ALTER TABLE public.verbal_cue_shadow_observations
    ADD COLUMN IF NOT EXISTS clip_kind text NOT NULL DEFAULT 'snippet';
ALTER TABLE public.verbal_cue_shadow_observations
    DROP CONSTRAINT IF EXISTS verbal_cue_shadow_clip_kind_check;
ALTER TABLE public.verbal_cue_shadow_observations
    ADD CONSTRAINT verbal_cue_shadow_clip_kind_check
    CHECK (clip_kind IN ('snippet', 'practice_attempt'));

ALTER TABLE public.coach_take_words ADD COLUMN IF NOT EXISTS draft_text text NULL;
ALTER TABLE public.coach_take_words ADD COLUMN IF NOT EXISTS draft_model_version text NULL;
ALTER TABLE public.coach_take_words ADD COLUMN IF NOT EXISTS drafted_at timestamptz NULL;
ALTER TABLE public.coach_take_words ADD COLUMN IF NOT EXISTS transcript text NULL;
ALTER TABLE public.coach_take_words ADD COLUMN IF NOT EXISTS transcribed_at timestamptz NULL;
-- A draft may precede the word: the row then holds the draft alone until
-- the coach writes, and is never shared (shared_at stays NULL).
ALTER TABLE public.coach_take_words DROP CONSTRAINT IF EXISTS coach_take_words_something;
ALTER TABLE public.coach_take_words ADD CONSTRAINT coach_take_words_something CHECK (
    (text IS NOT NULL AND length(btrim(text)) > 0) OR video_ref IS NOT NULL
    OR draft_text IS NOT NULL);

ALTER TABLE public.feedback_pairs ADD COLUMN IF NOT EXISTS take_word_id text NULL;
ALTER TABLE public.feedback_pairs DROP CONSTRAINT IF EXISTS feedback_pairs_surface_check;
ALTER TABLE public.feedback_pairs ADD CONSTRAINT feedback_pairs_surface_check
    CHECK (surface IN ('praise_line', 'clearer_version', 'exercise_script',
                       'coach_moment_line', 'coach_take_word'));

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_draft_surface_check;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_draft_surface_check CHECK (
        draft_surface IS NULL
        OR draft_surface IN ('exercise_script', 'praise_line', 'clearer_version', 'coach_moment_line'));

-- The shadow log's writer learns the clip kind (practice attempts are
-- audited too); every earlier caller sends none and gets 'snippet'.
CREATE OR REPLACE FUNCTION public.record_verbal_cue_shadow_v1(p_rows JSONB)
RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    item JSONB;
    added INTEGER := 0;
    n INTEGER;
BEGIN
    IF p_rows IS NULL OR jsonb_typeof(p_rows) <> 'array' THEN
        RAISE EXCEPTION 'VERBAL_CUE_SHADOW_INPUT_INVALID';
    END IF;
    FOR item IN SELECT value FROM jsonb_array_elements(p_rows) LOOP
        IF jsonb_typeof(item) <> 'object'
           OR COALESCE(btrim(item->>'take_session_id'), '') = ''
           OR COALESCE(btrim(item->>'snippet_id'), '') = ''
           OR COALESCE(btrim(item->>'error_id'), '') = ''
           OR COALESCE(btrim(item->>'detector_version'), '') = ''
           OR COALESCE(btrim(item->>'language'), '') = ''
           OR jsonb_typeof(item->'fired') IS DISTINCT FROM 'boolean'
           OR jsonb_typeof(item->'measurements') IS DISTINCT FROM 'object'
        THEN
            RAISE EXCEPTION 'VERBAL_CUE_SHADOW_INPUT_INVALID';
        END IF;
        IF NOT EXISTS (
            SELECT 1 FROM public.speaking_error
             WHERE error_id = item->>'error_id'
               AND status IN ('shadow', 'detected')
        ) THEN
            RAISE EXCEPTION 'VERBAL_CUE_SHADOW_CUE_NOT_MEASURED';
        END IF;
        INSERT INTO public.verbal_cue_shadow_observations (
            take_session_id, snippet_id, recording_id, error_id,
            detector_version, language, fired, measurements, clip_kind
        ) VALUES (
            item->>'take_session_id', item->>'snippet_id',
            NULLIF(item->>'recording_id', ''), item->>'error_id',
            item->>'detector_version', item->>'language',
            (item->>'fired')::boolean, item->'measurements',
            COALESCE(NULLIF(item->>'clip_kind', ''), 'snippet')
        )
        ON CONFLICT (snippet_id, error_id, detector_version) DO NOTHING;
        GET DIAGNOSTICS n = ROW_COUNT;
        added := added + n;
    END LOOP;
    RETURN added;
END;
$$;
REVOKE ALL ON FUNCTION public.record_verbal_cue_shadow_v1(JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_verbal_cue_shadow_v1(JSONB) TO service_role;

COMMIT;
