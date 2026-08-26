-- 0293 · feedback-manager evidence, immutable self-reports, and paragraph
-- commit metadata.
--
-- One spoken Take has one frozen three-lane feedback set. Human responses are
-- immutable observations with explicit provenance; they are not gold labels.
-- Orange rooting phrases are exact spans on a locked paragraph, never marker
-- text baked into the Ideal Text itself.

BEGIN;

ALTER TABLE public.ideal_text_feedback_sets
    DROP CONSTRAINT IF EXISTS ideal_text_feedback_sets_keys_array;

ALTER TABLE public.ideal_text_feedback_sets
    ADD CONSTRAINT ideal_text_feedback_sets_keys_array CHECK (
        jsonb_typeof(selected_keys) = 'array'
        AND jsonb_array_length(selected_keys) = 3
        AND selected_keys @> '[{"feedback_family":"confident_voice"}]'::jsonb
        AND selected_keys @> '[{"feedback_family":"rewrite_clarity"}]'::jsonb
        AND selected_keys @> '[{"feedback_family":"great_formulation"}]'::jsonb
    ) NOT VALID;

-- Keep the transactional claim boundary as strict as the table. The original
-- RPC allowed 1..3 and only required Confident Voice; that would turn a
-- partial manager result into a durable terminal state before the new CHECK
-- had a chance to explain the real contract.
CREATE OR REPLACE FUNCTION public.claim_ideal_text_feedback_set_v1(
    p_arc_id TEXT,
    p_owner_user_id UUID,
    p_take_session_id UUID,
    p_take_index INTEGER,
    p_review_version INTEGER,
    p_selected_keys JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    s public.v2_sessions%ROWTYPE;
    claimed public.ideal_text_feedback_sets%ROWTYPE;
BEGIN
    IF jsonb_typeof(p_selected_keys) <> 'array'
       OR jsonb_array_length(p_selected_keys) <> 3
       OR NOT p_selected_keys @> '[{"feedback_family":"confident_voice"}]'::jsonb
       OR NOT p_selected_keys @> '[{"feedback_family":"rewrite_clarity"}]'::jsonb
       OR NOT p_selected_keys @> '[{"feedback_family":"great_formulation"}]'::jsonb THEN
        RAISE EXCEPTION 'feedback set requires exactly one complete three-family set';
    END IF;
    IF p_review_version IS DISTINCT FROM p_take_index THEN
        RAISE EXCEPTION 'review version must equal Take index';
    END IF;
    SELECT * INTO s FROM public.v2_sessions WHERE id = p_take_session_id;
    IF s.id IS NULL THEN RAISE EXCEPTION 'Take not found'; END IF;
    IF s.user_id IS DISTINCT FROM p_owner_user_id
       OR s.arc_id::text IS DISTINCT FROM p_arc_id
       OR s.take_index IS DISTINCT FROM p_take_index THEN
        RAISE EXCEPTION 'feedback set provenance mismatch';
    END IF;
    IF COALESCE(s.recording_kind, 'spoken') <> 'spoken'
       OR s.paired_session_id IS NOT NULL THEN
        RAISE EXCEPTION 'feedback set requires a spoken Take';
    END IF;
    SELECT * INTO claimed FROM public.ideal_text_feedback_sets
     WHERE arc_id = p_arc_id AND take_session_id = p_take_session_id;
    IF claimed.arc_id IS NULL THEN
        INSERT INTO public.ideal_text_feedback_sets (
            arc_id, take_session_id, take_index, review_version, selected_keys
        ) VALUES (
            p_arc_id, p_take_session_id, p_take_index,
            p_review_version, p_selected_keys
        ) ON CONFLICT DO NOTHING;
        SELECT * INTO claimed FROM public.ideal_text_feedback_sets
         WHERE arc_id = p_arc_id
           AND (take_session_id = p_take_session_id
                OR review_version = p_review_version)
         ORDER BY created_at LIMIT 1;
    END IF;
    IF claimed.arc_id IS NULL THEN
        RAISE EXCEPTION 'feedback set could not be claimed';
    END IF;
    IF claimed.take_session_id IS DISTINCT FROM p_take_session_id
       OR claimed.take_index IS DISTINCT FROM p_take_index
       OR claimed.review_version IS DISTINCT FROM p_review_version THEN
        RAISE EXCEPTION 'feedback set claim conflicts with Take provenance';
    END IF;
    RETURN to_jsonb(claimed);
END;
$$;

ALTER TABLE public.ideal_text_part
    ADD COLUMN IF NOT EXISTS root_phrase TEXT NULL,
    ADD COLUMN IF NOT EXISTS root_start INTEGER NULL,
    ADD COLUMN IF NOT EXISTS root_end INTEGER NULL,
    ADD COLUMN IF NOT EXISTS root_selected_at TIMESTAMPTZ NULL;

ALTER TABLE public.ideal_text_part
    DROP CONSTRAINT IF EXISTS ideal_text_part_root_span;
ALTER TABLE public.ideal_text_part
    ADD CONSTRAINT ideal_text_part_root_span CHECK (
        (root_phrase IS NULL AND root_start IS NULL AND root_end IS NULL
         AND root_selected_at IS NULL)
        OR
        (root_phrase IS NOT NULL AND length(root_phrase) > 0
         AND root_start IS NOT NULL AND root_start >= 0
         AND root_end IS NOT NULL AND root_end > root_start
         AND root_selected_at IS NOT NULL)
    );

CREATE TABLE IF NOT EXISTS public.take_feedback_exposure (
    arc_id             TEXT        NOT NULL,
    take_session_id    UUID        NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
    review_version     INTEGER     NOT NULL CHECK (review_version >= 1),
    policy_version     TEXT        NOT NULL,
    model_version      TEXT        NULL,
    prompt_version     TEXT        NULL,
    candidate_set      JSONB       NOT NULL CHECK (
        jsonb_typeof(candidate_set) = 'array'
    ),
    selected_keys      JSONB       NOT NULL CHECK (
        jsonb_typeof(selected_keys) = 'array'
        AND jsonb_array_length(selected_keys) = 3
    ),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arc_id, take_session_id)
);

CREATE TABLE IF NOT EXISTS public.take_feedback_self_report (
    id                 BIGSERIAL   PRIMARY KEY,
    arc_id             TEXT        NOT NULL,
    take_session_id    UUID        NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
    owner_user_id      UUID        NOT NULL,
    feedback_id        TEXT        NOT NULL,
    feedback_family    TEXT        NOT NULL CHECK (feedback_family IN (
        'confident_voice', 'rewrite_clarity', 'great_formulation'
    )),
    snippet_id         UUID        NULL,
    response           TEXT        NOT NULL,
    provenance         TEXT        NOT NULL DEFAULT 'user_self_report'
        CHECK (provenance = 'user_self_report'),
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT take_feedback_self_report_response CHECK (
        (feedback_family = 'confident_voice' AND response IN (
            'yes', 'in_between', 'no', 'not_sure', 'audio_unclear'
        )) OR
        (feedback_family = 'rewrite_clarity' AND response IN (
            'apply_suggestion', 'edit_myself', 'keep_wording'
        )) OR
        (feedback_family = 'great_formulation' AND response IN (
            'useful', 'not_useful', 'not_sure'
        ))
    ),
    UNIQUE (take_session_id, owner_user_id, feedback_id)
);

CREATE INDEX IF NOT EXISTS take_feedback_self_report_clip_idx
    ON public.take_feedback_self_report (snippet_id, created_at DESC)
    WHERE snippet_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.ideal_text_part_revision (
    id                 BIGSERIAL   PRIMARY KEY,
    arc_id             TEXT        NOT NULL,
    user_id            TEXT        NOT NULL,
    part_id            UUID        NOT NULL,
    action             TEXT        NOT NULL CHECK (action IN (
        'user_edit', 'lock', 'unlock', 'keep_evolving',
        'root_set', 'root_skipped'
    )),
    text               TEXT        NOT NULL,
    root_phrase        TEXT        NULL,
    take_session_id    UUID        NULL,
    review_version     INTEGER     NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.take_feedback_exposure ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.take_feedback_self_report ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ideal_text_part_revision ENABLE ROW LEVEL SECURITY;

-- These records are append-only evidence. Corrections are new rows; history
-- is never edited into a different event after somebody acted on it.
CREATE OR REPLACE FUNCTION public.reject_immutable_feedback_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'immutable feedback evidence cannot be changed';
END;
$$;

REVOKE ALL ON FUNCTION public.claim_ideal_text_feedback_set_v1(
    TEXT, UUID, UUID, INTEGER, INTEGER, JSONB
) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.claim_ideal_text_feedback_set_v1(
    TEXT, UUID, UUID, INTEGER, INTEGER, JSONB
) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_ideal_text_feedback_set_v1(
    TEXT, UUID, UUID, INTEGER, INTEGER, JSONB
) TO service_role;
REVOKE ALL ON FUNCTION public.reject_immutable_feedback_mutation()
    FROM PUBLIC;
REVOKE ALL ON FUNCTION public.reject_immutable_feedback_mutation()
    FROM anon, authenticated;

DROP TRIGGER IF EXISTS take_feedback_exposure_immutable
    ON public.take_feedback_exposure;
CREATE TRIGGER take_feedback_exposure_immutable
    BEFORE UPDATE OR DELETE ON public.take_feedback_exposure
    FOR EACH ROW EXECUTE FUNCTION public.reject_immutable_feedback_mutation();

DROP TRIGGER IF EXISTS take_feedback_self_report_immutable
    ON public.take_feedback_self_report;
CREATE TRIGGER take_feedback_self_report_immutable
    BEFORE UPDATE OR DELETE ON public.take_feedback_self_report
    FOR EACH ROW EXECUTE FUNCTION public.reject_immutable_feedback_mutation();

DROP TRIGGER IF EXISTS ideal_text_part_revision_immutable
    ON public.ideal_text_part_revision;
CREATE TRIGGER ideal_text_part_revision_immutable
    BEFORE UPDATE OR DELETE ON public.ideal_text_part_revision
    FOR EACH ROW EXECUTE FUNCTION public.reject_immutable_feedback_mutation();

GRANT ALL ON TABLE public.take_feedback_exposure TO service_role;
GRANT ALL ON TABLE public.take_feedback_self_report TO service_role;
GRANT ALL ON TABLE public.ideal_text_part_revision TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.take_feedback_self_report_id_seq
    TO service_role;
GRANT USAGE, SELECT ON SEQUENCE public.ideal_text_part_revision_id_seq
    TO service_role;

COMMIT;
