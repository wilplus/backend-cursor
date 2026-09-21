-- The V3 candidate-set write still could not succeed: one variable named
-- after a column made every "row.x = x" comparison ambiguous.
--
-- PRODUCTION, 2026-09-21. With 0344's parenthesis in place the write got
-- past its advisory lock for the first time, inserted the transcript, the
-- slides, the paragraphs, the candidate set, every candidate and every
-- exposure -- and then PostgreSQL answered, on the very first count:
--
--     {'code': '42702', 'message': 'column reference "candidate_set_id"
--      is ambiguous', 'details': 'It could refer to either a PL/pgSQL
--      variable or a table column.'}
--
-- THE LINES, in `record_feedback_v3_service_candidate_set_v1` (D2):
--
--     DECLARE
--         candidate_set_id UUID;
--     ...
--     SELECT count(*) INTO candidate_count
--       FROM public.feedback_candidates row
--      WHERE row.candidate_set_id = candidate_set_id;
--
-- The left side is qualified; the right side is not, and it names both the
-- PL/pgSQL variable and a column of `row`. PL/pgSQL's default
-- `plpgsql.variable_conflict = error` refuses to guess, so the statement
-- raises, the transaction rolls back, and the caller logs "serving without
-- lineage" and serves V3 without its audit trail. The same comparison
-- appears four times in this body (two in the replay branch, two in the
-- ledger check), so no path through the function past the inserts can
-- finish. It was masked until 0344 because the write died earlier, at the
-- lock.
--
-- THE REPAIR IS THE PRAGMA THE FUNCTION WAS WRITTEN FOR. Every table in
-- this body is aliased (`row`, `attempt`, `object_row`, `project`,
-- `source_snippet`, `chosen`) and every column reference is qualified
-- through that alias; a bare name is, by the author's own convention, a
-- variable. `#variable_conflict use_variable` states that convention to
-- PL/pgSQL so the four comparisons resolve as written. Renaming the
-- variable instead would mean rewriting a dozen statements by string
-- replacement in a 350-line body nobody re-reviews here.
--
-- WHY THIS REPAIRS IN PLACE RATHER THAN RE-CREATING THE FUNCTION. Same
-- reason as 0344: D4 rewrote this body at migration time (swapping
-- `require_mlc3_service_principal_v1` for `require_mlc3_service_access_v2`)
-- and 0344 parenthesised its lock key. Re-issuing D2's text would revert
-- both. So this reads the CURRENT definition with `pg_get_functiondef`,
-- inserts the one pragma line at the top of the body, and re-executes it.
--
-- IDEMPOTENT. Re-running finds the pragma and returns without touching
-- anything. It degrades gracefully when the function is absent (a cluster
-- built before D2), and it refuses loudly rather than guessing if the body
-- does not open with the DECLARE block it expects.

DO $migration$
DECLARE
    signature CONSTANT TEXT :=
        'public.record_feedback_v3_service_candidate_set_v1'
        || '(uuid,uuid,uuid,jsonb)';
    pragma CONSTANT TEXT := '#variable_conflict use_variable';
    opening CONSTANT TEXT := '$function$' || E'\nDECLARE\n';
    function_oid OID;
    definition TEXT;
    hits INTEGER;
BEGIN
    function_oid := to_regprocedure(signature);
    IF function_oid IS NULL THEN
        RAISE NOTICE
            'candidate-set variable conflict: % absent, nothing to repair',
            signature;
        RETURN;
    END IF;

    definition := pg_get_functiondef(function_oid);

    IF position(pragma IN definition) > 0 THEN
        RAISE NOTICE
            'candidate-set variable conflict: pragma present, no change';
        RETURN;
    END IF;

    -- Exactly one body opening, or stop. `pg_get_functiondef` renders the
    -- body as `AS $function$` followed by the stored text, which D2 began
    -- with a DECLARE block. If a future rewrite changes that shape, inserting
    -- a pragma somewhere else would be a guess about statements nobody
    -- reviewed here.
    hits := (length(definition) - length(replace(definition, opening, '')))
            / length(opening);
    IF hits <> 1 THEN
        RAISE EXCEPTION
            'CANDIDATE_SET_BODY_SHAPE_UNEXPECTED: % occurrences of the '
            'body opening in %', hits, signature;
    END IF;

    definition := replace(
        definition, opening,
        '$function$' || E'\n' || pragma || E'\nDECLARE\n');
    EXECUTE definition;
    RAISE NOTICE 'candidate-set variable conflict: pragma added to %',
        signature;
END;
$migration$;
