-- 0339 - F1 feedback serving stops requiring an F2 coach permission.
--
-- FOUNDER DECISION 2026-09-18, option B. The locked goal is explicit:
--
--     "The record -> process -> Ideal Text -> next-Take loop never waits for
--      a coach or exercise."
--
-- It was waiting. Every V3 SQL path ran through
-- `require_mlc3_service_access_v2`, which requires the D4 general-user
-- rollout to be active, this principal to hold a current enrollment, and a
-- processing receipt carrying BOTH `personalized_exercise_recommendation`
-- AND `coach_review`. In production `mlc3_service_rollout_revisions` holds one
-- revision in state `disabled`, and `coach_review` is registered
-- `operational=false, authorizes_processing=false`. So the gate could not
-- pass, `read_feedback_v3_candidate_source_snapshot_v1` raised, and every
-- Take stood down to V2 -- which is what "1 bookmark on a 5-slide take" was.
--
-- It could not be opened by configuration either: activating the rollout
-- calls `register_mlc3_general_rollout_v2`, which refuses a policy whose
-- purposes are not operational. Turning `coach_review` operational would have
-- granted every V3 speaker a coach-review authorization to read back their
-- own document.
--
-- WHAT CHANGES. `require_mlc3_service_principal_v1` is restored to the
-- authority it carried before D4 retrofitted the rollout onto it: an active
-- `mlc3-first-client-service-v1` contract with both buckets configured, this
-- principal on the active service allowlist, and no pending purge request.
-- D4's rollout resolution is kept as an ADVISORY step so lineage stamping is
-- unchanged wherever the general-user rollout is actually running.
--
-- THIS IS NET STRICTER ON TWO CHECKS. D4's body had dropped the allowlist and
-- the purge check, relying on enrollment to imply them. Both come back here,
-- so a revoked principal and a principal mid-erasure are now refused on paths
-- that had stopped refusing them.
--
-- WHAT DOES NOT CHANGE. `require_mlc3_service_access_v2` itself is untouched,
-- so the confident-moment coaching bundle and every F2 path keep the full
-- rollout + enrollment + dual-purpose gate. No Phase-2 corpus, dataset,
-- training, evaluation, promotion or exercise-adequacy path is opened. No
-- purpose registry row is modified. Nothing changes about what data is
-- processed or where it goes -- only which permission is required to read
-- back your own Ideal Text.
--
-- Changes no rows. Idempotent: replacing a function with the same definition
-- twice is a no-op.

BEGIN;

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
    IF NOT EXISTS (
        SELECT 1 FROM public.mlc3_service_principal_allowlist allowed
         WHERE allowed.acquisition_principal_id = p_acquisition_principal_id
           AND allowed.contract_version = contract.contract_version
           AND allowed.state = 'active'
           AND allowed.revoked_at IS NULL
    ) OR EXISTS (
        SELECT 1 FROM public.data_purge_requests purge
         WHERE purge.acquisition_principal_id = p_acquisition_principal_id
           AND purge.state <> 'done'
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

CREATE OR REPLACE FUNCTION public.read_feedback_v3_candidate_source_snapshot_v1(
 p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path=public AS $$
DECLARE s public.ideal_text_document_snapshots; surface text;
BEGIN
 PERFORM public.lock_confident_moment_inventory_v1(p_acquisition_principal_id,p_project_id,p_take_id);
 -- F1 READS DO NOT WAIT FOR AN F2 PERMISSION (founder 2026-09-18).
 -- Was require_mlc3_service_access_v2, which demands the general-user
 -- rollout AND a dual-purpose receipt carrying `coach_review`. This is a
 -- speaker reading the Ideal Text of their own Take; the contract, the
 -- allowlist and the absence of a purge request are what that needs.
 PERFORM public.require_mlc3_service_principal_v1(p_acquisition_principal_id);
 SELECT snapshot.* INTO STRICT s
 FROM public.ideal_text_document_heads head
 JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
 WHERE snapshot.acquisition_principal_id=p_acquisition_principal_id
   AND snapshot.project_id=p_project_id AND snapshot.source_take_session_id=p_take_id
 FOR SHARE OF snapshot;
 surface:=COALESCE(s.payload->>'ideal_text',s.payload->>'text');
 IF surface IS NULL OR public.exercise_json_sha256_v1(s.payload)<>s.payload_sha256 THEN
  RAISE EXCEPTION 'FEEDBACK_V3_SOURCE_SNAPSHOT_INVALID';
 END IF;
 RETURN jsonb_build_object('snapshot_contract_version','feedback-v3-candidate-source-snapshot-v1',
  'document_snapshot_id',s.id,'source_generation',s.source_generation,'surface',surface,
  'surface_sha256',public.exercise_text_sha256_v1(surface));
END $$;

REVOKE ALL ON FUNCTION public.require_mlc3_service_principal_v1(UUID)
    FROM PUBLIC, anon, authenticated, service_role;
REVOKE ALL ON FUNCTION
    public.read_feedback_v3_candidate_source_snapshot_v1(uuid,uuid,uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.read_feedback_v3_candidate_source_snapshot_v1(uuid,uuid,uuid)
    TO service_role;

COMMIT;
