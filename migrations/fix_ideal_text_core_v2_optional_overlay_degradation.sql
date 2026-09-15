-- fix_ideal_text_core_v2_optional_overlay_degradation
--
-- LIVE LOOP incident, 2026-09-15. Every GET /v2/explore/arc/<id>/ideal-text/core
-- returned 500 in production from ~06:55 UTC, so Ideal Text — the canonical
-- presentation document, the load-bearing F1 read — could not load at all.
--
-- ROOT CAUSE. public.read_ideal_text_document_core_v2 (0327) fetches the
-- Confident Moment summary, an OPTIONAL F2 overlay, and the author correctly
-- wrote a degradation path for it. The degradation was keyed on a substring of
-- the error TEXT:
--
--     WHEN OTHERS THEN
--       IF SQLERRM LIKE '%DISABLED%' THEN ... ELSE RAISE; END IF;
--
-- That literal matches exactly two strings in the whole migration set —
-- COACH_GUIDANCE_D3_RUNTIME_DISABLED and EXERCISE_SERVICE_EXPOSURE_DISABLED —
-- both of which are deliberate kill switches. It handles "somebody turned the
-- overlay off" and does not handle "the overlay was never turned on", which is
-- the shipped default. The executed path:
--
--     read_ideal_text_document_core_v2            0327
--       -> project_confident_moment_bundles_v1    0327
--            -> require_mlc3_service_access_v2    0326
--                 -> RAISE EXCEPTION 'MLC3_ROLLOUT_NOT_ACTIVE'   (P0001)
--
-- 'MLC3_ROLLOUT_NOT_ACTIVE' does not contain 'DISABLED', so it fell through to
-- ELSE RAISE and an optional overlay took down the F1 read. The same ELSE RAISE
-- also fires on CONFIDENT_MOMENT_MEMBERSHIP_INVALID, which is raised for any
-- take with no Confident Moment bundle — i.e. every project predating MLC-3.
-- Activating the rollout would therefore NOT have fixed this; it moves the
-- failure from one unmatched string to another.
--
-- Enumerating which overlay failures are survivable is the defect. This
-- migration inverts the rule: the overlay is optional, so ANY overlay failure
-- degrades to a status state and the document is still returned. That is what
-- CLAUDE.md requires of F1 — it must be bulletproof WITHOUT the learning layer.
--
-- SECOND DEFECT, same function. Three SELECT ... INTO STRICT statements sit
-- outside that guard, so no_data_found (P0002) propagated as a 500:
--
--     projects                 -- arc that is not a project
--     ideal_text_document_heads (x2)  -- arc with no document published YET
--
-- The last two are the normal state of every project before its first snapshot.
-- The route already has the right answer for "no document" — it returns 404
-- IDEAL_TEXT_DOCUMENT_PENDING when the read returns nothing — so these now
-- RETURN NULL instead of raising. STRICT's other guarantee (TOO_MANY_ROWS) is
-- not lost: projects.id is the primary key, and ideal_text_document_heads is
-- PRIMARY KEY (arc_id, actor_id), so neither lookup can return a second row.
--
-- WHAT IS DELIBERATELY NOT CHANGED
--   * The wire contract. state stays in {available, unavailable, disabled},
--     code stays NULL and retryable stays false, so no client changes and no
--     new user-facing string. The diagnostic goes to the server log via
--     RAISE LOG, which is never sent to the client.
--   * Every ownership and projection check. CONFIDENT_MOMENT_PROJECTION_INVALID
--     still raises — an identity mismatch is a real integrity failure, not a
--     missing optional overlay, and it must stay loud.
--   * The serializer envelope. lock_confident_moment_inventory_v1 is still
--     called at the same point, outside the overlay's exception block.
--   * The snapshot shape and read_sha256, byte for byte.
--
-- Relation to the application-side change in #507: that made the Python wrapper
-- fall back to the v1 read instead of re-raising, which stopped the 500s. It is
-- a fallback, not a fix — with the RPC still raising, EVERY core read in
-- production silently serves the pre-Point-7 document. This migration is what
-- lets the v2 read serve again; #507 remains the safety net beneath it.
--
-- 0327 is applied, checksum-pinned and in the ledger, so it is not edited here.
-- Idempotent + additive, per the standing constraint: CREATE OR REPLACE of one
-- function, safe to re-run. No table, column or data change.

CREATE OR REPLACE FUNCTION public.read_ideal_text_document_core_v2(p_arc_id text,p_actor_id text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE s public.ideal_text_document_snapshots; owner_note public.user_arc_ideal_notes;
 parts jsonb; owner_edit jsonb; summary jsonb; status jsonb; snapshot_json jsonb; overlay jsonb; result jsonb;
 derived_principal uuid; derived_project uuid; derived_take uuid;
BEGIN
 -- CHANGED (was INTO STRICT): an arc that is not a project has no document.
 SELECT id,owner_principal_id INTO derived_project,derived_principal FROM public.projects WHERE id::text=p_arc_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.owner_principals p WHERE p.id=derived_principal
   AND (p.user_id::text=p_actor_id OR p.id::text=p_actor_id)) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 -- CHANGED (was INTO STRICT): no document published for this arc yet.
 SELECT snapshot.source_take_session_id INTO derived_take
 FROM public.ideal_text_document_heads head JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
 WHERE head.arc_id=p_arc_id AND head.actor_id=p_actor_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM public.lock_confident_moment_inventory_v1(derived_principal,derived_project,derived_take);
 -- CHANGED (was INTO STRICT): same head, re-read under FOR SHARE.
 SELECT snapshot.* INTO s FROM public.ideal_text_document_heads head
 JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
 WHERE head.arc_id=p_arc_id AND head.actor_id=p_actor_id AND snapshot.arc_id=p_arc_id AND snapshot.actor_id=p_actor_id FOR SHARE OF head,snapshot;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF s.arc_id='' OR s.actor_id='' OR s.acquisition_principal_id<>derived_principal
    OR s.project_id<>derived_project OR s.source_take_session_id<>derived_take THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 SELECT * INTO owner_note FROM public.user_arc_ideal_notes n WHERE n.arc_id=p_arc_id AND n.user_id=(SELECT user_id FROM public.owner_principals WHERE id=s.acquisition_principal_id) FOR SHARE;
 SELECT COALESCE(jsonb_agg(jsonb_build_object('id',p.id,'ord',p.ord,'text',p.text,
   'locked',COALESCE(l.locked,false),'current_part_revision_id',l.current_part_revision_id) ORDER BY p.ord,p.id),'[]'::jsonb)
 INTO parts FROM public.ideal_text_part p LEFT JOIN LATERAL(
   SELECT r.id current_part_revision_id,(r.action='lock') locked FROM public.ideal_text_part_revision r
   WHERE r.arc_id=p.arc_id AND r.user_id=p.user_id AND r.part_id=p.id ORDER BY r.id DESC LIMIT 1) l ON true
 WHERE p.arc_id=p_arc_id AND p.user_id=p_actor_id;
 owner_edit:=jsonb_build_object('text',owner_note.user_text,'source_document_version',owner_note.user_text_version,
  'user_text_revision',CASE WHEN owner_note.user_text_revision IS NULL THEN NULL ELSE owner_note.user_text_revision::text END,
  'user_text_sha256',CASE WHEN owner_note.user_text IS NULL THEN NULL ELSE public.exercise_text_sha256_v1(owner_note.user_text) END,
  'parts',parts,'current_bundle_text_update_binding',NULL);
 BEGIN
  summary:=public.project_confident_moment_bundles_v1(s.acquisition_principal_id,s.project_id,s.source_take_session_id)->'summary';
  status:=jsonb_build_object('state','available','code',NULL,'retryable',false);
 EXCEPTION WHEN no_data_found THEN
  summary:=NULL; status:=jsonb_build_object('state','unavailable','code',NULL,'retryable',false);
 WHEN OTHERS THEN
  -- CHANGED: the overlay is OPTIONAL, so every failure degrades and the
  -- document is still returned. The old ELSE RAISE here is what took the F1
  -- read down on 2026-09-15. 'disabled' is kept for the two explicit kill
  -- switches so their state is still distinguishable; everything else —
  -- MLC3_ROLLOUT_NOT_ACTIVE, CONFIDENT_MOMENT_MEMBERSHIP_INVALID, a timeout,
  -- anything future — reports 'unavailable'. Server log only: RAISE LOG is
  -- never sent to the client, so the wire contract is unchanged, and once this
  -- RPC stops raising it is the only trace that the overlay degraded.
  IF SQLERRM LIKE '%DISABLED%' THEN summary:=NULL; status:=jsonb_build_object('state','disabled','code',NULL,'retryable',false);
  ELSE
   RAISE LOG 'read_ideal_text_document_core_v2 overlay unavailable arc=% sqlstate=% message=%',p_arc_id,SQLSTATE,SQLERRM;
   summary:=NULL; status:=jsonb_build_object('state','unavailable','code',NULL,'retryable',false);
  END IF;
 END;
 snapshot_json:=jsonb_build_object('id',s.id::text,'arc_id',s.arc_id,'actor_id',s.actor_id,
  'acquisition_principal_id',s.acquisition_principal_id::text,'project_id',s.project_id::text,
  'source_take_session_id',s.source_take_session_id::text,'version',s.version,'source_generation',s.source_generation::text,
  'source_fingerprint_sha256',s.source_fingerprint_sha256,'payload_sha256',s.payload_sha256,'payload',s.payload,
  'enrichment_seed',s.enrichment_seed,'supersedes_id',CASE WHEN s.supersedes_id IS NULL THEN NULL ELSE s.supersedes_id::text END,
  'created_at',to_char(s.created_at AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US"Z"'));
 overlay:=jsonb_build_object('owner_edit',owner_edit,'confident_moment_summary',summary,'confident_moment_summary_status',status);
 result:=jsonb_build_object('ideal_text_core_read_contract_version','ideal-text-document-core-v2','snapshot',snapshot_json,'dynamic_overlay',overlay);
 RETURN result||jsonb_build_object('read_sha256',public.exercise_json_sha256_v1(result));
END $$;

-- CREATE OR REPLACE preserves the ACL 0327 set, so these re-state the existing
-- grant rather than change it. Kept explicit so the file is self-describing and
-- so the standing "functions get their EXECUTE revoked" rule reads true here.
REVOKE ALL ON FUNCTION public.read_ideal_text_document_core_v2(text,text)
 FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.read_ideal_text_document_core_v2(text,text) TO service_role;

NOTIFY pgrst,'reload schema';
