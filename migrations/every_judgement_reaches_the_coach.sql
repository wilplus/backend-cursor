-- 0391 · every judgement reaches the coach, with its kind (founder 2026-09-29)
--
-- WHY. The follow-up matrix: every moment the speaker judges (all answers but
-- Audio unclear) goes to the coach as a request, tagged with why it came:
--   error      a delivery problem the detectors named, on a clip read weak
--   praise     the clip reads confident (the speaker agreed, or did better
--              than they thought)
--   rewrite    the clip reads weak and nothing acoustic fired: the words
--   ambiguity  the speaker and the machine disagree
-- The coach records a video for errors by default and may for the rest.
-- Until today a request was raised only where nothing in the library fitted;
-- now one is raised even where the library matched (reason
-- 'library_matched'), so the coach can add a video on top.
--
-- WHAT. One column with a default, one widened CHECK, one RPC that takes the
-- kind. Additive; every existing row is an 'error'. Idempotent. No env var.
--
-- Rollback (a new forward migration): drop request_exercise_from_coach_v2,
-- narrow the reason CHECK back, drop the kind column.

BEGIN;

ALTER TABLE public.exercise_coach_requests
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'error';

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_kind_check;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_kind_check
    CHECK (kind IN ('error', 'praise', 'rewrite', 'ambiguity'));

ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_requests_reason_check;
ALTER TABLE public.exercise_coach_requests
    DROP CONSTRAINT IF EXISTS exercise_coach_request_reason_check;
ALTER TABLE public.exercise_coach_requests
    ADD CONSTRAINT exercise_coach_request_reason_check
    CHECK (reason IN ('nothing_spotted', 'nothing_targets_it', 'library_matched'));

CREATE INDEX IF NOT EXISTS idx_exercise_coach_requests_open_kind
    ON public.exercise_coach_requests (kind, created_at)
    WHERE resolution IS NULL;

-- Insert-once, as v1; the kind and the widened reason are the difference.
CREATE OR REPLACE FUNCTION public.request_exercise_from_coach_v2(
    p_owner_user_id TEXT,
    p_take_session_id TEXT,
    p_snippet_id TEXT,
    p_reason TEXT,
    p_kind TEXT,
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
       OR p_reason IS NULL
       OR p_reason NOT IN ('nothing_spotted', 'nothing_targets_it', 'library_matched')
       OR p_kind IS NULL OR p_kind NOT IN ('error', 'praise', 'rewrite', 'ambiguity')
       OR p_request_trace IS NULL OR jsonb_typeof(p_request_trace) <> 'object'
    THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_INPUT_INVALID';
    END IF;
    INSERT INTO public.exercise_coach_requests (
        owner_user_id, take_session_id, snippet_id, reason, kind, pattern,
        observed_tags, request_trace
    ) VALUES (
        p_owner_user_id, p_take_session_id, p_snippet_id, p_reason, p_kind,
        p_pattern, COALESCE(p_observed_tags, '{}'::TEXT[]), p_request_trace
    )
    ON CONFLICT (take_session_id, snippet_id) DO NOTHING;
    SELECT * INTO found_row FROM public.exercise_coach_requests
     WHERE take_session_id = p_take_session_id AND snippet_id = p_snippet_id;
    RETURN found_row;
END;
$$;

REVOKE ALL ON FUNCTION public.request_exercise_from_coach_v2(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.request_exercise_from_coach_v2(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT[], JSONB) TO service_role;

COMMIT;
