-- A coach hears when no exercise fits (founder 2026-09-28; contract 35b, 35f).
--
-- Since D1 an exercise is offered only when a detected problem fired on the
-- clip and something in the library targets it. When V3's exercise item
-- finds nothing, the speaker keeps "Let's practice" alone — and until now
-- nobody heard about it, because every coach surface hung off a practice,
-- which only exists once the speaker taps an offered exercise.
--
-- ONE REQUEST PER (TAKE, MOMENT). Written by the feedback build, which runs
-- again on every poll, so the write is insert-once: the first call records
-- the request and why (nothing_spotted, or nothing_targets_it), every later
-- call returns that row. The speaker never waits on it (live loop).
--
-- THE COACH RESOLVES IT ONCE, after their own blind rating of the moment (the
-- route enforces the gate). exercise_chosen names a library exercise;
-- exercise_authored names one the coach just filed into the library;
-- no_safe_match says there is none. Sharing with the speaker is a separate,
-- explicit act (35f) and only an exercise can be shared. Once set, a
-- resolution and a share never change; what was requested never changes.
--
-- Internal. Nothing here is a label or a training input, and no number from
-- it reaches the speaker (AC-9). Additive and idempotent. No env var.

BEGIN;

CREATE TABLE IF NOT EXISTS public.exercise_coach_requests (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id             TEXT        NOT NULL CHECK (length(owner_user_id) > 0),
    take_session_id           TEXT        NOT NULL CHECK (length(take_session_id) > 0),
    snippet_id                TEXT        NOT NULL CHECK (length(snippet_id) > 0),
    reason                    TEXT        NOT NULL
        CHECK (reason IN ('nothing_spotted', 'nothing_targets_it')),
    pattern                   TEXT        NULL,
    observed_tags             TEXT[]      NOT NULL DEFAULT '{}',
    request_trace             JSONB       NOT NULL CHECK (jsonb_typeof(request_trace) = 'object'),
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolution                TEXT        NULL CHECK (resolution IS NULL OR resolution IN (
        'exercise_chosen', 'exercise_authored', 'no_safe_match')),
    resolved_exercise_id      TEXT        NULL,
    resolved_exercise_version INTEGER     NULL CHECK (
        resolved_exercise_version IS NULL OR resolved_exercise_version >= 1),
    resolved_by               TEXT        NULL,
    resolved_at               TIMESTAMPTZ NULL,
    shared_at                 TIMESTAMPTZ NULL,
    CONSTRAINT exercise_coach_request_unit UNIQUE (take_session_id, snippet_id),
    CONSTRAINT exercise_coach_request_resolution_shape CHECK (
        (resolution IS NULL
         AND resolved_exercise_id IS NULL AND resolved_exercise_version IS NULL
         AND resolved_by IS NULL AND resolved_at IS NULL)
        OR (resolution = 'no_safe_match'
            AND resolved_exercise_id IS NULL AND resolved_exercise_version IS NULL
            AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL)
        OR (resolution IN ('exercise_chosen', 'exercise_authored')
            AND resolved_exercise_id IS NOT NULL AND resolved_exercise_version IS NOT NULL
            AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL)
    ),
    CONSTRAINT exercise_coach_request_share_needs_exercise CHECK (
        shared_at IS NULL
        OR resolution IN ('exercise_chosen', 'exercise_authored')
    )
);

CREATE INDEX IF NOT EXISTS idx_exercise_coach_requests_open
    ON public.exercise_coach_requests (created_at)
    WHERE resolution IS NULL;

ALTER TABLE public.exercise_coach_requests ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.exercise_coach_requests FROM PUBLIC, anon, authenticated;
-- Written only by the two functions below; the server reads it and the purge
-- erases it.
REVOKE ALL ON public.exercise_coach_requests FROM service_role;
GRANT SELECT, DELETE ON public.exercise_coach_requests TO service_role;

-- What was requested never changes; a resolution and a share are set once.
CREATE OR REPLACE FUNCTION public.guard_exercise_coach_request_update_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.take_session_id IS DISTINCT FROM OLD.take_session_id
       OR NEW.snippet_id IS DISTINCT FROM OLD.snippet_id
       OR NEW.reason IS DISTINCT FROM OLD.reason
       OR NEW.pattern IS DISTINCT FROM OLD.pattern
       OR NEW.observed_tags IS DISTINCT FROM OLD.observed_tags
       OR NEW.request_trace IS DISTINCT FROM OLD.request_trace
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_IMMUTABLE';
    END IF;
    IF OLD.resolution IS NOT NULL AND (
        NEW.resolution IS DISTINCT FROM OLD.resolution
        OR NEW.resolved_exercise_id IS DISTINCT FROM OLD.resolved_exercise_id
        OR NEW.resolved_exercise_version IS DISTINCT FROM OLD.resolved_exercise_version
        OR NEW.resolved_by IS DISTINCT FROM OLD.resolved_by
        OR NEW.resolved_at IS DISTINCT FROM OLD.resolved_at)
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_ALREADY_RESOLVED';
    END IF;
    IF OLD.shared_at IS NOT NULL AND NEW.shared_at IS DISTINCT FROM OLD.shared_at THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_ALREADY_SHARED';
    END IF;
    RETURN NEW;
END;
$$;
REVOKE ALL ON FUNCTION public.guard_exercise_coach_request_update_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS exercise_coach_request_guard
    ON public.exercise_coach_requests;
CREATE TRIGGER exercise_coach_request_guard
    BEFORE UPDATE ON public.exercise_coach_requests
    FOR EACH ROW EXECUTE FUNCTION public.guard_exercise_coach_request_update_v1();

-- Insert-once: the first call records the request, every later call returns
-- it unchanged (with whatever resolution it has since gained).
CREATE OR REPLACE FUNCTION public.request_exercise_from_coach_v1(
    p_owner_user_id TEXT,
    p_take_session_id TEXT,
    p_snippet_id TEXT,
    p_reason TEXT,
    p_pattern TEXT,
    p_observed_tags TEXT[],
    p_request_trace JSONB
) RETURNS public.exercise_coach_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    found_row public.exercise_coach_requests;
BEGIN
    IF COALESCE(btrim(p_owner_user_id), '') = ''
       OR COALESCE(btrim(p_take_session_id), '') = ''
       OR COALESCE(btrim(p_snippet_id), '') = ''
       OR p_reason IS NULL OR p_reason NOT IN ('nothing_spotted', 'nothing_targets_it')
       OR p_request_trace IS NULL OR jsonb_typeof(p_request_trace) <> 'object'
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_INPUT_INVALID';
    END IF;
    INSERT INTO public.exercise_coach_requests (
        owner_user_id, take_session_id, snippet_id, reason, pattern,
        observed_tags, request_trace
    ) VALUES (
        p_owner_user_id, p_take_session_id, p_snippet_id, p_reason, p_pattern,
        COALESCE(p_observed_tags, '{}'::TEXT[]), p_request_trace
    )
    ON CONFLICT (take_session_id, snippet_id) DO NOTHING;
    SELECT * INTO found_row FROM public.exercise_coach_requests
     WHERE take_session_id = p_take_session_id AND snippet_id = p_snippet_id;
    RETURN found_row;
END;
$$;

REVOKE ALL ON FUNCTION public.request_exercise_from_coach_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.request_exercise_from_coach_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], JSONB) TO service_role;

-- Resolve once, share once. Repeating the resolution already recorded is
-- harmless (a double-submit); a different one is refused. p_share on an
-- exercise resolution records the share if it has not happened yet.
CREATE OR REPLACE FUNCTION public.resolve_exercise_coach_request_v1(
    p_request_id UUID,
    p_coach_id TEXT,
    p_resolution TEXT,
    p_exercise_id TEXT,
    p_exercise_version INTEGER,
    p_share BOOLEAN
) RETURNS public.exercise_coach_requests
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    current_row public.exercise_coach_requests;
BEGIN
    IF p_request_id IS NULL OR COALESCE(btrim(p_coach_id), '') = ''
       OR p_resolution IS NULL
       OR p_resolution NOT IN ('exercise_chosen', 'exercise_authored', 'no_safe_match')
       OR (p_resolution = 'no_safe_match'
           AND (p_exercise_id IS NOT NULL OR p_exercise_version IS NOT NULL
                OR COALESCE(p_share, false)))
       OR (p_resolution <> 'no_safe_match'
           AND (COALESCE(btrim(p_exercise_id), '') = ''
                OR p_exercise_version IS NULL OR p_exercise_version < 1))
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
               resolved_by = p_coach_id,
               resolved_at = now()
         WHERE id = p_request_id
        RETURNING * INTO current_row;
    ELSIF current_row.resolution IS DISTINCT FROM p_resolution
       OR current_row.resolved_exercise_id IS DISTINCT FROM p_exercise_id
       OR current_row.resolved_exercise_version IS DISTINCT FROM p_exercise_version
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

REVOKE ALL ON FUNCTION public.resolve_exercise_coach_request_v1(
    UUID, TEXT, TEXT, TEXT, INTEGER, BOOLEAN) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_exercise_coach_request_v1(
    UUID, TEXT, TEXT, TEXT, INTEGER, BOOLEAN) TO service_role;

COMMENT ON TABLE public.exercise_coach_requests IS
    'One request per (Take, moment) where V3''s exercise item found no '
    'exercise, and the coach''s one resolution of it after their blind '
    'rating (founder 2026-09-28; contract 35b, 35f). Never shown to a user.';

COMMIT;
