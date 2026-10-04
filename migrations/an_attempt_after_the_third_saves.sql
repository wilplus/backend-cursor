-- 0417 · An attempt after the third saves (F1 Repair Plan Phase 4; founder
--        lock 2026-09-30, D2: "attempt 10 works like attempt 1").
--
-- 0279 created confident_voice_practice_attempt with
--     attempt_index INTEGER NOT NULL CHECK (attempt_index BETWEEN 1 AND 3)
-- The route stopped capping attempts on 2026-09-30, but this CHECK did not,
-- so a speaker's fourth attempt was refused by the database with "Could not
-- save that attempt." and its recording was left in the bucket.
--
-- The CHECK was declared inline, so it has no name of our choosing. It is
-- found by its definition (the only CHECK on the table that bounds
-- attempt_index above) and replaced by a named one that keeps the lower
-- bound. The UNIQUE (practice_id, attempt_index) order stays.
--
-- Changes no rows. Idempotent.

BEGIN;

DO $drop_attempt_cap$
DECLARE c record;
BEGIN
    FOR c IN
        SELECT con.conname
          FROM pg_constraint con
         WHERE con.conrelid = 'public.confident_voice_practice_attempt'::regclass
           AND con.contype = 'c'
           AND pg_get_constraintdef(con.oid) ~ 'attempt_index\s*<=\s*3'
    LOOP
        EXECUTE format(
            'ALTER TABLE public.confident_voice_practice_attempt DROP CONSTRAINT %I',
            c.conname);
    END LOOP;
END $drop_attempt_cap$;

ALTER TABLE public.confident_voice_practice_attempt
    DROP CONSTRAINT IF EXISTS confident_voice_practice_attempt_index_positive;
ALTER TABLE public.confident_voice_practice_attempt
    ADD CONSTRAINT confident_voice_practice_attempt_index_positive
    CHECK (attempt_index >= 1);

COMMIT;
