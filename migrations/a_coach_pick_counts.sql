-- 0398 · A coach's pick counts (founder 2026-09-29, decision 3).
--
-- THE JAR COUNTS ONLY JOINED RECORDS. A practice teaches the exercise learner
-- only when a seen exercise, on an exact clip, is joined to its outcome by
-- the exact version shown: the frozen 80/20 assignment (0372), its match
-- trace (0384) and the client's confirmed render (0387). Only exercises the
-- machine picked wrote those three rows. A coach shares an exercise two ways
-- -- answering the call for one when nothing fitted (0385), riding on the
-- same V3 item; or attaching one in the practice review -- and neither wrote
-- any of the three, and record_exercise_rendered_v1 refused a coach-shared
-- card by design. The coach's picks, which are exactly the ones filling the
-- library's gaps, never counted.
--
-- THE SAME THREE ROWS, UNDER A COACH POLICY NAME. A coach-shared exercise
-- gets an assignment with exposure_policy_version 'exercise-coach-shared-v1'
-- and selection_mode 'coach_chosen' (a singleton: one candidate, rank 1, no
-- seed, no draw, rng 'none'), a trace whose one candidate carries outcome
-- 'coach_chosen' and the exercise's main and secondary targets, and a render
-- receipt when the card is on screen. The unique index on (Take, moment,
-- policy) lets a coach row sit beside an 80/20 row on the same moment, and
-- every reader can tell them apart by the policy name and the mode: the
-- readiness count shows them as their own line, the ranked pool (outcome =
-- 'ranked') never contains them, and the fair test leaves them out. Nothing
-- about the coach's choice is folded into the machine's draw (L3).
--
-- assign_coach_shared_exercise_v1 writes the assignment and its trace in one
-- transaction, insert-once: a replay returns the frozen row and writes
-- nothing. record_exercise_rendered_v2 finds the assignment whose selected
-- exercise is the rendered one, under any policy, and refuses as v1 does
-- otherwise; v1 stays for callers that name it.
--
-- Internal. No number here reaches a user (AC-9); nothing here is a label.
-- Additive and idempotent: the CHECKs are dropped by their current
-- definition and re-added by name; existing rows are untouched. No env var.
-- Merging runs it on the next container start.

BEGIN;

-- ── The assignment table accepts the coach shape ─────────────────────────

DO $$
DECLARE
    c RECORD;
BEGIN
    FOR c IN
        SELECT conname
          FROM pg_constraint
         WHERE conrelid = 'public.confident_voice_exercise_assignments'::regclass
           AND contype = 'c'
           AND (pg_get_constraintdef(oid) LIKE '%exercise-80-20-v1%'
                OR pg_get_constraintdef(oid) LIKE '%v3_exercise_block%'
                OR pg_get_constraintdef(oid) LIKE '%deterministic_singleton%')
    LOOP
        EXECUTE format(
            'ALTER TABLE public.confident_voice_exercise_assignments '
            'DROP CONSTRAINT %I', c.conname);
    END LOOP;
END;
$$;

ALTER TABLE public.confident_voice_exercise_assignments
    ADD CONSTRAINT cv_exercise_assignment_policy_check CHECK (
        exposure_policy_version IN (
            'exercise-80-20-v1', 'exercise-coach-shared-v1'));
ALTER TABLE public.confident_voice_exercise_assignments
    ADD CONSTRAINT cv_exercise_assignment_lane_check CHECK (
        lane IN ('v3_exercise_block', 'legacy_offer',
                 'coach_request', 'coach_review'));
ALTER TABLE public.confident_voice_exercise_assignments
    ADD CONSTRAINT cv_exercise_assignment_mode_check CHECK (
        selection_mode IN ('deterministic_singleton', 'top', 'exploration',
                           'coach_chosen'));
-- A singleton and a coach pick are not randomized: no seed, no draw.
-- Anything else is.
ALTER TABLE public.confident_voice_exercise_assignments
    ADD CONSTRAINT cv_exercise_assignment_shape_check CHECK (
        (selection_mode IN ('deterministic_singleton', 'coach_chosen')
         AND candidate_count = 1
         AND protected_seed IS NULL AND seed_commitment_sha256 IS NULL
         AND draw IS NULL)
        OR
        (selection_mode NOT IN ('deterministic_singleton', 'coach_chosen')
         AND candidate_count >= 2
         AND protected_seed IS NOT NULL AND draw IS NOT NULL
         AND seed_commitment_sha256 ~ '^[0-9a-f]{64}$')
    );
-- A coach pick is only ever made under the coach policy, and the coach
-- policy only ever holds a coach pick.
ALTER TABLE public.confident_voice_exercise_assignments
    DROP CONSTRAINT IF EXISTS cv_exercise_assignment_coach_policy_check;
ALTER TABLE public.confident_voice_exercise_assignments
    ADD CONSTRAINT cv_exercise_assignment_coach_policy_check CHECK (
        (selection_mode = 'coach_chosen')
        = (exposure_policy_version = 'exercise-coach-shared-v1'));

-- ── The coach's pick, frozen once with its trace ─────────────────────────

-- p_lane: 'coach_request' (the call answered, 0385) or 'coach_review' (the
-- practice review's share). p_matching_policy_version names which. p_trace:
-- schema exercise-match-trace-v1 with exactly one candidate, outcome
-- 'coach_chosen', naming p_exercise_id. Returns the assignment; a replay
-- returns the frozen one and writes nothing.
CREATE OR REPLACE FUNCTION public.assign_coach_shared_exercise_v1(
    p_owner_user_id TEXT,
    p_take_session_id TEXT,
    p_snippet_id TEXT,
    p_lane TEXT,
    p_matching_policy_version TEXT,
    p_exercise_id TEXT,
    p_exercise_version INTEGER,
    p_trace JSONB
) RETURNS public.confident_voice_exercise_assignments
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    policy CONSTANT TEXT := 'exercise-coach-shared-v1';
    existing public.confident_voice_exercise_assignments;
    created public.confident_voice_exercise_assignments;
    pool JSONB;
BEGIN
    IF COALESCE(btrim(p_owner_user_id), '') = ''
       OR COALESCE(btrim(p_take_session_id), '') = ''
       OR COALESCE(btrim(p_snippet_id), '') = ''
       OR p_lane IS NULL OR p_lane NOT IN ('coach_request', 'coach_review')
       OR COALESCE(btrim(p_matching_policy_version), '') = ''
       OR COALESCE(btrim(p_exercise_id), '') = ''
       OR p_exercise_version IS NULL OR p_exercise_version < 1
    THEN
        RAISE EXCEPTION 'CV_EXERCISE_ASSIGNMENT_INPUT_INVALID';
    END IF;
    IF p_trace IS NULL OR jsonb_typeof(p_trace) <> 'object'
       OR p_trace->>'trace_schema' IS DISTINCT FROM 'exercise-match-trace-v1'
       OR jsonb_typeof(p_trace->'candidates') IS DISTINCT FROM 'array'
       OR jsonb_array_length(p_trace->'candidates') <> 1
       OR p_trace->'candidates'->0->>'outcome' IS DISTINCT FROM 'coach_chosen'
       OR p_trace->'candidates'->0->>'exercise_id' IS DISTINCT FROM p_exercise_id
       OR (p_trace->>'fit') IS NOT NULL
    THEN
        RAISE EXCEPTION 'CV_EXERCISE_MATCH_TRACE_INPUT_INVALID';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'cv-exercise-assignment:' || p_take_session_id || ':' || p_snippet_id
        || ':' || policy, 0));

    SELECT * INTO existing FROM public.confident_voice_exercise_assignments
     WHERE take_session_id = p_take_session_id
       AND snippet_id = p_snippet_id
       AND exposure_policy_version = policy;
    IF FOUND THEN
        RETURN existing;
    END IF;

    pool := jsonb_build_array(jsonb_build_object(
        'exercise_id', p_exercise_id,
        'version', p_exercise_version,
        'rank', 1,
        'chosen_by', 'coach'));

    INSERT INTO public.confident_voice_exercise_assignments (
        owner_user_id, take_session_id, snippet_id, lane,
        exposure_policy_version, matching_policy_version,
        candidates, candidate_count, pool_sha256,
        selected_exercise_id, selected_exercise_version, selected_rank,
        selection_mode, rng_algorithm_version, protected_seed,
        seed_commitment_sha256, draw, below_minimum_probability
    ) VALUES (
        p_owner_user_id, p_take_session_id, p_snippet_id, p_lane,
        policy, p_matching_policy_version,
        pool, 1,
        encode(extensions.digest(convert_to(pool::text, 'UTF8'), 'sha256'), 'hex'),
        p_exercise_id, p_exercise_version, 1,
        'coach_chosen', 'none', NULL, NULL, NULL, false
    ) RETURNING * INTO created;

    INSERT INTO public.confident_voice_exercise_match_traces (
        assignment_id, take_session_id, snippet_id, trace_schema_version,
        matching_policy_version, fit, trace, trace_sha256
    ) VALUES (
        created.id, created.take_session_id, created.snippet_id,
        'exercise-match-trace-v1', created.matching_policy_version,
        NULL, p_trace,
        encode(extensions.digest(convert_to(p_trace::text, 'UTF8'), 'sha256'), 'hex')
    )
    ON CONFLICT (assignment_id) DO NOTHING;
    RETURN created;
END;
$$;

REVOKE ALL ON FUNCTION public.assign_coach_shared_exercise_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, JSONB)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.assign_coach_shared_exercise_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, JSONB) TO service_role;

-- ── The render receipt, for any assignment on the moment ─────────────────

-- Returns the exposure (the first one, on every later call). Raises
-- EXERCISE_RENDERED_NOT_DRAWN when the moment has no assignment at all,
-- EXERCISE_RENDERED_WRONG_EXERCISE when it has one but not for the rendered
-- exercise, EXERCISE_RENDERED_NOT_OWNER when the caller is not the owner.
CREATE OR REPLACE FUNCTION public.record_exercise_rendered_v2(
    p_owner_user_id TEXT,
    p_take_session_id TEXT,
    p_snippet_id TEXT,
    p_exercise_id TEXT
) RETURNS public.confident_voice_exercise_exposures
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    assigned public.confident_voice_exercise_assignments;
    seen public.confident_voice_exercise_exposures;
BEGIN
    IF COALESCE(btrim(p_owner_user_id), '') = ''
       OR COALESCE(btrim(p_take_session_id), '') = ''
       OR COALESCE(btrim(p_snippet_id), '') = ''
       OR COALESCE(btrim(p_exercise_id), '') = ''
    THEN
        RAISE EXCEPTION 'EXERCISE_RENDERED_INPUT_INVALID';
    END IF;

    SELECT * INTO assigned FROM public.confident_voice_exercise_assignments
     WHERE take_session_id = p_take_session_id
       AND snippet_id = p_snippet_id
       AND selected_exercise_id = p_exercise_id
     ORDER BY created_at
     LIMIT 1;
    IF NOT FOUND THEN
        IF EXISTS (SELECT 1 FROM public.confident_voice_exercise_assignments
                    WHERE take_session_id = p_take_session_id
                      AND snippet_id = p_snippet_id) THEN
            RAISE EXCEPTION 'EXERCISE_RENDERED_WRONG_EXERCISE';
        END IF;
        RAISE EXCEPTION 'EXERCISE_RENDERED_NOT_DRAWN';
    END IF;
    IF assigned.owner_user_id IS DISTINCT FROM p_owner_user_id THEN
        RAISE EXCEPTION 'EXERCISE_RENDERED_NOT_OWNER';
    END IF;

    INSERT INTO public.confident_voice_exercise_exposures (
        assignment_id, owner_user_id, take_session_id, snippet_id,
        exercise_id, exercise_version
    ) VALUES (
        assigned.id, assigned.owner_user_id, assigned.take_session_id,
        assigned.snippet_id, assigned.selected_exercise_id,
        assigned.selected_exercise_version
    )
    ON CONFLICT (assignment_id) DO NOTHING;

    SELECT * INTO seen FROM public.confident_voice_exercise_exposures
     WHERE assignment_id = assigned.id;
    RETURN seen;
END;
$$;

REVOKE ALL ON FUNCTION public.record_exercise_rendered_v2(TEXT, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_rendered_v2(TEXT, TEXT, TEXT, TEXT)
    TO service_role;

COMMENT ON FUNCTION public.assign_coach_shared_exercise_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, JSONB) IS
    'A coach-shared exercise frozen once per (Take, moment) under exercise-coach-shared-v1 with its trace, so its practices join the jar like a machine pick and are told apart by the policy name (founder 2026-09-29, decision 3).';

COMMIT;
