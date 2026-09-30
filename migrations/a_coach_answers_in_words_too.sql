-- A coach answers in words too (founder 2026-09-30, C2, C4, C5, E5; build
-- plan group 2: P2-1, P2-2, P2-3, P2-7).
--
-- THREE THINGS, ONE MIGRATION, because they are one mechanism: the coach's
-- answer to a moment, the model's draft the answer started from, and the
-- pair the two make.
--
-- 1. THE REQUEST ANSWERED IN WORDS. A praise request is answered with a
--    line, a rewrite request with a clearer version: two new resolutions,
--    `line_written` and `version_written`, whose answer is `answer_text`.
--    Both may be shared with the speaker like an exercise is. The model's
--    draft the coach edited from is kept on the row (`draft_*`), coach-only,
--    never on a speaker payload. resolve_exercise_coach_request_v2 carries
--    the answer; v1 stays for callers that never send one.
--
-- 2. THE PAIRS. feedback_pairs holds one (draft, final) per answer where a
--    draft was shown and the final differs — the rule the service enforces
--    and the CHECK repeats. Stamped with the surface, the model version, the
--    pattern and the moment; `coach_id` is the author; `owner_user_id` names
--    whose passage the words are about, for the consent door later.
--    Never written from an owner's answer (only coach routes call it).
--    `exported_at` is for the weekly export, unset until then.
--
-- 3. THE COACH NAMES AN ERROR ON A MOMENT. coach_moment_error_event was
--    keyed by a practice row; the unified walk names a pattern on the
--    moment itself (take + snippet), so the row may carry either. The
--    shadow-cue validation reads both.
--
-- Nothing here reaches a speaker; nothing is a score (AC-9); a pair is
-- provenance, not a label (L3). Idempotent. No env var.

BEGIN;

-- ── 1. the request answered in words ────────────────────────────────────

ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS answer_text TEXT NULL;
ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS draft_text TEXT NULL;
ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS draft_model_version TEXT NULL;
ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS draft_surface TEXT NULL;
ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS drafted_at TIMESTAMPTZ NULL;

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_requests_resolution_check;
ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_resolution_values;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_resolution_values CHECK (
        resolution IS NULL OR resolution IN (
            'exercise_chosen', 'exercise_authored', 'no_safe_match',
            'line_written', 'version_written'));

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
        OR (resolution IN ('line_written', 'version_written')
            AND resolved_exercise_id IS NULL AND resolved_exercise_version IS NULL
            AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL
            AND answer_text IS NOT NULL AND length(btrim(answer_text)) > 0)
    );

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_share_needs_exercise;
ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_share_needs_answer;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_share_needs_answer CHECK (
        shared_at IS NULL
        OR resolution IN ('exercise_chosen', 'exercise_authored',
                          'line_written', 'version_written')
    );

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_draft_surface_check;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_draft_surface_check CHECK (
        draft_surface IS NULL
        OR draft_surface IN ('exercise_script', 'praise_line', 'clearer_version'));

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
    in_words BOOLEAN := p_resolution IN ('line_written', 'version_written');
    with_exercise BOOLEAN := p_resolution IN ('exercise_chosen', 'exercise_authored');
    answer TEXT := NULLIF(btrim(p_answer_text), '');
BEGIN
    IF p_request_id IS NULL OR COALESCE(btrim(p_coach_id), '') = ''
       OR p_resolution IS NULL
       OR p_resolution NOT IN ('exercise_chosen', 'exercise_authored',
                               'no_safe_match', 'line_written', 'version_written')
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

-- ── 2. the pairs ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.feedback_pairs (
    id                  uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    surface             text        NOT NULL,
    draft_text          text        NOT NULL,
    final_text          text        NOT NULL,
    final_kind          text        NOT NULL DEFAULT 'final',
    draft_model_version text        NULL,
    pattern_key         text        NULL,
    coach_id            text        NOT NULL,
    owner_user_id       text        NULL,
    take_session_id     text        NULL,
    snippet_id          text        NULL,
    request_id          uuid        NULL,
    exercise_id         text        NULL,
    exercise_version    integer     NULL,
    created_at          timestamptz NOT NULL DEFAULT now(),
    exported_at         timestamptz NULL,
    CONSTRAINT feedback_pairs_surface_check
        CHECK (surface IN ('praise_line', 'clearer_version', 'exercise_script')),
    CONSTRAINT feedback_pairs_final_kind_check
        CHECK (final_kind IN ('final', 'transcript')),
    CONSTRAINT feedback_pairs_texts_check
        CHECK (length(btrim(draft_text)) > 0 AND length(btrim(final_text)) > 0),
    CONSTRAINT feedback_pairs_differ_check
        CHECK (btrim(draft_text) <> btrim(final_text)),
    CONSTRAINT feedback_pairs_coach_check CHECK (length(btrim(coach_id)) > 0),
    CONSTRAINT feedback_pairs_one_home CHECK (request_id IS NOT NULL OR exercise_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS feedback_pairs_one_per_request
    ON public.feedback_pairs (surface, request_id) WHERE request_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS feedback_pairs_one_per_version
    ON public.feedback_pairs (surface, exercise_id, exercise_version, final_kind)
    WHERE exercise_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS feedback_pairs_unexported
    ON public.feedback_pairs (surface, created_at) WHERE exported_at IS NULL;

ALTER TABLE public.feedback_pairs ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE public.feedback_pairs IS
    'One (model draft, coach final) per coach answer where a draft was shown '
    'and the final differs (founder 2026-09-30, C5). Provenance for a later, '
    'separately authorised preference export; never a label, never shown.';

-- ── 3. a pattern named on the moment itself ─────────────────────────────
-- Degrades to a no-op where coach_moment_error_event does not exist (a
-- rehearsal lane without the exercise library); production has it (0392).

DO $$
BEGIN
    IF to_regclass('public.coach_moment_error_event') IS NULL THEN
        RETURN;
    END IF;
    ALTER TABLE public.coach_moment_error_event
        ALTER COLUMN practice_id DROP NOT NULL;
    ALTER TABLE public.coach_moment_error_event
        ADD COLUMN IF NOT EXISTS snippet_id TEXT NULL;
    ALTER TABLE public.coach_moment_error_event
        ADD COLUMN IF NOT EXISTS take_session_id TEXT NULL;
    ALTER TABLE public.coach_moment_error_event
        DROP CONSTRAINT IF EXISTS coach_moment_error_event_moment_check;
    ALTER TABLE public.coach_moment_error_event
        ADD CONSTRAINT coach_moment_error_event_moment_check
        CHECK (practice_id IS NOT NULL OR snippet_id IS NOT NULL);
    CREATE INDEX IF NOT EXISTS coach_moment_error_event_snippet_idx
        ON public.coach_moment_error_event (error_id, snippet_id, seq)
        WHERE snippet_id IS NOT NULL;
END;
$$;

COMMIT;
