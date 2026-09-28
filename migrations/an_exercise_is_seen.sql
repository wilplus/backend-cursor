-- An exercise is seen (founder 2026-09-28; label specification
-- exercise-adequacy-label-v1, docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md §3.5).
--
-- The label specification counts an exposure only once the speaker's own
-- client confirms the assigned exercise actually rendered. Until now the only
-- record was the 80/20 assignment (0372), which is made when the feedback is
-- built — whether or not the card was ever on a screen. Counting offers as
-- exposures would understate how often speakers attempt an exercise, and the
-- attempt-rate guardrail would compare offers with attempts.
--
-- ONE EXPOSURE PER ASSIGNMENT, RECORDED ONCE. record_exercise_rendered_v1
-- checks the confirmation against the frozen assignment — the same Take and
-- moment, the same owner, the exercise the draw actually selected — and
-- inserts once; every later call returns the first row. A card rendered on
-- ten polls is one exposure. A moment with no draw (nothing fitted, or a
-- coach-shared exercise) has nothing to expose and records nothing.
--
-- Internal. No number here reaches a user (AC-9); nothing here is a label.
-- Additive and idempotent. No env var.

BEGIN;

CREATE TABLE IF NOT EXISTS public.confident_voice_exercise_exposures (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    assignment_id      UUID        NOT NULL UNIQUE
        REFERENCES public.confident_voice_exercise_assignments(id)
        ON DELETE CASCADE,
    owner_user_id      TEXT        NOT NULL CHECK (length(owner_user_id) > 0),
    take_session_id    TEXT        NOT NULL CHECK (length(take_session_id) > 0),
    snippet_id         TEXT        NOT NULL CHECK (length(snippet_id) > 0),
    exercise_id        TEXT        NOT NULL CHECK (length(exercise_id) > 0),
    exercise_version   INTEGER     NOT NULL CHECK (exercise_version >= 1),
    rendered_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cv_exercise_exposures_take
    ON public.confident_voice_exercise_exposures (take_session_id);

ALTER TABLE public.confident_voice_exercise_exposures ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.confident_voice_exercise_exposures
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.confident_voice_exercise_exposures FROM service_role;
GRANT SELECT, DELETE ON public.confident_voice_exercise_exposures TO service_role;

CREATE OR REPLACE FUNCTION public.reject_cv_exercise_exposure_update_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    RAISE EXCEPTION 'CV_EXERCISE_EXPOSURE_IMMUTABLE';
END;
$$;
REVOKE ALL ON FUNCTION public.reject_cv_exercise_exposure_update_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS cv_exercise_exposure_immutable
    ON public.confident_voice_exercise_exposures;
CREATE TRIGGER cv_exercise_exposure_immutable
    BEFORE UPDATE ON public.confident_voice_exercise_exposures
    FOR EACH ROW EXECUTE FUNCTION public.reject_cv_exercise_exposure_update_v1();

-- Returns the exposure (the first one, on every later call). Raises
-- EXERCISE_RENDERED_NOT_DRAWN when the moment has no assignment,
-- EXERCISE_RENDERED_NOT_OWNER when the caller is not the assignment's owner,
-- EXERCISE_RENDERED_WRONG_EXERCISE when the rendered exercise is not the one
-- the draw selected.
CREATE OR REPLACE FUNCTION public.record_exercise_rendered_v1(
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
       AND exposure_policy_version = 'exercise-80-20-v1';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'EXERCISE_RENDERED_NOT_DRAWN';
    END IF;
    IF assigned.owner_user_id IS DISTINCT FROM p_owner_user_id THEN
        RAISE EXCEPTION 'EXERCISE_RENDERED_NOT_OWNER';
    END IF;
    IF assigned.selected_exercise_id IS DISTINCT FROM p_exercise_id THEN
        RAISE EXCEPTION 'EXERCISE_RENDERED_WRONG_EXERCISE';
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

REVOKE ALL ON FUNCTION public.record_exercise_rendered_v1(TEXT, TEXT, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_exercise_rendered_v1(TEXT, TEXT, TEXT, TEXT)
    TO service_role;

COMMENT ON TABLE public.confident_voice_exercise_exposures IS
    'One exposure per 80/20 assignment: the speaker''s client confirmed the '
    'assigned exercise rendered (label spec exercise-adequacy-label-v1). '
    'Recorded once; never shown to a user; not a label.';

COMMIT;
