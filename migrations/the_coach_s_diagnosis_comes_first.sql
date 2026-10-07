-- 0445 · the coach's diagnosis comes first (founder 2026-10-06, coach panel
-- redesign lock flow 6, N56.1; the words CP2 A; Q-B7 A and Q-B12 A, N62;
-- build plan D-CP-4)
--
-- WHY. The coach panel lock, flow 6: "Error moments: the diagnosis first.
-- 'What kind of error is it?' The errors the machine heard come first,
-- marked 'The machine heard this'. Then the others, then 'Something else ·
-- Name a new error' and 'I don't hear an error'." Q-B7 A: "An error a coach
-- names in one field is stored as 'named by a coach' until the founder
-- writes its definition and question in admin. The exercise reaches the
-- speaker now and waits in the library. The coach's list shows every active
-- error plus coach-named ones. Naming is a signal for the founder only;
-- readiness for a detector still comes from blind 'Do you hear it?'
-- answers." Q-B12 A: when a coach changes an answer, the new one replaces
-- it and the old one stays in history for audit.
--
-- The library (speaking_error, 0332) can hold only an error WITH its
-- written definition and its one question (CONSTRUCT): a coach's name in
-- one field has neither, so it cannot go there yet. And the diagnosis is the
-- coach's own judgement about one recording: coach provenance (L3), never a
-- training label, never a quorum vote, never a detector's readiness.
--
-- WHAT. Two tables and one writer:
--
--   coach_named_errors        an error a coach named in one field: the
--                             words as the coach said them, a key for the
--                             same words said twice, who named it first and
--                             when. "Named by a coach" until the founder
--                             links it to a library entry they wrote
--                             (speaking_error_id, set in admin, outside this
--                             file). Library content, not a person's record.
--   coach_moment_diagnoses    one coach's diagnosis of one moment, versioned:
--                             a library error, a coach-named error, or "I
--                             don't hear an error". Exactly one current row
--                             per moment and coach (superseded_at IS NULL);
--                             a changed diagnosis supersedes the current row
--                             and writes the next version (Q-B12 A), so the
--                             history stays. Never read by the speaker.
--   set_coach_moment_diagnosis_v1   the one writer: validates the shape,
--                             finds or files the coach-named error, leaves a
--                             diagnosis that says the same thing as before
--                             untouched, otherwise supersedes and versions.
--                             Returns the current row.
--
-- WHAT IS NOT HERE. No count, no score, nothing a speaker reads (AC-9): the
-- speaker's payload never carries a coach's diagnosis. Nothing joins these
-- tables to confidence_labels, to the blind "Do you hear it?" answers
-- (error_presence_audit) or to any readiness report; naming is a signal the
-- founder reads in admin. The route sits behind the blind gate: a coach
-- diagnoses a moment only after their own blind rating of it (BLIND COACH).
--
-- Idempotent: IF NOT EXISTS, CREATE OR REPLACE; applied twice it changes
-- nothing. Writes no row on its own. Locks: only the new tables
-- (speaking_error is referenced by a foreign key, which takes a brief share
-- lock on that small library table, never a rewrite).
--
-- Rollback (a new forward migration): DROP FUNCTION
-- public.set_coach_moment_diagnosis_v1(text, text, text, text, text, text);
-- DROP TABLE public.coach_moment_diagnoses; DROP TABLE
-- public.coach_named_errors. Nothing else depends on them.

BEGIN;

CREATE TABLE IF NOT EXISTS public.coach_named_errors (
    id                uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    name              text        NOT NULL,
    name_key          text        NOT NULL,
    named_by          text        NOT NULL,
    first_named_at    timestamptz NOT NULL DEFAULT now(),
    speaking_error_id text        NULL REFERENCES public.speaking_error (error_id),
    linked_at         timestamptz NULL,
    CONSTRAINT coach_named_errors_name_length CHECK (
        char_length(btrim(name)) BETWEEN 1 AND 120),
    CONSTRAINT coach_named_errors_key_shape CHECK (
        name_key = lower(regexp_replace(btrim(name), '\s+', ' ', 'g'))),
    CONSTRAINT coach_named_errors_once UNIQUE (name_key),
    CONSTRAINT coach_named_errors_link_shape CHECK (
        (speaking_error_id IS NULL) = (linked_at IS NULL))
);
ALTER TABLE public.coach_named_errors ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_named_errors IS
    'An error a coach named in one field (0445; Q-B7 A): the words as said, '
    'one row per distinct wording, who named it first. "Named by a coach" '
    'until the founder writes its definition and question in admin and links '
    'it (speaking_error_id). Library content; a signal for the founder only, '
    'never a detector''s readiness.';

CREATE TABLE IF NOT EXISTS public.coach_moment_diagnoses (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    take_session_id text        NOT NULL,
    snippet_id      text        NOT NULL,
    coach_id        text        NOT NULL,
    kind            text        NOT NULL,
    error_id        text        NULL REFERENCES public.speaking_error (error_id),
    named_error_id  uuid        NULL REFERENCES public.coach_named_errors (id),
    version         integer     NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    superseded_at   timestamptz NULL,
    CONSTRAINT coach_moment_diagnoses_kind_check CHECK (
        kind IN ('error', 'named_error', 'no_error')),
    CONSTRAINT coach_moment_diagnoses_shape CHECK (
        (kind = 'error' AND error_id IS NOT NULL AND named_error_id IS NULL)
        OR (kind = 'named_error' AND named_error_id IS NOT NULL AND error_id IS NULL)
        OR (kind = 'no_error' AND error_id IS NULL AND named_error_id IS NULL)),
    CONSTRAINT coach_moment_diagnoses_ids_check CHECK (
        length(btrim(take_session_id)) > 0 AND length(btrim(snippet_id)) > 0
        AND length(btrim(coach_id)) > 0),
    CONSTRAINT coach_moment_diagnoses_version_positive CHECK (version >= 1),
    CONSTRAINT coach_moment_diagnoses_versions UNIQUE (snippet_id, coach_id, version)
);
-- Exactly one current diagnosis per moment and coach; history below it.
CREATE UNIQUE INDEX IF NOT EXISTS coach_moment_diagnoses_one_current
    ON public.coach_moment_diagnoses (snippet_id, coach_id)
    WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS coach_moment_diagnoses_take_idx
    ON public.coach_moment_diagnoses (take_session_id);
ALTER TABLE public.coach_moment_diagnoses ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_moment_diagnoses IS
    'One coach''s diagnosis of one moment (0445; coach panel lock flow 6; '
    'Q-B7 A; Q-B12 A): a library error, a coach-named error, or "I don''t '
    'hear an error". One current row per moment and coach; a change '
    'supersedes it and writes the next version, so the history stays. Coach '
    'provenance (L3): never a training label, never a vote, never shown to '
    'the speaker. Written only by set_coach_moment_diagnosis_v1; purged with '
    'the Take and with the coach.';

CREATE OR REPLACE FUNCTION public.set_coach_moment_diagnosis_v1(
    p_take_session_id text,
    p_snippet_id text,
    p_coach_id text,
    p_kind text,
    p_error_id text,
    p_new_name text
) RETURNS public.coach_moment_diagnoses
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    v_name     text := NULLIF(regexp_replace(btrim(COALESCE(p_new_name, '')), '\s+', ' ', 'g'), '');
    v_named_id uuid := NULL;
    v_error_id text := NULLIF(btrim(COALESCE(p_error_id, '')), '');
    v_current  public.coach_moment_diagnoses;
    v_next     integer;
    v_row      public.coach_moment_diagnoses;
BEGIN
    IF COALESCE(btrim(p_take_session_id), '') = ''
       OR COALESCE(btrim(p_snippet_id), '') = ''
       OR COALESCE(btrim(p_coach_id), '') = ''
       OR p_kind IS NULL OR p_kind NOT IN ('error', 'named_error', 'no_error')
       OR (p_kind = 'error' AND (v_error_id IS NULL OR v_name IS NOT NULL))
       OR (p_kind = 'named_error' AND (v_name IS NULL OR v_error_id IS NOT NULL
                                       OR char_length(v_name) > 120))
       OR (p_kind = 'no_error' AND (v_error_id IS NOT NULL OR v_name IS NOT NULL))
    THEN
        RAISE EXCEPTION 'COACH_DIAGNOSIS_INPUT_INVALID';
    END IF;

    IF p_kind = 'error' THEN
        -- A library error the coach may still choose: active, whatever its
        -- detector status (observed, shadow, detected).
        IF NOT EXISTS (SELECT 1 FROM public.speaking_error
                        WHERE error_id = v_error_id AND active) THEN
            RAISE EXCEPTION 'COACH_DIAGNOSIS_ERROR_NOT_IN_LIBRARY';
        END IF;
    ELSIF p_kind = 'named_error' THEN
        -- The same words said twice are one coach-named error; a name the
        -- founder has since linked to a library entry becomes that entry.
        INSERT INTO public.coach_named_errors (name, name_key, named_by)
        VALUES (v_name, lower(v_name), p_coach_id)
        ON CONFLICT (name_key) DO NOTHING;
        SELECT id, speaking_error_id INTO v_named_id, v_error_id
          FROM public.coach_named_errors WHERE name_key = lower(v_name);
        IF v_error_id IS NOT NULL THEN
            p_kind := 'error';
            v_named_id := NULL;
        ELSE
            v_error_id := NULL;
        END IF;
    END IF;

    SELECT * INTO v_current FROM public.coach_moment_diagnoses
     WHERE snippet_id = p_snippet_id AND coach_id = p_coach_id
       AND superseded_at IS NULL
       FOR UPDATE;

    -- The same diagnosis again changes nothing (idempotent).
    IF FOUND AND v_current.kind = p_kind
       AND v_current.error_id IS NOT DISTINCT FROM v_error_id
       AND v_current.named_error_id IS NOT DISTINCT FROM v_named_id THEN
        RETURN v_current;
    END IF;

    -- Q-B12 A: the new diagnosis replaces the current one; the old row stays.
    IF FOUND THEN
        UPDATE public.coach_moment_diagnoses
           SET superseded_at = now()
         WHERE id = v_current.id;
    END IF;
    SELECT COALESCE(max(version), 0) + 1 INTO v_next
      FROM public.coach_moment_diagnoses
     WHERE snippet_id = p_snippet_id AND coach_id = p_coach_id;

    INSERT INTO public.coach_moment_diagnoses (
        take_session_id, snippet_id, coach_id, kind, error_id, named_error_id, version
    ) VALUES (
        p_take_session_id, p_snippet_id, p_coach_id, p_kind, v_error_id, v_named_id, v_next
    )
    RETURNING * INTO v_row;
    RETURN v_row;
END;
$$;

COMMENT ON FUNCTION public.set_coach_moment_diagnosis_v1(text, text, text, text, text, text) IS
    'The coach''s diagnosis of a moment (0445): a library error, a coach-named '
    'error (filed as "named by a coach" when new), or no error. The same '
    'diagnosis again is a no-op; a different one supersedes the current row '
    'and writes the next version (Q-B12 A). service_role only.';

-- ── The door ───────────────────────────────────────────────────────────────
-- Browser roles and PUBLIC get nothing on the tables or the function,
-- whatever default privileges the schema carries (Supabase grants
-- anon/authenticated on public by default; PostgREST publishes every public
-- function). The app reads both tables and calls the function with the
-- service key; the purge deletes diagnoses with the Take and with the coach;
-- the diagnoses are written only through the function. The coach-named
-- errors are library content: the founder's admin links them (UPDATE of
-- speaking_error_id and linked_at, in a later file) and nothing deletes them
-- here. Roles are guarded: they exist on Supabase, not on a bare Postgres.
REVOKE ALL ON TABLE public.coach_named_errors FROM PUBLIC;
REVOKE ALL ON TABLE public.coach_moment_diagnoses FROM PUBLIC;
REVOKE ALL ON FUNCTION public.set_coach_moment_diagnosis_v1(text, text, text, text, text, text) FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format('REVOKE ALL ON TABLE public.coach_named_errors FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON TABLE public.coach_moment_diagnoses FROM %I', v_role);
            EXECUTE format('REVOKE ALL ON FUNCTION public.set_coach_moment_diagnosis_v1(text, text, text, text, text, text) FROM %I', v_role);
        END IF;
    END LOOP;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        REVOKE ALL ON TABLE public.coach_named_errors FROM service_role;
        GRANT SELECT ON TABLE public.coach_named_errors TO service_role;
        REVOKE ALL ON TABLE public.coach_moment_diagnoses FROM service_role;
        GRANT SELECT, DELETE ON TABLE public.coach_moment_diagnoses TO service_role;
        GRANT EXECUTE ON FUNCTION public.set_coach_moment_diagnosis_v1(text, text, text, text, text, text) TO service_role;
    END IF;
END $$;

COMMIT;
