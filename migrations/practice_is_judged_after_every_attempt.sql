-- Practice is judged after every attempt (contract 29a / 35d, founder
-- 2026-09-25, Q17 A / Q18 A).
--
-- 1. The owner's answers about practice take the same five values as the first
--    judgement: yes, in_between, no, not_sure, audio_unclear. The three yes/no
--    CHECKs are replaced (found by definition, since their names were
--    generated). Only `user_answer = 'yes'` still counts towards Voice Album.
-- 2. `ideal_text_practice_adoptions` keeps the words an adopted practice
--    attempt replaced, for the paragraph history.
-- 3. `adopt_practice_passage_v1` writes the adopted words, their Slide map and
--    that history row in ONE transaction, and refuses a document that moved
--    since it was read (a Take finished in between).
--
-- Additive and idempotent.

BEGIN;

DO $widen$
DECLARE
    c RECORD;
BEGIN
    FOR c IN
        SELECT con.conname, rel.relname
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid = con.conrelid
          JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
         WHERE nsp.nspname = 'public'
           AND con.contype = 'c'
           AND (
             (rel.relname = 'confident_voice_practice_attempt'
              AND pg_get_constraintdef(con.oid) ~ '\muser_answer\M')
             OR (rel.relname = 'confident_voice_practice'
              AND pg_get_constraintdef(con.oid)
                  ~ '\m(original_user_answer|final_user_answer)\M')
           )
    LOOP
        EXECUTE format('ALTER TABLE public.%I DROP CONSTRAINT %I',
                       c.relname, c.conname);
    END LOOP;
END
$widen$;

ALTER TABLE public.confident_voice_practice_attempt
    ADD CONSTRAINT cvp_attempt_user_answer_five CHECK (user_answer IN
        ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear'));
ALTER TABLE public.confident_voice_practice
    ADD CONSTRAINT cvp_original_user_answer_five CHECK (original_user_answer IN
        ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear'));
ALTER TABLE public.confident_voice_practice
    ADD CONSTRAINT cvp_final_user_answer_five CHECK (final_user_answer IN
        ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear'));

CREATE TABLE IF NOT EXISTS public.ideal_text_practice_adoptions (
    id            BIGSERIAL   PRIMARY KEY,
    arc_id        TEXT        NOT NULL,
    user_id       TEXT        NOT NULL,
    slide_index   INTEGER     NULL CHECK (slide_index >= 0),
    practice_id   UUID        NOT NULL,
    attempt_id    UUID        NOT NULL,
    before_text   TEXT        NOT NULL,
    after_text    TEXT        NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ideal_text_practice_adoption_once UNIQUE (attempt_id)
);

CREATE INDEX IF NOT EXISTS idx_practice_adoptions_slide
    ON public.ideal_text_practice_adoptions (arc_id, user_id, slide_index, id);

ALTER TABLE public.ideal_text_practice_adoptions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.ideal_text_practice_adoptions
    FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.adopt_practice_passage_v1(
    p_arc_id TEXT,
    p_owner_user_id UUID,
    p_expected_text TEXT,
    p_new_text TEXT,
    p_new_document JSONB,
    p_slide_index INTEGER,
    p_practice_id UUID,
    p_attempt_id UUID,
    p_before TEXT,
    p_after TEXT
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    ideal public.coach_arc_ideal_text%ROWTYPE;
    practice public.confident_voice_practice%ROWTYPE;
BEGIN
    SELECT * INTO practice
      FROM public.confident_voice_practice
     WHERE id = p_practice_id AND owner_user_id = p_owner_user_id;
    IF practice.id IS NULL OR practice.project_id::text <> p_arc_id THEN
        RAISE EXCEPTION 'practice does not belong to this owner and Project';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.confident_voice_practice_attempt
                    WHERE id = p_attempt_id AND practice_id = p_practice_id) THEN
        RAISE EXCEPTION 'attempt does not belong to this practice';
    END IF;
    IF NULLIF(trim(COALESCE(p_new_text, '')), '') IS NULL THEN
        RAISE EXCEPTION 'adopted text is empty';
    END IF;

    SELECT * INTO ideal
      FROM public.coach_arc_ideal_text
     WHERE arc_id = p_arc_id
     FOR UPDATE;
    IF ideal.arc_id IS NULL OR ideal.auto_text IS DISTINCT FROM p_expected_text THEN
        RETURN jsonb_build_object('adopted', false, 'reason', 'document_moved');
    END IF;
    IF EXISTS (SELECT 1 FROM public.ideal_text_practice_adoptions
                WHERE attempt_id = p_attempt_id) THEN
        RETURN jsonb_build_object('adopted', false, 'reason', 'already_adopted');
    END IF;

    UPDATE public.coach_arc_ideal_text
       SET auto_text = p_new_text,
           document = COALESCE(p_new_document, document),
           auto_updated_at = now(),
           text = CASE WHEN updated_by IS NULL AND approved_at IS NULL
                       THEN p_new_text ELSE text END,
           updated_at = now()
     WHERE arc_id = p_arc_id;

    INSERT INTO public.ideal_text_practice_adoptions (
        arc_id, user_id, slide_index, practice_id, attempt_id,
        before_text, after_text
    ) VALUES (
        p_arc_id, p_owner_user_id::text, p_slide_index, p_practice_id,
        p_attempt_id, p_before, p_after
    );

    RETURN jsonb_build_object('adopted', true);
END;
$$;

REVOKE ALL ON FUNCTION public.adopt_practice_passage_v1(
    TEXT, UUID, TEXT, TEXT, JSONB, INTEGER, UUID, UUID, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.adopt_practice_passage_v1(
    TEXT, UUID, TEXT, TEXT, JSONB, INTEGER, UUID, UUID, TEXT, TEXT
) TO service_role;

COMMIT;
