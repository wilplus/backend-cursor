-- fix_ideal_text_core_v2_part_revision_id_transport
--
-- One missing cast, found in production the moment 0328 let the v2 read get far
-- enough to be validated:
--
--     ConfidentMomentProjectionInvalid:
--       current_part_revision_id must be a canonical positive bigint string
--
-- `services/confident_moment_bundle.py` validates the D29 envelope. For every
-- owner_edit part it requires current_part_revision_id to be a canonical
-- positive bigint STRING (`_bigint_string`, `_BIGINT_RE = ^[1-9][0-9]*$`) or
-- null. `ideal_text_part_revision.id` is BIGSERIAL, so `jsonb_build_object`
-- emits it as a JSON NUMBER and the validator rejects the whole document.
--
-- The rule is not arbitrary and is not the validator being fussy: a bigint past
-- 2^53 loses precision as a JSON number in any JavaScript client, so every
-- 64-bit id crosses this boundary as a string. The author knew — the sibling
-- field three lines below in the SAME statement is cast:
--
--     'user_text_revision', CASE WHEN owner_note.user_text_revision IS NULL
--                                THEN NULL ELSE owner_note.user_text_revision::text END
--
-- current_part_revision_id simply did not get the same treatment. `::text` is
-- enough on its own here — NULL::text is NULL, which the validator accepts for
-- this field (`nullable=True`) — so no CASE is needed.
--
-- WHY THIS WAS INVISIBLE UNTIL NOW. Before 0328 the RPC raised
-- MLC3_ROLLOUT_NOT_ACTIVE and `db.get_ideal_text_document_core_v2` never
-- reached `validate_ideal_text_core_v2` at all, so this defect could not be
-- observed. Fixing the raise did not cause it; it revealed it. #507's v1
-- fallback then caught the validator error too, which is why the surface stayed
-- up while the v2 read still did not serve.
--
-- This is the second of two independent contract breaks in 0327's owner_edit
-- block. The other — the validator requiring owner_edit to be COMPLETELY empty
-- (parts included) whenever owner text is null, while this function always
-- fills parts — is a genuine disagreement about the contract rather than a
-- missed cast, and is deliberately NOT changed here.
--
-- Everything else is 0328's definition, unchanged: the optional overlay still
-- degrades on any failure, the three lookups still return no-document rather
-- than raise, CONFIDENT_MOMENT_PROJECTION_INVALID still raises, and the wire
-- contract is otherwise untouched.
--
-- 0327 and 0328 are applied, checksum-pinned and in the ledger, so neither is
-- edited. Idempotent + additive: CREATE OR REPLACE of one function, safe to
-- re-run. No table, column or data change.

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
 -- CHANGED: ::text on current_part_revision_id. It is BIGSERIAL, so without the
 -- cast jsonb_build_object emits a JSON number and the D29 validator rejects the
 -- whole document. NULL::text stays NULL, which this field allows.
 SELECT COALESCE(jsonb_agg(jsonb_build_object('id',p.id,'ord',p.ord,'text',p.text,
   'locked',COALESCE(l.locked,false),'current_part_revision_id',l.current_part_revision_id::text) ORDER BY p.ord,p.id),'[]'::jsonb)
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
