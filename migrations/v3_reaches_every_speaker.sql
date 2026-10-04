-- 0415 · V3 reaches every speaker (F1 Repair Plan Phase 2; founder
--        2026-10-03, N29 answer 1: "Every speaker").
--
-- WHY. `read_feedback_v3_candidate_source_snapshot_v1` (0342) -- the read every
-- served V3 Feedback set starts from -- calls
-- `require_mlc3_service_principal_v1`, which raised
-- MLC3_SERVICE_PRINCIPAL_NOT_ALLOWED for any principal without an active row
-- in `mlc3_service_principal_allowlist`. That list belonged to the retired
-- MLC-3 first-client loop and held the founder. Every other speaker -- every
-- account, every guest -- got the V2 stand-in rows instead of the served
-- policy (contract 24b), which is the defect the F1 Repair Plan names first.
--
-- WHAT CHANGES. Only the allowlist half of one condition:
--
--   * the allowlist is consulted only while `ring_settings` holds
--     `v3_requires_allowlist = true`. Absent or false (the default), every
--     principal passes it. To switch back without a deploy:
--
--         INSERT INTO public.ring_settings (key, value, changed_by)
--         VALUES ('v3_requires_allowlist', 'true'::jsonb, 'founder')
--         ON CONFLICT (key) DO UPDATE
--            SET value = EXCLUDED.value, changed_by = EXCLUDED.changed_by,
--                changed_at = now();
--
--   * the pending-deletion check is unchanged and always holds, with 0378's
--     narrowing (account-wide purges only; a project purge pauses only its
--     project, which the per-project checks already do) written into the
--     body rather than re-applied by regexp.
--
-- Everything else in the body is 0339's, verbatim: the read-committed guard,
-- the canonical lock order (rollout policy, then principal), the active
-- contract requirement and the advisory D4 lineage step.
--
-- Config first (CLAUDE.md): MLC3_SERVICE_ENABLED=1 on the web service, read in
-- its boot log, before this merges -- the Python side still requires it.
--
-- Changes no rows. Idempotent.

BEGIN;

CREATE OR REPLACE FUNCTION public.v3_requires_allowlist_v1()
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public AS $$
    SELECT COALESCE((
        SELECT (value #>> '{}')::boolean
          FROM public.ring_settings
         WHERE key = 'v3_requires_allowlist'
           AND jsonb_typeof(value) = 'boolean'
    ), false);
$$;

REVOKE ALL ON FUNCTION public.v3_requires_allowlist_v1()
    FROM PUBLIC, anon, authenticated, service_role;

CREATE OR REPLACE FUNCTION public.require_mlc3_service_principal_v1(
    p_acquisition_principal_id UUID
) RETURNS public.mlc3_service_contracts
LANGUAGE plpgsql SECURITY DEFINER VOLATILE
SET search_path = public AS $$
DECLARE
    contract public.mlc3_service_contracts;
    wall_now TIMESTAMPTZ := clock_timestamp();
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'MLC3_SERVICE_REQUIRES_READ_COMMITTED';
    END IF;
    -- D11 lock order (the marker test_purge_scope_postgres reads).
    -- CANONICAL LOCK ORDER: rollout policy, THEN principal (2026-09-18).
    -- The D2 body this restores took only the principal lock, because before
    -- D4 there was no rollout-policy lock to order against. Reinstating it
    -- unchanged put this function alone on principal -> rollout-policy while
    -- lock_confident_moment_inventory_v1, require_mlc3_service_access_v2 and
    -- ensure_mlc3_service_enrollment_v2 all take rollout-policy -> principal.
    --
    -- The rehearsal lane `d11-legacy-root-order` caught it: it holds
    -- mlc3-rollout-policy-v2 and asserts activate_synthetic_root_phrase_v1
    -- blocks on THAT lock and holds nothing else yet. With the inverted order
    -- the lane wedged rather than failing, which is what an ordering bug looks
    -- like before it is a production deadlock between a serving read and a
    -- rollout change.
    PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2', 0));
    PERFORM pg_advisory_xact_lock(hashtextextended(
        'mlc3-service-principal:' || p_acquisition_principal_id::TEXT, 0
    ));
    SELECT * INTO contract
      FROM public.mlc3_service_contracts
     WHERE contract_version = 'mlc3-first-client-service-v1'
       AND state = 'active'
       AND active_from <= wall_now
       AND (retired_at IS NULL OR retired_at > wall_now)
       AND length(btrim(practice_bucket)) > 0
       AND length(btrim(coach_video_bucket)) > 0
     FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'MLC3_SERVICE_CONTRACT_NOT_ACTIVE';
    END IF;
    -- 0415 (N29.1, Phase 2): V3 reaches every speaker. The allowlist is
    -- consulted only while `ring_settings.v3_requires_allowlist` is true --
    -- the switch back, flippable from the SQL editor without a deploy. The
    -- pending-deletion check always holds (0378: account-wide purges only).
    IF (public.v3_requires_allowlist_v1() AND NOT EXISTS (
        SELECT 1 FROM public.mlc3_service_principal_allowlist allowed
         WHERE allowed.acquisition_principal_id = p_acquisition_principal_id
           AND allowed.contract_version = contract.contract_version
           AND allowed.state = 'active'
           AND allowed.revoked_at IS NULL
    )) OR EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id = p_acquisition_principal_id
           AND purge.state <> 'done'
           AND purge.project_id IS NULL /* 0378: account-wide purges only */
    ) THEN
        RAISE EXCEPTION 'MLC3_SERVICE_PRINCIPAL_NOT_ALLOWED';
    END IF;
    -- D4 LINEAGE, ADVISORY (2026-09-18). `require_mlc3_service_access_v2`
    -- resolves the general-user rollout and, as a side effect, sets the
    -- transaction-local authority that `prepare_mlc3_rollout_*_row_v2` stamps
    -- onto new rows. Where that rollout IS running, this keeps every row's
    -- lineage exactly as D4 wrote it.
    --
    -- Where it is not, serving continues. The trigger already contemplates
    -- this: with no transaction-local mode it does `RETURN NEW` and the row
    -- keeps its historical `allowlisted_service` / `synthetic_dark` value with
    -- NULL lineage, which the rollout-subject CHECK explicitly permits
    -- (`rollout_operation_mode IS NULL OR (...)`). That is the state the
    -- first-client service ran in before D4 existed.
    --
    -- Only the six "this principal is not in the general-user rollout" codes
    -- are absorbed -- the same list `_CONFIDENT_MOMENT_INELIGIBLE_CODES` uses
    -- in routes/v2/explore_ideal_text.py, and the same idiom the coaching
    -- bundle already uses. A deadlock, a timeout or a contract fault still
    -- aborts, because those are faults rather than a statement about who this
    -- speaker is.
    BEGIN
        PERFORM public.require_mlc3_service_access_v2(
            p_acquisition_principal_id, NULL, NULL
        );
    EXCEPTION WHEN OTHERS THEN
        IF SQLERRM NOT IN (
            'MLC3_ROLLOUT_NOT_ACTIVE',
            'MLC3_CURRENT_ENROLLMENT_REQUIRED',
            'MLC3_COHORT_MEMBERSHIP_REQUIRED',
            'MLC3_ENROLLMENT_AUTHORITY_STALE',
            'MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED',
            'MLC3_ROLLOUT_POLICY_AUTHORITY_MISMATCH'
        ) THEN
            RAISE;
        END IF;
    END;
    RETURN contract;
END;
$$;

-- As 0339: reached only through the SECURITY DEFINER source read.
REVOKE ALL ON FUNCTION public.require_mlc3_service_principal_v1(UUID)
    FROM PUBLIC, anon, authenticated, service_role;

COMMIT;
