-- "Sounds more confident" reads the coach's two answers (founder 2026-09-29,
-- Q5; rule exercise-more-confident-v2, contract 35g-3).
--
-- 0388 read the coach leg from a direct "Do you find it more confident?" Yes.
-- Since 0390 the coach answers the same snapshot question as the speaker
-- ("Does this sound confident to you?", five answers), so "more confident"
-- is now WORKED OUT from two answers by the same coach:
--
--   before  their blind rating of the original clip (confidence_labels:
--           yes / neutral / no; unrateable is no answer);
--   after   their answer about the practice attempt (0390: yes / in_between
--           / no / not_sure / audio_unclear).
--
-- On the ladder No < In-between < Yes the coach leg is
--   yes      after is higher than before (the coach heard it get better)
--   no       after is the same or lower
--   pending  either answer is missing or off the ladder (Not sure, Audio
--            unclear, unrateable), OR both are Yes: already confident, so
--            the exercise cannot be shown to have helped (founder: counts as
--            not decided, never as "didn't help").
-- The machine leg is unchanged (the composite went up, any amount). The
-- outcome is unchanged: helped only when both legs say yes; not_helped when
-- either says no; pending otherwise.
--
-- Both coach answers are kept in their own columns (L3). Rows written under
-- v1 keep rule_version v1 and are not rewritten. Still never a label and never
-- served (is_label / serves_user CHECK false). Additive and idempotent.

BEGIN;

ALTER TABLE public.practice_more_confident_outcomes
    ADD COLUMN IF NOT EXISTS coach_before TEXT NULL,
    ADD COLUMN IF NOT EXISTS coach_after  TEXT NULL;

DO $rule$
DECLARE
    c RECORD;
BEGIN
    FOR c IN
        SELECT con.conname
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid = con.conrelid
          JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
         WHERE nsp.nspname = 'public'
           AND rel.relname = 'practice_more_confident_outcomes'
           AND con.contype = 'c'
           AND pg_get_constraintdef(con.oid) ~ '\mrule_version\M'
    LOOP
        EXECUTE format(
            'ALTER TABLE public.practice_more_confident_outcomes DROP CONSTRAINT %I',
            c.conname);
    END LOOP;
END
$rule$;

ALTER TABLE public.practice_more_confident_outcomes
    ADD CONSTRAINT practice_more_confident_rule_version
    CHECK (rule_version IN ('exercise-more-confident-v1',
                            'exercise-more-confident-v2'));
ALTER TABLE public.practice_more_confident_outcomes
    ALTER COLUMN rule_version SET DEFAULT 'exercise-more-confident-v2';

-- A coach answer's place on the ladder, or NULL when it is not on it.
CREATE OR REPLACE FUNCTION public.practice_coach_ladder_v1(p_answer TEXT)
RETURNS INTEGER LANGUAGE sql IMMUTABLE SET search_path = public
AS $$
    SELECT CASE p_answer
        WHEN 'no' THEN 0
        WHEN 'neutral' THEN 1
        WHEN 'in_between' THEN 1
        WHEN 'yes' THEN 2
    END;
$$;
REVOKE ALL ON FUNCTION public.practice_coach_ladder_v1(TEXT)
    FROM PUBLIC, anon, authenticated;

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
    v_before TEXT;
    v_after TEXT;
    v_before_step INTEGER;
    v_after_step INTEGER;
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

    -- The same coach's blind rating of the original clip.
    SELECT CASE WHEN label.unrateable THEN NULL ELSE label.value END
      INTO v_before
      FROM public.confidence_labels label
     WHERE label.snippet_id = practice.snippet_id
       AND label.rater_id = attempt.coach_confidence_decided_by
       AND label.state_id = 'confidence'
     ORDER BY label.updated_at DESC NULLS LAST
     LIMIT 1;
    v_after := attempt.coach_confidence_decision;
    v_before_step := public.practice_coach_ladder_v1(v_before);
    v_after_step := public.practice_coach_ladder_v1(v_after);
    v_coach := CASE
        WHEN v_before_step IS NULL OR v_after_step IS NULL THEN NULL
        WHEN v_before_step = 2 AND v_after_step = 2 THEN NULL
        WHEN v_after_step > v_before_step THEN 'yes'
        ELSE 'no' END;

    v_outcome := CASE
        WHEN v_machine = 'unmeasurable' OR v_coach IS NULL THEN 'pending'
        WHEN v_machine = 'higher' AND v_coach = 'yes' THEN 'helped'
        ELSE 'not_helped' END;

    INSERT INTO public.practice_more_confident_outcomes (
        practice_id, attempt_id, owner_user_id, take_session_id,
        original_score, attempt_score, machine_leg, coach_leg, coach_before,
        coach_after, outcome, rule_version
    ) VALUES (
        practice.id, attempt.id, practice.owner_user_id,
        practice.take_session_id, v_original, v_attempt, v_machine, v_coach,
        v_before, v_after, v_outcome, 'exercise-more-confident-v2'
    )
    ON CONFLICT (practice_id) DO UPDATE SET
        attempt_id = EXCLUDED.attempt_id,
        original_score = EXCLUDED.original_score,
        attempt_score = EXCLUDED.attempt_score,
        machine_leg = EXCLUDED.machine_leg,
        coach_leg = EXCLUDED.coach_leg,
        coach_before = EXCLUDED.coach_before,
        coach_after = EXCLUDED.coach_after,
        outcome = EXCLUDED.outcome,
        rule_version = EXCLUDED.rule_version,
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

COMMIT;
