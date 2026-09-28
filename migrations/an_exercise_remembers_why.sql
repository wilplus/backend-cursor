-- An exercise remembers why it was chosen (founder 2026-09-28, step 2 of the
-- exercise routing plan).
--
-- 0372 freezes WHICH exercise a moment got and the 80/20 draw. It does not
-- keep WHY: which problems fired on the clip, the measurements behind them,
-- the rules and library in force, and what happened to every other exercise
-- in the catalogue. Once a threshold moves, "why did this speaker get this
-- exercise?" has no answer, and the trials served since D5 could never be
-- compared fairly with exact fits.
--
-- ONE TRACE PER ASSIGNMENT, WRITTEN WITH IT. assign_confident_voice_exercise_v2
-- runs v1's draw and, only on the call that actually drew (the assignment
-- row was created in this transaction), writes the trace beside it. A replay
-- returns the frozen choice and writes nothing, so a trace can never be
-- recomputed later and passed off as the one the choice was made on. An
-- assignment drawn before this migration keeps no trace rather than a late
-- one.
--
-- THE TRACE MUST AGREE WITH THE DRAW. The function refuses a trace whose
-- ranked candidates are not exactly the pool handed to the draw, in order.
--
-- Internal only. The numbers in a trace are measurements, never shown to a
-- user (AC-9); no transcript text is copied into it. Nothing here is a
-- dataset, a label or a training input.
--
-- Additive and idempotent. No backfill, no env var.

BEGIN;

CREATE TABLE IF NOT EXISTS public.confident_voice_exercise_match_traces (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id           UUID        NOT NULL UNIQUE
        REFERENCES public.confident_voice_exercise_assignments(id)
        ON DELETE CASCADE,
    take_session_id         TEXT        NOT NULL CHECK (length(take_session_id) > 0),
    snippet_id              TEXT        NOT NULL CHECK (length(snippet_id) > 0),
    trace_schema_version    TEXT        NOT NULL
        CHECK (trace_schema_version = 'exercise-match-trace-v1'),
    matching_policy_version TEXT        NOT NULL CHECK (length(matching_policy_version) > 0),
    fit                     TEXT        NULL CHECK (fit IS NULL OR fit IN ('exact', 'trial')),
    trace                   JSONB       NOT NULL CHECK (
        jsonb_typeof(trace) = 'object'
        AND jsonb_typeof(trace->'candidates') = 'array'
        AND jsonb_typeof(trace->'observed_tags') = 'array'
        AND jsonb_typeof(trace->'signals') = 'object'
        AND jsonb_typeof(trace->'vocabulary') = 'array'
    ),
    trace_sha256            TEXT        NOT NULL CHECK (trace_sha256 ~ '^[0-9a-f]{64}$'),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cv_exercise_match_traces_take
    ON public.confident_voice_exercise_match_traces (take_session_id);

ALTER TABLE public.confident_voice_exercise_match_traces ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.confident_voice_exercise_match_traces
    FROM PUBLIC, anon, authenticated;
-- Written only by the function below; the server reads it and the purge
-- erases it. Nothing updates it.
REVOKE ALL ON public.confident_voice_exercise_match_traces FROM service_role;
GRANT SELECT, DELETE ON public.confident_voice_exercise_match_traces TO service_role;

-- Immutable once written. DELETE stays possible because erasure must be.
CREATE OR REPLACE FUNCTION public.reject_cv_exercise_match_trace_update_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    RAISE EXCEPTION 'CV_EXERCISE_MATCH_TRACE_IMMUTABLE';
END;
$$;
REVOKE ALL ON FUNCTION public.reject_cv_exercise_match_trace_update_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS cv_exercise_match_trace_immutable
    ON public.confident_voice_exercise_match_traces;
CREATE TRIGGER cv_exercise_match_trace_immutable
    BEFORE UPDATE ON public.confident_voice_exercise_match_traces
    FOR EACH ROW EXECUTE FUNCTION public.reject_cv_exercise_match_trace_update_v1();

-- p_trace: the caller's complete record of the match (schema
-- exercise-match-trace-v1). Its candidates with outcome 'ranked', ordered by
-- rank, must be exactly p_candidates.
CREATE OR REPLACE FUNCTION public.assign_confident_voice_exercise_v2(
    p_owner_user_id TEXT,
    p_take_session_id TEXT,
    p_snippet_id TEXT,
    p_lane TEXT,
    p_matching_policy_version TEXT,
    p_candidates JSONB,
    p_trace JSONB
) RETURNS public.confident_voice_exercise_assignments
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    assigned public.confident_voice_exercise_assignments;
    ranked TEXT[];
    pooled TEXT[];
BEGIN
    IF p_trace IS NULL OR jsonb_typeof(p_trace) <> 'object'
       OR p_trace->>'trace_schema' IS DISTINCT FROM 'exercise-match-trace-v1'
       OR jsonb_typeof(p_trace->'candidates') IS DISTINCT FROM 'array'
       OR (p_trace->>'fit') IS NOT NULL AND (p_trace->>'fit') NOT IN ('exact', 'trial')
       OR p_candidates IS NULL OR jsonb_typeof(p_candidates) <> 'array'
    THEN
        RAISE EXCEPTION 'CV_EXERCISE_MATCH_TRACE_INPUT_INVALID';
    END IF;

    SELECT array_agg(c->>'exercise_id' ORDER BY (c->>'rank')::integer)
      INTO ranked
      FROM jsonb_array_elements(p_trace->'candidates') AS c
     WHERE c->>'outcome' = 'ranked';
    SELECT array_agg(c->>'exercise_id' ORDER BY ord)
      INTO pooled
      FROM jsonb_array_elements(p_candidates) WITH ORDINALITY AS t(c, ord);
    IF ranked IS DISTINCT FROM pooled THEN
        RAISE EXCEPTION 'CV_EXERCISE_MATCH_TRACE_DISAGREES_WITH_POOL';
    END IF;

    assigned := public.assign_confident_voice_exercise_v1(
        p_owner_user_id, p_take_session_id, p_snippet_id, p_lane,
        p_matching_policy_version, p_candidates);

    -- Only the call that drew records why. created_at defaults to now(), the
    -- transaction's start, so equality means this transaction made the row.
    IF assigned.created_at = now() THEN
        INSERT INTO public.confident_voice_exercise_match_traces (
            assignment_id, take_session_id, snippet_id, trace_schema_version,
            matching_policy_version, fit, trace, trace_sha256
        ) VALUES (
            assigned.id, assigned.take_session_id, assigned.snippet_id,
            'exercise-match-trace-v1', assigned.matching_policy_version,
            p_trace->>'fit', p_trace,
            encode(extensions.digest(convert_to(p_trace::text, 'UTF8'), 'sha256'), 'hex')
        )
        ON CONFLICT (assignment_id) DO NOTHING;
    END IF;
    RETURN assigned;
END;
$$;

REVOKE ALL ON FUNCTION public.assign_confident_voice_exercise_v2(
    TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.assign_confident_voice_exercise_v2(
    TEXT, TEXT, TEXT, TEXT, TEXT, JSONB, JSONB) TO service_role;

COMMENT ON TABLE public.confident_voice_exercise_match_traces IS
    'Why one frozen exercise choice was made: the clip, the fired problems and '
    'their measurements, the rules and library in force, and every catalogue '
    'exercise ranked or excluded with its reason (founder 2026-09-28). Written '
    'once with the draw; never shown to a user.';

COMMIT;
