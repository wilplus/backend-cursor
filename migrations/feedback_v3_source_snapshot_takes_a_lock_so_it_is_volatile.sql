-- V3'S SOURCE READ HAS NEVER RUN (found in production 2026-09-19).
--
-- `read_feedback_v3_candidate_source_snapshot_v1` was declared STABLE and its
-- body takes a row lock:
--
--     SELECT snapshot.* INTO STRICT s ... FOR SHARE OF snapshot;
--
-- PostgreSQL rejects that at runtime, every time:
--
--     ERROR 0A000: SELECT FOR SHARE is not allowed in a non-volatile function
--
-- So the function could never return. Every Take fell through
-- `_decline(take_id, "source_snapshot_rpc_failed", ...)` and V3 stood down,
-- which is why activating V3 changed nothing a user could see: no Confident
-- Voice items, `moments: []` frozen into the published enrichment seed, and
-- therefore no bookmarks at all -- no green, no pulsing orange, nothing.
--
-- IT WAS MASKED. `require_mlc3_service_principal_v1` runs one line earlier and
-- raised MLC3_SERVICE_PRINCIPAL_NOT_ALLOWED for a principal that was not on
-- the allowlist, so the FOR SHARE was never reached. Allowlisting the founder
-- principal moved the failure from line 10 to line 11 and uncovered this. Two
-- independent blockers, stacked, both silent behind one typed decline reason.
--
-- The declaration was wrong, not the body. The function takes advisory locks
-- through `require_mlc3_service_principal_v1` and a row share lock of its own;
-- acquiring locks is a side effect, and STABLE is a promise there are none.
-- VOLATILE is what this function has always actually been. Nothing else about
-- it changes: same body, same arguments, same return, same authority checks.
--
-- CREATE OR REPLACE RESETS `SET search_path`, so it is restated here (the same
-- trap 0338 documents). The REVOKE/GRANT pair is restated for the same reason
-- of being explicit; CREATE OR REPLACE preserves privileges, and re-asserting
-- them costs nothing and cannot leave the function reachable by a role that
-- should not have it.

BEGIN;

CREATE OR REPLACE FUNCTION public.read_feedback_v3_candidate_source_snapshot_v1(
 p_acquisition_principal_id uuid,p_project_id uuid,p_take_id uuid)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
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

REVOKE ALL ON FUNCTION
    public.read_feedback_v3_candidate_source_snapshot_v1(uuid,uuid,uuid)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.read_feedback_v3_candidate_source_snapshot_v1(uuid,uuid,uuid)
    TO service_role;

COMMIT;
