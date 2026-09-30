-- A word for this Take (founder 2026-09-30, B3; build plan group 4: P2-5,
-- P2-11).
--
-- 1. THE TAKE-LEVEL WORD. With per-moment sharing the arc-level publish
--    gate has nothing left to gate. What remains is one optional message
--    and one optional video per Take, per coach, which the speaker reads
--    as "Your coach" (the sheet that exists) on the next read. One row per
--    (take, coach); a later save replaces it; `shared_at` is when it went
--    to the speaker. The arc-level publish and its delivery job are retired
--    with the removals (P2-19), not here: both mechanisms serve until then.
--
-- 2. AN ANSWER THAT IS A NOTE. An error without a video, and every
--    ambiguity, is answered in words that are neither a praise line nor a
--    clearer version: `note_written`, riding the moment only, never filed.
--
-- 3. AN ANSWER'S VIDEO. A praise line, a clearer version or a note may
--    carry a video for the speaker; it lives on the request row as
--    `answer_video_ref` and rides `coach_answer` when shared.
--
-- Nothing here reaches a speaker unshared; nothing is a score (AC-9).
-- Idempotent. No env var.

BEGIN;

-- ── 1. the take-level word ──────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.coach_take_words (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    take_session_id text        NOT NULL,
    coach_id        text        NOT NULL,
    text            text        NULL,
    video_ref       text        NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    shared_at       timestamptz NULL,
    CONSTRAINT coach_take_words_one_per_coach UNIQUE (take_session_id, coach_id),
    CONSTRAINT coach_take_words_text_len CHECK (text IS NULL OR length(text) <= 4000),
    CONSTRAINT coach_take_words_something CHECK (
        (text IS NOT NULL AND length(btrim(text)) > 0) OR video_ref IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS coach_take_words_shared_idx
    ON public.coach_take_words (take_session_id, shared_at DESC)
    WHERE shared_at IS NOT NULL;

ALTER TABLE public.coach_take_words ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.coach_take_words IS
    'One optional message and video per Take, per coach (founder 2026-09-30, '
    'B3). The speaker reads the latest shared one as "Your coach".';

-- ── 2. a note as an answer; 3. an answer''s video ───────────────────────

ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS answer_video_ref TEXT NULL;

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_resolution_values;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_resolution_values CHECK (
        resolution IS NULL OR resolution IN (
            'exercise_chosen', 'exercise_authored', 'no_safe_match',
            'line_written', 'version_written', 'note_written'));

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_resolution_shape;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_resolution_shape CHECK (
        (resolution IS NULL
         AND resolved_exercise_id IS NULL AND resolved_exercise_version IS NULL
         AND resolved_by IS NULL AND resolved_at IS NULL
         AND answer_text IS NULL)
        OR (resolution = 'no_safe_match'
            AND resolved_exercise_id IS NULL AND resolved_exercise_version IS NULL
            AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL
            AND answer_text IS NULL)
        OR (resolution IN ('exercise_chosen', 'exercise_authored')
            AND resolved_exercise_id IS NOT NULL AND resolved_exercise_version IS NOT NULL
            AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL
            AND answer_text IS NULL)
        OR (resolution IN ('line_written', 'version_written', 'note_written')
            AND resolved_exercise_id IS NULL AND resolved_exercise_version IS NULL
            AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL
            AND answer_text IS NOT NULL AND length(btrim(answer_text)) > 0)
    );

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_share_needs_answer;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_share_needs_answer CHECK (
        shared_at IS NULL
        OR resolution IN ('exercise_chosen', 'exercise_authored',
                          'line_written', 'version_written', 'note_written')
    );

CREATE OR REPLACE FUNCTION public.resolve_exercise_coach_request_v2(
    p_request_id UUID,
    p_coach_id TEXT,
    p_resolution TEXT,
    p_exercise_id TEXT,
    p_exercise_version INTEGER,
    p_share BOOLEAN,
    p_answer_text TEXT
) RETURNS public.exercise_coach_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    current_row public.exercise_coach_requests;
    in_words BOOLEAN := p_resolution IN ('line_written', 'version_written', 'note_written');
    with_exercise BOOLEAN := p_resolution IN ('exercise_chosen', 'exercise_authored');
    answer TEXT := NULLIF(btrim(p_answer_text), '');
BEGIN
    IF p_request_id IS NULL OR COALESCE(btrim(p_coach_id), '') = ''
       OR p_resolution IS NULL
       OR p_resolution NOT IN ('exercise_chosen', 'exercise_authored',
                               'no_safe_match', 'line_written', 'version_written',
                               'note_written')
       OR (p_resolution = 'no_safe_match'
           AND (p_exercise_id IS NOT NULL OR p_exercise_version IS NOT NULL
                OR COALESCE(p_share, false) OR answer IS NOT NULL))
       OR (with_exercise
           AND (COALESCE(btrim(p_exercise_id), '') = ''
                OR p_exercise_version IS NULL OR p_exercise_version < 1
                OR answer IS NOT NULL))
       OR (in_words
           AND (p_exercise_id IS NOT NULL OR p_exercise_version IS NOT NULL
                OR answer IS NULL))
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_INPUT_INVALID';
    END IF;

    SELECT * INTO current_row FROM public.exercise_coach_requests
     WHERE id = p_request_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_NOT_FOUND';
    END IF;

    IF current_row.resolution IS NULL THEN
        UPDATE public.exercise_coach_requests
           SET resolution = p_resolution,
               resolved_exercise_id = p_exercise_id,
               resolved_exercise_version = p_exercise_version,
               answer_text = answer,
               resolved_by = p_coach_id,
               resolved_at = now()
         WHERE id = p_request_id
        RETURNING * INTO current_row;
    ELSIF current_row.resolution IS DISTINCT FROM p_resolution
       OR current_row.resolved_exercise_id IS DISTINCT FROM p_exercise_id
       OR current_row.resolved_exercise_version IS DISTINCT FROM p_exercise_version
       OR current_row.answer_text IS DISTINCT FROM answer
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_ALREADY_RESOLVED';
    END IF;

    IF COALESCE(p_share, false) AND current_row.shared_at IS NULL THEN
        UPDATE public.exercise_coach_requests
           SET shared_at = now()
         WHERE id = p_request_id
        RETURNING * INTO current_row;
    END IF;
    RETURN current_row;
END;
$$;

REVOKE ALL ON FUNCTION public.resolve_exercise_coach_request_v2(
    UUID, TEXT, TEXT, TEXT, INTEGER, BOOLEAN, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_exercise_coach_request_v2(
    UUID, TEXT, TEXT, TEXT, INTEGER, BOOLEAN, TEXT) TO service_role;

COMMIT;
