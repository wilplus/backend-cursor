-- The v2 core read asked the projection for a key it never returns, so its
-- "available" branch has never once produced a valid envelope.
--
-- PRODUCTION, 2026-09-21, on every open of every V3 Take since MLC-3 reached
-- general availability on 2026-09-20:
--
--     ideal-text core v2 read failed arc=c41fca24-...:
--       ConfidentMomentProjectionInvalid: available summary state invalid
--     f1.degrade reason=ideal_text_core_v2_read_failed
--     ideal-text core served by the v1 fallback
--
-- THE ONE TOKEN. `read_ideal_text_document_core_v2` (0327, carried verbatim
-- through 0328, 0329 and 0330) reads
--
--     project_confident_moment_bundles_v1(...)->'summary'
--
-- but the projection (0327) returns
--
--     jsonb_build_object('bundle_projection',body,'confident_moment_summary',summary)
--
-- so `->'summary'` is SQL NULL every time the projection succeeds, and the
-- read then labels that NULL `state='available'`. The Python validator
-- (`services/confident_moment_bundle.py`, `validate_ideal_text_core_v2`)
-- refuses "available with no summary" -- correctly, that combination is
-- impossible under the contract -- and the whole v2 envelope is thrown away
-- for the v1 fallback, which serves `owner_edit: NULL`. The speaker's own
-- Ideal Text edit state drops off the cold open.
--
-- WHY ONLY NOW. The projection's gates (`require_mlc3_service_access_v2`,
-- exactly one V3 membership on the head snapshot) raised for everyone while
-- the rollout was `disabled`, and a raise lands in the handler below as a
-- valid `'unavailable'`. GA on 2026-09-20 opened the gates, the projection
-- started succeeding, and the wrong key finally surfaced.
--
-- THE FIX is 0330's definition with that token corrected, plus one guard
-- that keeps the SQL consistent with the validator: a NULL summary is
-- reported as `'unavailable'` (with `owner_edit` intact) rather than as an
-- `'available'` the reader cannot accept. 0327-0330 are applied,
-- checksum-pinned and in the ledger, so none of them is edited. Idempotent
-- + additive: CREATE OR REPLACE of one function, safe to re-run. No table,
-- column or data change.

CREATE OR REPLACE FUNCTION public.read_ideal_text_document_core_v2(p_arc_id text,p_actor_id text)
RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER VOLATILE SET search_path=public AS $$
DECLARE s public.ideal_text_document_snapshots; owner_note public.user_arc_ideal_notes;
 parts jsonb; owner_edit jsonb; summary jsonb; status jsonb; snapshot_json jsonb; overlay jsonb; result jsonb;
 derived_principal uuid; derived_project uuid; derived_take uuid;
BEGIN
 -- 0328 (was INTO STRICT): an arc that is not a project has no document.
 SELECT id,owner_principal_id INTO derived_project,derived_principal FROM public.projects WHERE id::text=p_arc_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF NOT EXISTS(SELECT 1 FROM public.owner_principals p WHERE p.id=derived_principal
   AND (p.user_id::text=p_actor_id OR p.id::text=p_actor_id)) THEN RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 -- 0328 (was INTO STRICT): no document published for this arc yet.
 SELECT snapshot.source_take_session_id INTO derived_take
 FROM public.ideal_text_document_heads head JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
 WHERE head.arc_id=p_arc_id AND head.actor_id=p_actor_id;
 IF NOT FOUND THEN RETURN NULL; END IF;
 PERFORM public.lock_confident_moment_inventory_v1(derived_principal,derived_project,derived_take);
 -- 0328 (was INTO STRICT): same head, re-read under FOR SHARE.
 SELECT snapshot.* INTO s FROM public.ideal_text_document_heads head
 JOIN public.ideal_text_document_snapshots snapshot ON snapshot.id=head.snapshot_id
 WHERE head.arc_id=p_arc_id AND head.actor_id=p_actor_id AND snapshot.arc_id=p_arc_id AND snapshot.actor_id=p_actor_id FOR SHARE OF head,snapshot;
 IF NOT FOUND THEN RETURN NULL; END IF;
 IF s.arc_id='' OR s.actor_id='' OR s.acquisition_principal_id<>derived_principal
    OR s.project_id<>derived_project OR s.source_take_session_id<>derived_take THEN
  RAISE EXCEPTION 'CONFIDENT_MOMENT_PROJECTION_INVALID'; END IF;
 SELECT * INTO owner_note FROM public.user_arc_ideal_notes n WHERE n.arc_id=p_arc_id AND n.user_id=(SELECT user_id FROM public.owner_principals WHERE id=s.acquisition_principal_id) FOR SHARE;
 -- 0329: ::text on current_part_revision_id. It is BIGSERIAL, so without the
 -- cast jsonb_build_object emits a JSON number and the D29 validator rejects the
 -- whole document. NULL::text stays NULL, which this field allows.
 SELECT COALESCE(jsonb_agg(jsonb_build_object('id',p.id,'ord',p.ord,'text',p.text,
   'locked',COALESCE(l.locked,false),'current_part_revision_id',l.current_part_revision_id::text) ORDER BY p.ord,p.id),'[]'::jsonb)
 INTO parts FROM public.ideal_text_part p LEFT JOIN LATERAL(
   SELECT r.id current_part_revision_id,(r.action='lock') locked FROM public.ideal_text_part_revision r
   WHERE r.arc_id=p.arc_id AND r.user_id=p.user_id AND r.part_id=p.id ORDER BY r.id DESC LIMIT 1) l ON true
 WHERE p.arc_id=p_arc_id AND p.user_id=p_actor_id;
 -- CHANGED: owner_edit is all-or-nothing. With no owner text there is no owner
 -- edit state at all, so every field is null and parts is []. One condition
 -- decides all six, which is what the validator and the client both require.
 IF owner_note.user_text IS NULL THEN
  owner_edit:=jsonb_build_object('text',NULL,'source_document_version',NULL,
   'user_text_revision',NULL,'user_text_sha256',NULL,
   'parts','[]'::jsonb,'current_bundle_text_update_binding',NULL);
 ELSE
  owner_edit:=jsonb_build_object('text',owner_note.user_text,'source_document_version',owner_note.user_text_version,
   'user_text_revision',CASE WHEN owner_note.user_text_revision IS NULL THEN NULL ELSE owner_note.user_text_revision::text END,
   'user_text_sha256',public.exercise_text_sha256_v1(owner_note.user_text),
   'parts',parts,'current_bundle_text_update_binding',NULL);
 END IF;
 BEGIN
  summary:=public.project_confident_moment_bundles_v1(s.acquisition_principal_id,s.project_id,s.source_take_session_id)->'confident_moment_summary';
  IF summary IS NULL THEN
   RAISE LOG 'read_ideal_text_document_core_v2 overlay returned no summary arc=%',p_arc_id;
   status:=jsonb_build_object('state','unavailable','code',NULL,'retryable',false);
  ELSE
   status:=jsonb_build_object('state','available','code',NULL,'retryable',false);
  END IF;
 EXCEPTION WHEN no_data_found THEN
  summary:=NULL; status:=jsonb_build_object('state','unavailable','code',NULL,'retryable',false);
 WHEN OTHERS THEN
  -- 0328: the overlay is OPTIONAL, so every failure degrades and the document
  -- is still returned. 'disabled' is kept for the two explicit kill switches;
  -- everything else reports 'unavailable'. Server log only -- RAISE LOG is
  -- never sent to the client, so the wire contract is unchanged.
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

-- CREATE OR REPLACE preserves the ACL, so these re-state the existing grant
-- rather than change it. Kept explicit so the file is self-describing.
REVOKE ALL ON FUNCTION public.read_ideal_text_document_core_v2(text,text)
 FROM PUBLIC,anon,authenticated,service_role;
GRANT EXECUTE ON FUNCTION public.read_ideal_text_document_core_v2(text,text) TO service_role;

NOTIFY pgrst,'reload schema';
