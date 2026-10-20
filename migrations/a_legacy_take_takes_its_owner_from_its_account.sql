-- a_legacy_take_takes_its_owner_from_its_account (0485)
--
-- THE PROBLEM. An account deletion's subject graph (0312,
-- resolve_phase1_purge_subject_graph_v1, wrapped by v2 and v3) holds every
-- Take of the account, by owner principal OR by user id. A Take found only by
-- its user id, whose owner_principal_id is empty, is a "legacy" Take: the
-- graph lists it in unresolved_legacy_take_ids, the orchestrator files it as
-- an `unknown` target (LEGACY_TAKE_OWNER_PRINCIPAL_UNRESOLVED), and the whole
-- erasure stops for review. v2_sessions.owner_principal_id is a nullable copy
-- that most Takes never got, so an account with older Takes could not be
-- erased at all. docs/PHASE1-DELETION-DEPENDENCY-AUDIT.md: "a future
-- resolution requires its own reviewed, typed RPC". This is that RPC
-- (founder 2026-10-20, option 1: three test accounts' Takes could not be
-- erased, and neither could a real speaker's older Takes).
--
-- THE RULE. resolve_legacy_take_owners_v1(principal) gives a legacy Take the
-- owner principal of its own account, and nothing else:
--   * only a Take this account's own graph lists as unresolved;
--   * only while its owner_principal_id is empty (a Take naming another
--     principal is a real conflict and stays unresolved);
--   * only the owner principal whose user_id is the Take's own user_id
--     (owner_principals.user_id is UNIQUE, so there is at most one), and only
--     when that principal is one of this account's graph principals.
-- Anything it cannot settle stays unresolved, so the purge still stops for
-- review on it (fail-closed, as before). It deletes nothing. It returns the
-- Takes it resolved and those still unresolved.
--
-- WHO CALLS IT. services/data_purge.py, once, just before it freezes a new
-- inventory for a purge it is running (never in a preview), so the frozen
-- graph and the freeze's own recomputation both see the resolved owners.
-- service_role only.
--
-- LOCKS. It takes the MLC-3 service purge writer's advisory locks (0327's
-- registry) in that writer's order, a subset of it (rollout policy, the
-- service principal, then each Take's inventory by id), so it serialises
-- with a concurrent service purge of the same principal and cannot deadlock
-- with it. It is not one of 0327's registered writers and re-issues none.
--
-- ADDITIVE AND IDEMPOTENT. One CREATE OR REPLACE FUNCTION and its grants; no
-- table, column or row is created, altered or dropped by running this file.
-- Calling the function twice resolves nothing the second time. No env var.

CREATE OR REPLACE FUNCTION public.resolve_legacy_take_owners_v1(
    p_acquisition_principal_id UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    graph JSONB;
    principal_values TEXT[];
    legacy_values TEXT[];
    resolved_values TEXT[];
    after_graph JSONB;
BEGIN
    IF p_acquisition_principal_id IS NULL THEN
        RAISE EXCEPTION 'LEGACY_TAKE_OWNER_PRINCIPAL_REQUIRED';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2', 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-principal:' || p_acquisition_principal_id::text, 0));

    graph := public.resolve_phase1_purge_subject_graph_v3(p_acquisition_principal_id);
    SELECT ARRAY(SELECT jsonb_array_elements_text(graph -> 'principal_ids'))
      INTO principal_values;
    SELECT ARRAY(SELECT jsonb_array_elements_text(
               graph -> 'unresolved_legacy_take_ids'))
      INTO legacy_values;

    IF COALESCE(array_length(legacy_values, 1), 0) = 0 THEN
        RETURN jsonb_build_object(
            'resolved_take_ids', '[]'::jsonb,
            'unresolved_take_ids', '[]'::jsonb);
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
                'confident-moment-take-inventory:' || take_id, 0))
       FROM unnest(legacy_values) AS take_id
      ORDER BY take_id COLLATE "C";

    WITH settled AS (
        UPDATE public.v2_sessions session
           SET owner_principal_id = principal.id
          FROM public.owner_principals principal
         WHERE session.id::text = ANY(legacy_values)
           AND session.owner_principal_id IS NULL
           AND session.user_id IS NOT NULL
           AND principal.user_id = session.user_id
           AND principal.id::text = ANY(principal_values)
        RETURNING session.id::text AS id
    )
    SELECT COALESCE(array_agg(id ORDER BY id COLLATE "C"), '{}'::text[])
      INTO resolved_values
      FROM settled;

    after_graph := public.resolve_phase1_purge_subject_graph_v3(
        p_acquisition_principal_id);
    RETURN jsonb_build_object(
        'resolved_take_ids', to_jsonb(resolved_values),
        'unresolved_take_ids',
            COALESCE(after_graph -> 'unresolved_legacy_take_ids', '[]'::jsonb));
END;
$$;

REVOKE ALL ON FUNCTION public.resolve_legacy_take_owners_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.resolve_legacy_take_owners_v1(UUID)
    TO service_role;
