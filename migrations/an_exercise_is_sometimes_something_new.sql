-- An exercise is sometimes something new: the 80/20 exposure policy
-- (founder 2026-09-26: "please do the 80/20 try smth new").
--
-- When a moment has two or more eligible exercises, the best match is chosen
-- with probability 4/5 and each of the others with 1/(5(n-1)). One eligible
-- exercise is chosen with probability 1 and is not a randomized comparison.
-- This follows docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md §4.4 for the exercise
-- lane that actually serves speakers today (the `diagnostic_exercise`
-- catalogue), not the dark MLC-3 frames, whose CHECKs forbid serving.
--
-- ONE DRAW PER MOMENT, EVER. The Ideal Text is polled and its feedback is
-- recomputed after every answer, so a draw made in Python would re-roll on
-- every read. The draw happens here, under an advisory lock, and the unique
-- key returns the first row forever after: refresh, retry and replay never
-- redraw. The row freezes the complete ranked pool, every candidate's
-- probability, the seed commitment and the draw, so the comparison can be
-- evaluated later without trusting anything recomputed.
--
-- Exposure policy only. It changes WHICH eligible exercise a moment gets,
-- never the exercise content, the speaker's answer or any coach packet, and
-- nothing here is a dataset, a label or a training input. No number from
-- this table reaches a user (AC-9).
--
-- Additive and idempotent. No backfill, no env var.

BEGIN;

CREATE TABLE IF NOT EXISTS public.confident_voice_exercise_assignments (
    id                          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id               TEXT        NOT NULL CHECK (length(owner_user_id) > 0),
    take_session_id             TEXT        NOT NULL CHECK (length(take_session_id) > 0),
    snippet_id                  TEXT        NOT NULL CHECK (length(snippet_id) > 0),
    lane                        TEXT        NOT NULL
        CHECK (lane IN ('v3_exercise_block', 'legacy_offer')),
    exposure_policy_version     TEXT        NOT NULL
        CHECK (exposure_policy_version = 'exercise-80-20-v1'),
    matching_policy_version     TEXT        NOT NULL CHECK (length(matching_policy_version) > 0),
    candidates                  JSONB       NOT NULL CHECK (jsonb_typeof(candidates) = 'array'),
    candidate_count             INTEGER     NOT NULL CHECK (candidate_count >= 1),
    pool_sha256                 TEXT        NOT NULL CHECK (pool_sha256 ~ '^[0-9a-f]{64}$'),
    selected_exercise_id        TEXT        NOT NULL CHECK (length(selected_exercise_id) > 0),
    selected_exercise_version   INTEGER     NOT NULL CHECK (selected_exercise_version >= 1),
    selected_rank               INTEGER     NOT NULL CHECK (selected_rank >= 1),
    selection_mode              TEXT        NOT NULL
        CHECK (selection_mode IN ('deterministic_singleton', 'top', 'exploration')),
    rng_algorithm_version       TEXT        NOT NULL,
    protected_seed              BYTEA       NULL,
    seed_commitment_sha256      TEXT        NULL,
    draw                        NUMERIC     NULL CHECK (draw IS NULL OR (draw >= 0 AND draw < 1)),
    minimum_probability         NUMERIC     NOT NULL DEFAULT 0.01,
    below_minimum_probability   BOOLEAN     NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (selected_rank <= candidate_count),
    -- A singleton is not randomized: no seed, no draw. Anything else is.
    CHECK (
        (selection_mode = 'deterministic_singleton' AND candidate_count = 1
         AND protected_seed IS NULL AND seed_commitment_sha256 IS NULL AND draw IS NULL)
        OR
        (selection_mode <> 'deterministic_singleton' AND candidate_count >= 2
         AND protected_seed IS NOT NULL AND draw IS NOT NULL
         AND seed_commitment_sha256 ~ '^[0-9a-f]{64}$')
    ),
    CHECK ((selection_mode = 'top') = (selected_rank = 1 AND candidate_count >= 2))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_cv_exercise_assignment_unit
    ON public.confident_voice_exercise_assignments
       (take_session_id, snippet_id, exposure_policy_version);

ALTER TABLE public.confident_voice_exercise_assignments ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.confident_voice_exercise_assignments
    FROM PUBLIC, anon, authenticated;
-- Written only by the function below. The server reads it (the practice
-- start route checks the tapped exercise against it) and the account purge
-- deletes it, so SELECT and DELETE stay with service_role; nothing updates it.
REVOKE INSERT, UPDATE, TRUNCATE ON public.confident_voice_exercise_assignments
    FROM service_role;
GRANT SELECT, DELETE ON public.confident_voice_exercise_assignments TO service_role;

-- Immutable once written. DELETE stays possible because erasure must be.
CREATE OR REPLACE FUNCTION public.reject_cv_exercise_assignment_update_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    RAISE EXCEPTION 'CV_EXERCISE_ASSIGNMENT_IMMUTABLE';
END;
$$;
REVOKE ALL ON FUNCTION public.reject_cv_exercise_assignment_update_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS cv_exercise_assignment_immutable
    ON public.confident_voice_exercise_assignments;
CREATE TRIGGER cv_exercise_assignment_immutable
    BEFORE UPDATE ON public.confident_voice_exercise_assignments
    FOR EACH ROW EXECUTE FUNCTION public.reject_cv_exercise_assignment_update_v1();

-- p_candidates: the moment's eligible exercises, best match first, each
-- {"exercise_id": text, "version": int}. The ranking is the caller's (the one
-- deterministic matcher); this function only freezes it and draws.
CREATE OR REPLACE FUNCTION public.assign_confident_voice_exercise_v1(
    p_owner_user_id TEXT,
    p_take_session_id TEXT,
    p_snippet_id TEXT,
    p_lane TEXT,
    p_matching_policy_version TEXT,
    p_candidates JSONB
) RETURNS public.confident_voice_exercise_assignments
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    policy CONSTANT TEXT := 'exercise-80-20-v1';
    existing public.confident_voice_exercise_assignments;
    created public.confident_voice_exercise_assignments;
    n INTEGER;
    item JSONB;
    idx INTEGER := 0;
    pool JSONB := '[]'::jsonb;
    frozen JSONB := '[]'::jsonb;
    seed BYTEA;
    draw NUMERIC;
    chosen INTEGER;
    mode TEXT;
    other_denominator BIGINT;
BEGIN
    IF COALESCE(btrim(p_owner_user_id), '') = ''
       OR COALESCE(btrim(p_take_session_id), '') = ''
       OR COALESCE(btrim(p_snippet_id), '') = ''
       OR p_lane IS NULL OR p_lane NOT IN ('v3_exercise_block', 'legacy_offer')
       OR COALESCE(btrim(p_matching_policy_version), '') = ''
       OR p_candidates IS NULL OR jsonb_typeof(p_candidates) <> 'array'
       OR jsonb_array_length(p_candidates) < 1
    THEN
        RAISE EXCEPTION 'CV_EXERCISE_ASSIGNMENT_INPUT_INVALID';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'cv-exercise-assignment:' || p_take_session_id || ':' || p_snippet_id, 0));

    SELECT * INTO existing FROM public.confident_voice_exercise_assignments
     WHERE take_session_id = p_take_session_id
       AND snippet_id = p_snippet_id
       AND exposure_policy_version = policy;
    IF FOUND THEN
        -- Never redraw. A later call with a different pool still gets the
        -- first assignment; the caller decides whether it can still serve.
        RETURN existing;
    END IF;

    n := jsonb_array_length(p_candidates);
    FOR item IN SELECT value FROM jsonb_array_elements(p_candidates) LOOP
        IF jsonb_typeof(item) <> 'object'
           OR COALESCE(btrim(item->>'exercise_id'), '') = ''
           OR jsonb_typeof(item->'version') <> 'number'
           OR (item->>'version')::numeric <> floor((item->>'version')::numeric)
           OR (item->>'version')::numeric < 1
        THEN
            RAISE EXCEPTION 'CV_EXERCISE_ASSIGNMENT_INPUT_INVALID';
        END IF;
        pool := pool || jsonb_build_array(jsonb_build_object(
            'exercise_id', item->>'exercise_id',
            'version', (item->>'version')::integer));
    END LOOP;
    IF (SELECT count(DISTINCT value->>'exercise_id') FROM jsonb_array_elements(pool)) <> n THEN
        RAISE EXCEPTION 'CV_EXERCISE_ASSIGNMENT_DUPLICATE_EXERCISE';
    END IF;

    IF n = 1 THEN
        chosen := 1;
        mode := 'deterministic_singleton';
    ELSE
        seed := extensions.gen_random_bytes(32);
        -- First 52 bits of sha256(seed || unit) / 2^52: the same algorithm
        -- as exercise_rng_draw_v1 (0314), inlined so this lane does not
        -- depend on the dark schema's grants.
        draw := ('x' || substr(encode(extensions.digest(
                    seed || convert_to(p_take_session_id || ':' || p_snippet_id
                                       || ':' || policy, 'UTF8'),
                    'sha256'), 'hex'), 1, 13))::bit(52)::bigint::numeric
                / 4503599627370496::numeric;
        IF draw < 0.8 THEN
            chosen := 1;
            mode := 'top';
        ELSE
            chosen := 2 + floor((draw - 0.8) * 5 * (n - 1))::integer;
            chosen := LEAST(GREATEST(chosen, 2), n);
            mode := 'exploration';
        END IF;
    END IF;

    other_denominator := 5 * (n - 1);
    FOR item IN SELECT value FROM jsonb_array_elements(pool) LOOP
        idx := idx + 1;
        frozen := frozen || jsonb_build_array(item || jsonb_build_object(
            'rank', idx,
            'probability_numerator',
                CASE WHEN n = 1 THEN 1 WHEN idx = 1 THEN 4 ELSE 1 END,
            'probability_denominator',
                CASE WHEN n = 1 THEN 1 WHEN idx = 1 THEN 5 ELSE other_denominator END));
    END LOOP;

    INSERT INTO public.confident_voice_exercise_assignments (
        owner_user_id, take_session_id, snippet_id, lane,
        exposure_policy_version, matching_policy_version,
        candidates, candidate_count, pool_sha256,
        selected_exercise_id, selected_exercise_version, selected_rank,
        selection_mode, rng_algorithm_version,
        protected_seed, seed_commitment_sha256, draw,
        minimum_probability, below_minimum_probability
    ) VALUES (
        p_owner_user_id, p_take_session_id, p_snippet_id, p_lane,
        policy, p_matching_policy_version,
        frozen, n,
        encode(extensions.digest(convert_to(pool::text, 'UTF8'), 'sha256'), 'hex'),
        pool->(chosen - 1)->>'exercise_id',
        (pool->(chosen - 1)->>'version')::integer,
        chosen, mode,
        CASE WHEN n = 1 THEN 'not_randomized_singleton'
             ELSE 'sha256-first52-v1' END,
        seed,
        CASE WHEN seed IS NULL THEN NULL
             ELSE encode(extensions.digest(seed, 'sha256'), 'hex') END,
        draw,
        0.01,
        n > 1 AND (1::numeric / other_denominator) < 0.01
    )
    RETURNING * INTO created;
    RETURN created;
END;
$$;

REVOKE ALL ON FUNCTION public.assign_confident_voice_exercise_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.assign_confident_voice_exercise_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, JSONB) TO service_role;

COMMENT ON TABLE public.confident_voice_exercise_assignments IS
    'One frozen exercise choice per (Take, moment): the ranked pool, every '
    'probability, the seed commitment and the draw of the 80/20 exposure '
    'policy (founder 2026-09-26). Never redrawn; never shown to a user.';

COMMIT;
