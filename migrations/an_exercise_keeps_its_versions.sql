-- 0399 · An exercise keeps its versions (founder 2026-09-29, decision 4;
-- build-order item 1, coach-panel authoring).
--
-- THE LIVE LIBRARY IS UPSERTED IN PLACE. diagnostic_exercise (the library the
-- matcher reads and the speaker's card plays from) has one row per exercise
-- id; `version` is a number the saver sets, and an edit overwrites the row.
-- An outcome must point at the exact version that was shown (0372 and 0387
-- store selected_exercise_version), and until now nothing stored what that
-- version WAS once the row moved on. The MLC-3 canonical catalogue has proper
-- version rows, but it is behind MLC3_SERVICE_ENABLED and needs a need
-- contract and a media object per version, so the live lane gets the small
-- table it needs beside it and keeps serving as it does.
--
-- ONE ROW PER (exercise, version), WRITTEN ONCE. Every save through the
-- catalogue service (the CMS, the coach panel, the answered call, the
-- practice review) bumps the live row's version when the definition or the
-- video changed and writes one version row holding the definition as saved,
-- the AI script draft if the coach asked for one, the coach's final text, the
-- video's lineage (url, sha256, size) and the transcript of the video, made
-- at upload through the authorized provider path under the coach's own
-- processing authorization. The three texts -- what the AI wrote, what the
-- coach said, and later which versions helped (module 8) -- are the corpus a
-- future script generator learns from; nothing learns from them yet, and no
-- learning surface is registered for them.
--
-- THE TRANSCRIPT ARRIVES ONCE. A version row is immutable except for one
-- transition: transcript_status 'pending' -> done / failed /
-- coach_authorization_missing, filling the transcript columns and nothing
-- else. Any other UPDATE raises.
--
-- Written only through its RPCs (R-1); service_role reads and, for erasure,
-- deletes. Coach content, not a speaker's recording: the table is product
-- vocabulary like diagnostic_exercise (NON_SUBJECT in the purge registry).
-- Internal. Nothing here reaches a speaker except through the live row it
-- mirrors. Additive and idempotent; no env var. Merging runs it on boot.

BEGIN;

CREATE TABLE IF NOT EXISTS public.diagnostic_exercise_version (
    id                            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    exercise_id                   TEXT        NOT NULL CHECK (length(exercise_id) > 0),
    version                       INTEGER     NOT NULL CHECK (version >= 1),
    title                         TEXT        NOT NULL,
    instruction                   TEXT        NOT NULL DEFAULT '',
    introduction_copy             TEXT        NOT NULL DEFAULT '',
    confident_introduction_copy   TEXT        NULL,
    acoustic_problem_tags         TEXT[]      NOT NULL DEFAULT '{}',
    supported_confidence_patterns TEXT[]      NOT NULL DEFAULT '{}',
    matching_criteria             JSONB       NOT NULL DEFAULT '{}'::jsonb,
    ai_draft_text                 TEXT        NULL,
    ai_draft_model_version        TEXT        NULL,
    explanation_video_url         TEXT        NULL,
    video_sha256                  TEXT        NULL
        CHECK (video_sha256 IS NULL OR video_sha256 ~ '^[0-9a-f]{64}$'),
    video_bytes                   INTEGER     NULL CHECK (video_bytes IS NULL OR video_bytes >= 0),
    transcript                    JSONB       NULL,
    transcript_language           TEXT        NULL,
    transcript_status             TEXT        NOT NULL DEFAULT 'not_requested'
        CHECK (transcript_status IN (
            'not_requested', 'pending', 'done', 'coach_authorization_missing',
            'failed')),
    source                        TEXT        NOT NULL
        CHECK (source IN ('cms', 'coach_panel', 'coach_request', 'coach_review')),
    created_by                    TEXT        NOT NULL DEFAULT '',
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (exercise_id, version),
    CHECK ((transcript_status = 'done') = (transcript IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_diagnostic_exercise_version_exercise
    ON public.diagnostic_exercise_version (exercise_id, version DESC);

ALTER TABLE public.diagnostic_exercise_version ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.diagnostic_exercise_version FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.diagnostic_exercise_version FROM service_role;
GRANT SELECT, DELETE ON public.diagnostic_exercise_version TO service_role;

-- Immutable, except the one transcript transition.
CREATE OR REPLACE FUNCTION public.guard_exercise_version_update_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    IF OLD.transcript_status <> 'pending'
       OR NEW.transcript_status NOT IN ('done', 'failed', 'coach_authorization_missing')
       OR NEW.id IS DISTINCT FROM OLD.id
       OR NEW.exercise_id IS DISTINCT FROM OLD.exercise_id
       OR NEW.version IS DISTINCT FROM OLD.version
       OR NEW.title IS DISTINCT FROM OLD.title
       OR NEW.instruction IS DISTINCT FROM OLD.instruction
       OR NEW.introduction_copy IS DISTINCT FROM OLD.introduction_copy
       OR NEW.confident_introduction_copy IS DISTINCT FROM OLD.confident_introduction_copy
       OR NEW.acoustic_problem_tags IS DISTINCT FROM OLD.acoustic_problem_tags
       OR NEW.supported_confidence_patterns IS DISTINCT FROM OLD.supported_confidence_patterns
       OR NEW.matching_criteria IS DISTINCT FROM OLD.matching_criteria
       OR NEW.ai_draft_text IS DISTINCT FROM OLD.ai_draft_text
       OR NEW.ai_draft_model_version IS DISTINCT FROM OLD.ai_draft_model_version
       OR NEW.explanation_video_url IS DISTINCT FROM OLD.explanation_video_url
       OR NEW.video_sha256 IS DISTINCT FROM OLD.video_sha256
       OR NEW.video_bytes IS DISTINCT FROM OLD.video_bytes
       OR NEW.source IS DISTINCT FROM OLD.source
       OR NEW.created_by IS DISTINCT FROM OLD.created_by
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'EXERCISE_VERSION_IMMUTABLE';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_exercise_version_update_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS diagnostic_exercise_version_immutable
    ON public.diagnostic_exercise_version;
CREATE TRIGGER diagnostic_exercise_version_immutable
    BEFORE UPDATE ON public.diagnostic_exercise_version
    FOR EACH ROW EXECUTE FUNCTION public.guard_exercise_version_update_v1();

-- The version row, written once. p_row carries the columns above except id
-- and created_at; a replay for an existing (exercise_id, version) returns the
-- stored row and writes nothing.
CREATE OR REPLACE FUNCTION public.record_exercise_version_v1(p_row JSONB)
RETURNS public.diagnostic_exercise_version
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    stored public.diagnostic_exercise_version;
    tags TEXT[];
    patterns TEXT[];
BEGIN
    IF p_row IS NULL OR jsonb_typeof(p_row) <> 'object'
       OR COALESCE(btrim(p_row->>'exercise_id'), '') = ''
       OR jsonb_typeof(p_row->'version') IS DISTINCT FROM 'number'
       OR COALESCE(btrim(p_row->>'title'), '') = ''
       OR p_row->>'source' IS NULL
    THEN
        RAISE EXCEPTION 'EXERCISE_VERSION_INPUT_INVALID';
    END IF;
    SELECT COALESCE(array_agg(value), '{}') INTO tags
      FROM jsonb_array_elements_text(COALESCE(p_row->'acoustic_problem_tags', '[]'::jsonb));
    SELECT COALESCE(array_agg(value), '{}') INTO patterns
      FROM jsonb_array_elements_text(COALESCE(p_row->'supported_confidence_patterns', '[]'::jsonb));

    INSERT INTO public.diagnostic_exercise_version (
        exercise_id, version, title, instruction, introduction_copy,
        confident_introduction_copy, acoustic_problem_tags,
        supported_confidence_patterns, matching_criteria, ai_draft_text,
        ai_draft_model_version, explanation_video_url, video_sha256,
        video_bytes, transcript, transcript_language, transcript_status,
        source, created_by
    ) VALUES (
        p_row->>'exercise_id', (p_row->>'version')::integer, p_row->>'title',
        COALESCE(p_row->>'instruction', ''), COALESCE(p_row->>'introduction_copy', ''),
        p_row->>'confident_introduction_copy', tags, patterns,
        COALESCE(p_row->'matching_criteria', '{}'::jsonb), p_row->>'ai_draft_text',
        p_row->>'ai_draft_model_version', p_row->>'explanation_video_url',
        p_row->>'video_sha256', (p_row->>'video_bytes')::integer,
        CASE WHEN jsonb_typeof(p_row->'transcript') = 'object' THEN p_row->'transcript' END,
        p_row->>'transcript_language',
        COALESCE(p_row->>'transcript_status', 'not_requested'),
        p_row->>'source', COALESCE(p_row->>'created_by', '')
    )
    ON CONFLICT (exercise_id, version) DO NOTHING;

    SELECT * INTO stored FROM public.diagnostic_exercise_version
     WHERE exercise_id = p_row->>'exercise_id'
       AND version = (p_row->>'version')::integer;
    RETURN stored;
END;
$$;
REVOKE ALL ON FUNCTION public.record_exercise_version_v1(JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_version_v1(JSONB) TO service_role;

-- The transcript's one arrival. Raises EXERCISE_VERSION_NOT_PENDING when the
-- row is not waiting for one (missing, or already settled).
CREATE OR REPLACE FUNCTION public.set_exercise_version_transcript_v1(
    p_exercise_id TEXT,
    p_version INTEGER,
    p_status TEXT,
    p_transcript JSONB,
    p_language TEXT
) RETURNS public.diagnostic_exercise_version
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    stored public.diagnostic_exercise_version;
BEGIN
    -- NULL-safe: a missing transcript must read as "no transcript", never as
    -- an unknown that lets a 'done' through to the table CHECK.
    IF p_status IS NULL
       OR p_status NOT IN ('done', 'failed', 'coach_authorization_missing')
       OR (p_status = 'done') <> COALESCE(jsonb_typeof(p_transcript) = 'object', false)
    THEN
        RAISE EXCEPTION 'EXERCISE_VERSION_INPUT_INVALID';
    END IF;
    UPDATE public.diagnostic_exercise_version
       SET transcript_status = p_status,
           transcript = CASE WHEN p_status = 'done' THEN p_transcript END,
           transcript_language = CASE WHEN p_status = 'done' THEN p_language END
     WHERE exercise_id = p_exercise_id
       AND version = p_version
       AND transcript_status = 'pending'
    RETURNING * INTO stored;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'EXERCISE_VERSION_NOT_PENDING';
    END IF;
    RETURN stored;
END;
$$;
REVOKE ALL ON FUNCTION public.set_exercise_version_transcript_v1(TEXT, INTEGER, TEXT, JSONB, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_exercise_version_transcript_v1(TEXT, INTEGER, TEXT, JSONB, TEXT)
    TO service_role;

COMMENT ON TABLE public.diagnostic_exercise_version IS
    'One immutable row per (exercise, version) of the live library: the definition as saved, the AI draft, the coach''s final, the video lineage and its transcript (founder 2026-09-29, decision 4). Nothing learns from it yet.';

COMMIT;
