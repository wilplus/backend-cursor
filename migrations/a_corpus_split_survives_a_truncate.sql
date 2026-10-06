-- 0434 · a corpus split survives a TRUNCATE too (founder 2026-10-06, panel
-- answer CO1 A, decisions log N56.4: "decided by a fixed hash and never
-- re-shuffled")
--
-- WHY. 0433 made public.corpus_speaker_splits insert-once with a ROW-level
-- BEFORE UPDATE OR DELETE trigger. Row-level triggers do not fire on
-- TRUNCATE, so one TRUNCATE emptied the table and the next import of every
-- speaker would be assigned again from whatever the code's salt and rule say
-- that day: exactly the re-shuffle the table exists to prevent. The
-- independent check of 0433 found it.
--
-- WHAT. One STATEMENT-level BEFORE TRUNCATE trigger on the same table,
-- calling 0433's refusing function (public.corpus_speaker_splits_never_change,
-- which raises CORPUS_SPLIT_IMMUTABLE before it could return anything, so it
-- serves a statement trigger unchanged). The function is restated with the
-- same body and the same revokes, so this file stands on its own if it is
-- ever applied to a database whose 0433 function was altered by hand.
--
-- NON-DESTRUCTIVE AND IDEMPOTENT. No table, column, row or grant is
-- created or dropped; DROP TRIGGER IF EXISTS then CREATE; no env var.
--
-- Rollback (a new forward migration): drop the trigger
-- corpus_speaker_splits_never_truncate.

BEGIN;

CREATE OR REPLACE FUNCTION public.corpus_speaker_splits_never_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    RAISE EXCEPTION 'CORPUS_SPLIT_IMMUTABLE: a corpus speaker keeps its split'
        USING ERRCODE = 'check_violation';
END;
$$;
REVOKE ALL ON FUNCTION public.corpus_speaker_splits_never_change() FROM PUBLIC;
DO $$
DECLARE
    v_role text;
BEGIN
    FOREACH v_role IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = v_role) THEN
            EXECUTE format(
                'REVOKE ALL ON FUNCTION public.corpus_speaker_splits_never_change() FROM %I',
                v_role);
        END IF;
    END LOOP;
END $$;

DROP TRIGGER IF EXISTS corpus_speaker_splits_never_truncate
    ON public.corpus_speaker_splits;
CREATE TRIGGER corpus_speaker_splits_never_truncate
    BEFORE TRUNCATE ON public.corpus_speaker_splits
    FOR EACH STATEMENT EXECUTE FUNCTION public.corpus_speaker_splits_never_change();

COMMIT;
