-- a_practice_is_heard_in_the_next_take (0476)
--
-- WHY. The founder (2026-10-18, Linear WIL-29, concept
-- docs/CONCEPT-per-user-exercise-effectiveness-2026-10-18.md; decided in
-- chat: "build option 2", "next time is the next Take of the same
-- project", "founder only"). Every measure the product has asks whether an
-- exercise helped the moment it was practised on, minutes later. None asks
-- whether it held: when the speaker recorded the whole talk again, did the
-- problem the exercise targeted come back on that passage?
--
-- WHAT. One row per library-exercise practice, written once, when the
-- speaker's next Take of the same project is ready (rule
-- exercise-held-next-take-v1, services/exercise_held.py):
--
--   held       the passage was found in the next Take, said with reliable
--              audio, and none of the practice's targeted problems fired;
--   came_back  found and reliable, and at least one targeted problem fired;
--   unknown    with the reason: the passage was not found (rewritten,
--              split, cut), the audio was not reliable, the signal rules
--              changed in between, or nothing was targeted.
--
-- Insert-once and immutable: a later Take never revises the result (the
-- trigger refuses UPDATE). DELETE stays possible because erasure must be;
-- the purge registry takes the row with the practice, and the cascades
-- are the backstop.
--
-- WHAT IT IS NOT. Not a label of any kind: no dataset, training,
-- evaluation or promotion path reads it (is_label CHECK-forced false). It
-- never reaches a speaker or a coach (serves_user CHECK-forced false;
-- AC-9); the founder's own pages read it. No transcript text is copied.
--
-- Additive and idempotent. Nothing is dropped. No env var.

BEGIN;

CREATE TABLE IF NOT EXISTS public.exercise_held_next_take_outcomes (
    practice_id            UUID        PRIMARY KEY
        REFERENCES public.confident_voice_practice(id) ON DELETE CASCADE,
    owner_user_id          UUID        NOT NULL,
    project_id             UUID        NOT NULL,
    practice_take_id       UUID        NOT NULL,
    next_take_id           UUID        NOT NULL
        REFERENCES public.v2_sessions(id) ON DELETE CASCADE,
    next_snippet_id        UUID        NULL,
    exercise_id            TEXT        NOT NULL,
    targeted_problems      TEXT[]      NOT NULL DEFAULT '{}',
    still_firing           TEXT[]      NOT NULL DEFAULT '{}',
    outcome                TEXT        NOT NULL
        CHECK (outcome IN ('held', 'came_back', 'unknown')),
    unknown_reason         TEXT        NULL CHECK (unknown_reason IS NULL OR
        unknown_reason IN ('no_trace', 'no_targeted_problem', 'rules_changed',
                           'passage_not_found', 'audio_unreliable')),
    signal_rules_version   TEXT        NULL,
    rule_version           TEXT        NOT NULL
        DEFAULT 'exercise-held-next-take-v1'
        CHECK (rule_version = 'exercise-held-next-take-v1'),
    is_label               BOOLEAN     NOT NULL DEFAULT false CHECK (is_label = false),
    serves_user            BOOLEAN     NOT NULL DEFAULT false CHECK (serves_user = false),
    recorded_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((outcome = 'unknown') = (unknown_reason IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_exercise_held_next_take_owner
    ON public.exercise_held_next_take_outcomes (owner_user_id);
CREATE INDEX IF NOT EXISTS idx_exercise_held_next_take_next_take
    ON public.exercise_held_next_take_outcomes (next_take_id);

ALTER TABLE public.exercise_held_next_take_outcomes ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.exercise_held_next_take_outcomes
    FROM PUBLIC, anon, authenticated;
REVOKE ALL ON public.exercise_held_next_take_outcomes FROM service_role;
GRANT SELECT, INSERT, DELETE ON public.exercise_held_next_take_outcomes
    TO service_role;

CREATE OR REPLACE FUNCTION public.reject_exercise_held_next_take_update_v1()
RETURNS TRIGGER LANGUAGE plpgsql SET search_path = public
AS $$
BEGIN
    RAISE EXCEPTION 'EXERCISE_HELD_NEXT_TAKE_IMMUTABLE';
END;
$$;
REVOKE ALL ON FUNCTION public.reject_exercise_held_next_take_update_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS exercise_held_next_take_immutable
    ON public.exercise_held_next_take_outcomes;
CREATE TRIGGER exercise_held_next_take_immutable
    BEFORE UPDATE ON public.exercise_held_next_take_outcomes
    FOR EACH ROW EXECUTE FUNCTION public.reject_exercise_held_next_take_update_v1();

COMMENT ON TABLE public.exercise_held_next_take_outcomes IS
    'exercise-held-next-take-v1 (0476, founder 2026-10-18, WIL-29): did a '
    'practised exercise''s targeted problem stay away on the same passage in '
    'the speaker''s next Take of the same project? Insert-once, immutable, '
    'never a label, never shown to a speaker or a coach (AC-9).';

COMMIT;
