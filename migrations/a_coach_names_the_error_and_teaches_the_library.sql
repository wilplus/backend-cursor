-- a_coach_names_the_error_and_teaches_the_library
--
-- FOUNDER 2026-09-25, on the coach's Confident Voice practice review. Two
-- things, each its own table so neither can be mistaken for the other.
--
-- 1 · A COACH NAMES THE ERROR ON ONE MOMENT (coach_moment_error_event).
--     "Naming a new error tags the clip, stored as coach provenance." A row
--     is a coach's judgement about ONE recording and nothing else:
--       * it is never shown to the speaker;
--       * it never joins the machine's observed tags, which stay a detector
--         verdict (L3: coach judgement and detector verdict stay separate);
--       * it is not a training label. Phase-2 corpus, dataset and training
--         paths stay disabled, and nothing here is registered with them;
--       * it goes when the recording goes: the deletion registry deletes it
--         with the speaker's practice (services/data_purge_registry.py), and
--         ON DELETE CASCADE from the practice is the backstop.
--     Append-only events (named / withdrawn). The current state is the latest
--     event per (practice, error), so a withdrawn name keeps its history.
--
-- 2 · ATTACHING AN EXERCISE TEACHES THE LIBRARY (diagnostic_exercise_teaching).
--     "Attach = both": giving an exercise to the speaker for this moment also
--     records that this exercise fixes this moment's error, so the next
--     speaker whose OWN recording shows that error is matched to it. What
--     crosses recordings is a claim about the EXERCISE (the same kind of claim
--     the CMS "What does it fix?" step makes), never a signal about one
--     recording. Another speaker is still matched only on their own detector
--     verdict. Founder decision 04 (#643) made the same move for the coach's
--     own exercises.
--       * Only errors the machine can DETECT may become an exercise's tags,
--         the rule the catalogue already enforces (_validate_tags). A
--         detector-less name could never match anyone, so it is skipped.
--       * Every teaching is logged: who, when, from which moment, from which
--         source (the coach's own naming, or the machine's reading that the
--         coach attached to), and whether it actually changed the tags.
--       * UNDO removes a tag only when a TEACHING put it there (the last
--         change to that tag on that exercise was a teaching that added it)
--         AND no other live teaching still claims the same fix. A tag the CMS
--         author set is never removed by an undo. Asking "did THIS teaching
--         add it?" instead would strand a tag: moment 1 adds it, moment 2
--         claims it too, moment 1's undo must keep it, and moment 2's undo
--         would then keep it as well because moment 2 did not add it.
--       * It never empties an exercise's tags, because an exercise naming no
--         error can never be offered to anyone.
--       * A speaker's deletion removes the teaching rows made from their
--         moment (services/data_purge_registry.py). The tag a teaching added
--         stays on the exercise, because it is a claim about the EXERCISE and
--         carries nothing about the speaker. practice_id's ON DELETE SET NULL
--         is the backstop for a practice deleted by any other path.
--
-- The two functions are the ONLY writers of the teaching table and of a taught
-- tag. Each locks the exercise row first, so a teach and an undo on the same
-- exercise serialise instead of losing one another's write.
--
-- Additive and idempotent: CREATE ... IF NOT EXISTS and CREATE OR REPLACE
-- FUNCTION only. No DROP, and no existing row is rewritten. No environment
-- variable is involved, so there is nothing to set on any Railway service
-- first. The code that calls these functions ships in the same PR, and it
-- degrades to "nothing named, nothing taught" if this has not run yet.

CREATE TABLE IF NOT EXISTS public.coach_moment_error_event (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Order of record. created_at is the transaction's start, which two
    -- writers can commit out of order; seq is assigned at insert.
    seq          BIGINT GENERATED ALWAYS AS IDENTITY,
    practice_id  UUID NOT NULL
                 REFERENCES public.confident_voice_practice(id)
                 ON DELETE CASCADE,
    error_id     TEXT NOT NULL REFERENCES public.speaking_error(error_id),
    coach_id     UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
    action       TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT coach_moment_error_event_action_check
        CHECK (action IN ('named', 'withdrawn'))
);

CREATE INDEX IF NOT EXISTS coach_moment_error_event_practice_idx
    ON public.coach_moment_error_event (practice_id, error_id, seq);

ALTER TABLE public.coach_moment_error_event ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.diagnostic_exercise_teaching (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Order of record: assigned at insert, under the exercise row lock both
    -- functions take, so it is the order the changes actually happened in.
    seq           BIGINT GENERATED ALWAYS AS IDENTITY,
    exercise_id   TEXT NOT NULL
                  REFERENCES public.diagnostic_exercise(exercise_id),
    error_id      TEXT NOT NULL REFERENCES public.speaking_error(error_id),
    practice_id   UUID NULL
                  REFERENCES public.confident_voice_practice(id)
                  ON DELETE SET NULL,
    coach_id      UUID NULL REFERENCES auth.users(id) ON DELETE SET NULL,
    action        TEXT NOT NULL,
    source        TEXT NOT NULL,
    -- taught: this row added the tag. undone: this row removed it.
    changed_tags  BOOLEAN NOT NULL,
    undoes_id     UUID NULL
                  REFERENCES public.diagnostic_exercise_teaching(id),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT diagnostic_exercise_teaching_action_check
        CHECK (action IN ('taught', 'undone')),
    CONSTRAINT diagnostic_exercise_teaching_source_check
        CHECK (source IN ('coach_named', 'machine_observed')),
    CONSTRAINT diagnostic_exercise_teaching_undo_shape_check
        CHECK ((action = 'undone') = (undoes_id IS NOT NULL))
);

-- A teaching is undone at most once.
CREATE UNIQUE INDEX IF NOT EXISTS diagnostic_exercise_teaching_one_undo
    ON public.diagnostic_exercise_teaching (undoes_id)
    WHERE undoes_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS diagnostic_exercise_teaching_fix_idx
    ON public.diagnostic_exercise_teaching (exercise_id, error_id, seq);

CREATE INDEX IF NOT EXISTS diagnostic_exercise_teaching_practice_idx
    ON public.diagnostic_exercise_teaching (practice_id);

ALTER TABLE public.diagnostic_exercise_teaching ENABLE ROW LEVEL SECURITY;

-- Teach: for each error, add it to the exercise's tags if absent, and log it.
-- Returns one object per error actually recorded:
--   {"teaching_id", "error_id", "added"}
-- An error the machine cannot detect, or one this moment already taught this
-- exercise and has not undone, is skipped and absent from the result.
CREATE OR REPLACE FUNCTION public.teach_diagnostic_exercise_v1(
    p_exercise_id TEXT,
    p_practice_id UUID,
    p_coach_id UUID,
    p_error_ids TEXT[],
    p_source TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public
AS $$
DECLARE
    tags TEXT[];
    err TEXT;
    added BOOLEAN;
    new_id UUID;
    changed BOOLEAN := FALSE;
    result JSONB := '[]'::jsonb;
BEGIN
    IF p_source NOT IN ('coach_named', 'machine_observed') THEN
        RAISE EXCEPTION 'unknown teaching source %', p_source;
    END IF;
    SELECT acoustic_problem_tags INTO tags
      FROM diagnostic_exercise
     WHERE exercise_id = p_exercise_id
       FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'unknown exercise %', p_exercise_id;
    END IF;
    tags := COALESCE(tags, '{}'::TEXT[]);
    FOREACH err IN ARRAY COALESCE(p_error_ids, '{}'::TEXT[]) LOOP
        IF NOT EXISTS (
            SELECT 1 FROM speaking_error
             WHERE error_id = err AND status = 'detected' AND active
        ) THEN
            CONTINUE;
        END IF;
        IF EXISTS (
            SELECT 1 FROM diagnostic_exercise_teaching t
             WHERE t.exercise_id = p_exercise_id
               AND t.error_id = err
               AND t.practice_id = p_practice_id
               AND t.action = 'taught'
               AND NOT EXISTS (
                   SELECT 1 FROM diagnostic_exercise_teaching u
                    WHERE u.undoes_id = t.id)
        ) THEN
            CONTINUE;
        END IF;
        added := NOT (err = ANY(tags));
        IF added THEN
            tags := array_append(tags, err);
            changed := TRUE;
        END IF;
        INSERT INTO diagnostic_exercise_teaching (
            exercise_id, error_id, practice_id, coach_id,
            action, source, changed_tags
        ) VALUES (
            p_exercise_id, err, p_practice_id, p_coach_id,
            'taught', p_source, added
        ) RETURNING id INTO new_id;
        result := result || jsonb_build_array(jsonb_build_object(
            'teaching_id', new_id, 'error_id', err, 'added', added));
    END LOOP;
    IF changed THEN
        UPDATE diagnostic_exercise
           SET acoustic_problem_tags = tags, updated_at = now()
         WHERE exercise_id = p_exercise_id;
    END IF;
    RETURN result;
END;
$$;

-- Undo one teaching made from this moment. Returns
--   {"undone": bool, "removed": bool, "reason": text|null}
-- reason is 'not_found' (no such teaching for this moment) or
-- 'already_undone'.
CREATE OR REPLACE FUNCTION public.undo_diagnostic_exercise_teaching_v1(
    p_teaching_id UUID,
    p_practice_id UUID,
    p_coach_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = public
AS $$
DECLARE
    taught diagnostic_exercise_teaching%ROWTYPE;
    tags TEXT[];
    removed BOOLEAN := FALSE;
BEGIN
    SELECT * INTO taught
      FROM diagnostic_exercise_teaching
     WHERE id = p_teaching_id AND action = 'taught';
    IF NOT FOUND OR taught.practice_id IS DISTINCT FROM p_practice_id THEN
        RETURN jsonb_build_object(
            'undone', false, 'removed', false, 'reason', 'not_found');
    END IF;
    -- The exercise row first, in the same order teach takes its locks.
    SELECT acoustic_problem_tags INTO tags
      FROM diagnostic_exercise
     WHERE exercise_id = taught.exercise_id
       FOR UPDATE;
    IF EXISTS (SELECT 1 FROM diagnostic_exercise_teaching
                WHERE undoes_id = taught.id) THEN
        RETURN jsonb_build_object(
            'undone', false, 'removed', false, 'reason', 'already_undone');
    END IF;
    tags := COALESCE(tags, '{}'::TEXT[]);
    IF taught.error_id = ANY(tags)
       AND COALESCE(array_length(tags, 1), 0) > 1
       -- A teaching put the tag there: the last change to it was an add.
       AND COALESCE((
           SELECT last_change.action = 'taught'
             FROM diagnostic_exercise_teaching last_change
            WHERE last_change.exercise_id = taught.exercise_id
              AND last_change.error_id = taught.error_id
              AND last_change.changed_tags
            ORDER BY last_change.seq DESC
            LIMIT 1), FALSE)
       -- And nothing else still claims the fix.
       AND NOT EXISTS (
           SELECT 1 FROM diagnostic_exercise_teaching other
            WHERE other.exercise_id = taught.exercise_id
              AND other.error_id = taught.error_id
              AND other.action = 'taught'
              AND other.id <> taught.id
              AND NOT EXISTS (
                  SELECT 1 FROM diagnostic_exercise_teaching u
                   WHERE u.undoes_id = other.id))
    THEN
        UPDATE diagnostic_exercise
           SET acoustic_problem_tags = array_remove(tags, taught.error_id),
               updated_at = now()
         WHERE exercise_id = taught.exercise_id;
        removed := TRUE;
    END IF;
    INSERT INTO diagnostic_exercise_teaching (
        exercise_id, error_id, practice_id, coach_id,
        action, source, changed_tags, undoes_id
    ) VALUES (
        taught.exercise_id, taught.error_id, taught.practice_id, p_coach_id,
        'undone', taught.source, removed, taught.id
    );
    RETURN jsonb_build_object('undone', true, 'removed', removed,
                              'reason', NULL);
END;
$$;

-- service_role only, by exact signature. The coach routes are the only
-- callers, and they run as service_role.
REVOKE ALL ON FUNCTION public.teach_diagnostic_exercise_v1(
    TEXT, UUID, UUID, TEXT[], TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.teach_diagnostic_exercise_v1(
    TEXT, UUID, UUID, TEXT[], TEXT
) TO service_role;

REVOKE ALL ON FUNCTION public.undo_diagnostic_exercise_teaching_v1(
    UUID, UUID, UUID
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.undo_diagnostic_exercise_teaching_v1(
    UUID, UUID, UUID
) TO service_role;
