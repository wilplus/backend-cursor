-- A coach answers a practice recording the same five ways (founder 2026-09-29,
-- Q3 + Q3a).
--
-- The coach is now asked the same snapshot question the speaker is asked,
-- "Does this sound confident to you?", with the same five answers: Yes,
-- In-between, No, Not sure, Audio unclear. One judgement screen everywhere.
-- confident_voice_practice_attempt.coach_confidence_decision only allowed
-- yes/no; this widens it to the five values the speaker's own answer column
-- already allows (0351, practice_is_judged_after_every_attempt.sql).
--
-- The Voice Album still needs the coach's real Yes (35g); every other answer
-- keeps a recording out. Nothing is rewritten: existing yes/no rows are
-- already valid under the wider rule. Additive and idempotent. No env var.

BEGIN;

DO $widen$
DECLARE
    c RECORD;
BEGIN
    FOR c IN
        SELECT con.conname
          FROM pg_constraint con
          JOIN pg_class rel ON rel.oid = con.conrelid
          JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
         WHERE nsp.nspname = 'public'
           AND rel.relname = 'confident_voice_practice_attempt'
           AND con.contype = 'c'
           AND pg_get_constraintdef(con.oid) ~ '\mcoach_confidence_decision\M'
    LOOP
        EXECUTE format(
            'ALTER TABLE public.confident_voice_practice_attempt DROP CONSTRAINT %I',
            c.conname);
    END LOOP;
END
$widen$;

ALTER TABLE public.confident_voice_practice_attempt
    ADD CONSTRAINT cvp_attempt_coach_decision_five
    CHECK (coach_confidence_decision IS NULL OR coach_confidence_decision IN
        ('yes', 'in_between', 'no', 'not_sure', 'audio_unclear'));

COMMIT;
