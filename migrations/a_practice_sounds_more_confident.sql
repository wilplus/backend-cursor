-- A practice sounds more confident (founder 2026-09-28, option A; rule
-- exercise-more-confident-v1, contract 35g-3).
--
-- One internal result per practice session, about the attempt the coach
-- judged: did it sound MORE CONFIDENT than the original clip? Two legs, and
-- both must say yes:
--
--   machine  the attempt's voice-confidence composite is higher than the
--            original clip's (any increase; services/voice_confidence.py,
--            the same speaker-relative scale the V3 lanes already read);
--   coach    the coach answered "Do you find it more confident?" Yes, after
--            their own blind rating of the moment. The speaker's own answer
--            is not a leg.
--
--   helped      both legs yes
--   not_helped  either leg no
--   pending     a leg is missing (no score to compare, or no coach answer)
--
-- WHAT IT IS NOT. It is not exercise-adequacy-label-v1 (design §3.5) and not
-- a label of any kind: no dataset, training, evaluation or promotion path may
-- read it (is_label is CHECK-forced false), and it never reaches a user or a
-- coach (serves_user is CHECK-forced false; AC-9). The two legs stay in their
-- own columns with their own provenance (L3), and the result is derived from
-- them by the one function below, never written by hand.
--
-- The coach may revise their answer, so the row is recomputed in place on
-- every coach decision. Additive and idempotent. No env var.

BEGIN;

CREATE TABLE IF NOT EXISTS public.practice_more_confident_outcomes (
    practice_id      UUID        PRIMARY KEY
        REFERENCES public.confident_voice_practice(id) ON DELETE CASCADE,
    attempt_id       UUID        NOT NULL
        REFERENCES public.confident_voice_practice_attempt(id)
        ON DELETE CASCADE,
    owner_user_id    UUID        NOT NULL,
    take_session_id  UUID        NOT NULL,
    original_score   DOUBLE PRECISION,
    attempt_score    DOUBLE PRECISION,
    machine_leg      TEXT        NOT NULL
        CHECK (machine_leg IN ('higher', 'not_higher', 'unmeasurable')),
    coach_leg        TEXT
        CHECK (coach_leg IS NULL OR coach_leg IN ('yes', 'no')),
    outcome          TEXT        NOT NULL
        CHECK (outcome IN ('helped', 'not_helped', 'pending')),
    rule_version     TEXT        NOT NULL DEFAULT 'exercise-more-confident-v1'
        CHECK (rule_version = 'exercise-more-confident-v1'),
    is_label         BOOLEAN     NOT NULL DEFAULT false CHECK (is_label = false),
    serves_user      BOOLEAN     NOT NULL DEFAULT false CHECK (serves_user = false),
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_practice_more_confident_take
    ON public.practice_more_confident_outcomes (take_session_id);

ALTER TABLE public.practice_more_confident_outcomes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.practice_more_confident_outcomes
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.practice_more_confident_outcomes FROM service_role;
GRANT SELECT, DELETE ON public.practice_more_confident_outcomes TO service_role;

-- A JSON number, or NULL. Anything else (absent, a string, a bool) is "no
-- score", never coerced.
CREATE OR REPLACE FUNCTION public.practice_confidence_number_v1(p_value JSONB)
RETURNS DOUBLE PRECISION LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT CASE WHEN jsonb_typeof(p_value) = 'number'
                THEN (p_value #>> '{}')::double precision END;
$$;
REVOKE ALL ON FUNCTION public.practice_confidence_number_v1(JSONB)
    FROM PUBLIC, anon, authenticated;

-- Recompute the result for one practice from what is stored: the original
-- clip's frozen snapshot, the attempt's own snapshot, and the coach's answer
-- on that attempt. Raises PRACTICE_MORE_CONFIDENT_NOT_FOUND when the attempt
-- does not belong to the practice.
CREATE OR REPLACE FUNCTION public.record_practice_more_confident_v1(
    p_practice_id UUID,
    p_attempt_id UUID
) RETURNS public.practice_more_confident_outcomes
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    practice public.confident_voice_practice;
    attempt public.confident_voice_practice_attempt;
    v_original DOUBLE PRECISION;
    v_attempt DOUBLE PRECISION;
    v_machine TEXT;
    v_coach TEXT;
    v_outcome TEXT;
    saved public.practice_more_confident_outcomes;
BEGIN
    SELECT * INTO practice FROM public.confident_voice_practice
     WHERE id = p_practice_id;
    SELECT * INTO attempt FROM public.confident_voice_practice_attempt
     WHERE id = p_attempt_id AND practice_id = p_practice_id;
    IF practice.id IS NULL OR attempt.id IS NULL THEN
        RAISE EXCEPTION 'PRACTICE_MORE_CONFIDENT_NOT_FOUND';
    END IF;

    v_original := public.practice_confidence_number_v1(
        practice.acoustic_evidence -> 'snapshot' -> 'confidence');
    v_attempt := public.practice_confidence_number_v1(
        attempt.acoustic_metrics -> 'confidence');
    v_machine := CASE
        WHEN v_original IS NULL OR v_attempt IS NULL THEN 'unmeasurable'
        WHEN v_attempt > v_original THEN 'higher'
        ELSE 'not_higher' END;
    v_coach := CASE WHEN attempt.coach_confidence_decision IN ('yes', 'no')
                    THEN attempt.coach_confidence_decision END;
    v_outcome := CASE
        WHEN v_machine = 'unmeasurable' OR v_coach IS NULL THEN 'pending'
        WHEN v_machine = 'higher' AND v_coach = 'yes' THEN 'helped'
        ELSE 'not_helped' END;

    INSERT INTO public.practice_more_confident_outcomes (
        practice_id, attempt_id, owner_user_id, take_session_id,
        original_score, attempt_score, machine_leg, coach_leg, outcome
    ) VALUES (
        practice.id, attempt.id, practice.owner_user_id,
        practice.take_session_id, v_original, v_attempt, v_machine, v_coach,
        v_outcome
    )
    ON CONFLICT (practice_id) DO UPDATE SET
        attempt_id = EXCLUDED.attempt_id,
        original_score = EXCLUDED.original_score,
        attempt_score = EXCLUDED.attempt_score,
        machine_leg = EXCLUDED.machine_leg,
        coach_leg = EXCLUDED.coach_leg,
        outcome = EXCLUDED.outcome,
        updated_at = now();

    SELECT * INTO saved FROM public.practice_more_confident_outcomes
     WHERE practice_id = practice.id;
    RETURN saved;
END;
$$;

REVOKE ALL ON FUNCTION public.record_practice_more_confident_v1(UUID, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_practice_more_confident_v1(UUID, UUID)
    TO service_role;

COMMENT ON TABLE public.practice_more_confident_outcomes IS
    'Internal: did the coach-judged practice attempt sound more confident than '
    'the original (machine composite higher AND coach Yes)? Rule '
    'exercise-more-confident-v1. Never a label, never shown to anyone.';

COMMIT;
