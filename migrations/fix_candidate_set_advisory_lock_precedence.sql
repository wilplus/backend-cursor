-- The V3 candidate-set write could never succeed: one missing pair of
-- parentheses turned a lock key into a JSON parse.
--
-- PRODUCTION, 2026-09-19. The first time V3 ever reached its candidate-set
-- write -- `piece_has_no_part_id` (#564/#568) had stood it down before this
-- point on every Take since the cutover -- PostgreSQL answered:
--
--     {'code': '22P02', 'details': 'Token "feedback" is invalid.',
--      'message': 'invalid input syntax for type json'}
--
-- THE LINE, in `record_feedback_v3_service_candidate_set_v1` (D2):
--
--     PERFORM pg_advisory_xact_lock(hashtextextended(
--         'feedback-v3-service-candidate-set:' ||
--         p_bundle->>'idempotency_key', 0
--     ));
--
-- `||` and `->>` are both in PostgreSQL's "any other operator" precedence
-- class and are LEFT associative, so this does not parse as
-- `literal || (p_bundle->>'key')`. It parses as
-- `(literal || p_bundle) ->> 'key'`, which resolves to `jsonb || jsonb`,
-- which coerces the literal to jsonb, which asks the JSON lexer to read
-- `feedback-v3-service-candidate-set:`. The lexer takes the bare word
-- `feedback`, meets the `-`, and raises 22P02 -- the exact error above,
-- reproduced byte for byte on a local 16 cluster before this file existed:
--
--     SELECT hashtextextended('feedback-v3-service-candidate-set:' ||
--                             '{"idempotency_key":"k"}'::jsonb->>'k', 0);
--     ERROR:  invalid input syntax for type json
--     DETAIL:  Token "feedback" is invalid.
--
-- Every other advisory lock in D2 concatenates a plain TEXT parameter
-- (`'feedback-v3-service-membership:' || p_idempotency_key`) and is
-- unaffected. A scan of the whole migrations tree finds this one instance.
--
-- WHY THIS REPAIRS IN PLACE RATHER THAN RE-CREATING THE FUNCTION. D4
-- (`add_mlc3_general_user_service_d4.sql`) rewrites this function's body at
-- migration time, swapping `require_mlc3_service_principal_v1` for
-- `require_mlc3_service_access_v2`. Re-issuing D2's text would silently
-- revert that cutover. So this reads the CURRENT definition with
-- `pg_get_functiondef`, replaces the one broken expression, and re-executes
-- it -- the same device D4 uses, for the same reason.
--
-- IDEMPOTENT. Re-running finds the repaired form and returns without
-- touching anything. It degrades gracefully when the function is absent
-- (a cluster built before D2), and it refuses loudly rather than guessing
-- if the expression it expects is neither broken nor already fixed.

DO $migration$
DECLARE
    signature CONSTANT TEXT :=
        'public.record_feedback_v3_service_candidate_set_v1'
        || '(uuid,uuid,uuid,jsonb)';
    broken CONSTANT TEXT := 'p_bundle->>''idempotency_key'', 0';
    repaired CONSTANT TEXT := '(p_bundle->>''idempotency_key''), 0';
    function_oid OID;
    definition TEXT;
    hits INTEGER;
BEGIN
    function_oid := to_regprocedure(signature);
    IF function_oid IS NULL THEN
        RAISE NOTICE
            'candidate-set advisory lock: % absent, nothing to repair',
            signature;
        RETURN;
    END IF;

    definition := pg_get_functiondef(function_oid);

    IF position(repaired IN definition) > 0 THEN
        RAISE NOTICE
            'candidate-set advisory lock: already parenthesised, no change';
        RETURN;
    END IF;

    -- Exactly one, or stop. `idempotency_key` appears five times in this
    -- body; only the advisory-lock call carries the `, 0` seed. If a future
    -- edit makes that untrue, replacing "all of them" would be a silent
    -- rewrite of statements nobody reviewed here.
    hits := (length(definition) - length(replace(definition, broken, '')))
            / length(broken);
    IF hits <> 1 THEN
        RAISE EXCEPTION
            'CANDIDATE_SET_LOCK_PATTERN_UNEXPECTED: % occurrences of the '
            'advisory-lock expression in %', hits, signature;
    END IF;

    definition := replace(definition, broken, repaired);
    EXECUTE definition;
    RAISE NOTICE 'candidate-set advisory lock: parenthesised in %', signature;
END;
$migration$;
