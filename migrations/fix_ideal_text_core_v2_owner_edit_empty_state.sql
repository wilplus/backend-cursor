-- fix_ideal_text_core_v2_owner_edit_empty_state
--
-- The second of the two transport breaks in 0327's owner_edit block, and the
-- one 0329 deliberately left alone. Seen in production as:
--
--     ConfidentMomentProjectionInvalid: owner_edit empty state invalid
--
-- THE CONTRACT. `owner_edit` is the OWNER'S EDIT STATE, and it is all-or-
-- nothing: either the owner has typed their own text, or the block is
-- canonically empty. `validate_owner_edit_transport` in
-- services/confident_moment_bundle.py:
--
--     if owner.get("text") is None:
--         if any(owner.get(key) is not None for key in (
--             "source_document_version", "user_text_revision",
--             "user_text_sha256", "current_bundle_text_update_binding",
--         )) or parts:
--             raise ConfidentMomentProjectionInvalid("owner_edit empty state invalid")
--
-- So a null `text` requires the other four to be null AND `parts` to be [].
--
-- THIS IS A DELIBERATE CONTRACT, NOT A FUSSY VALIDATOR, and the SQL is the only
-- one of three implementations that disobeys it. The frontend enforces the same
-- rule independently in mapConfidentMomentOwnerEdit (`value.parts.length !== 0`
-- -> reject), and its own test names the shape:
--
--     it("preserves the canonical valid-empty owner edit state", ...)
--       owner_edit: { text: null, source_document_version: null,
--                     user_text_revision: null, user_text_sha256: null,
--                     parts: [], current_bundle_text_update_binding: null }
--
-- `owner_edit.parts` means "the paragraphs the owner has edited", which is a
-- different thing from the document's own paragraph inventory. That is why the
-- empty state carries none: with no owner edit there are no owner-edited parts.
--
-- WHAT WAS WRONG, EXACTLY ONE FIELD. The function always emitted the live
-- `parts` aggregate regardless of whether an owner edit existed, so every arc
-- whose owner had not typed their own text failed validation and fell back to
-- the v1 read.
--
-- `source_document_version` and `user_text_revision` LOOK like they could break
-- the same rule, because they were keyed on their own nullness rather than on
-- `user_text`. They cannot, and this was checked rather than assumed: the table
-- carries a CHECK that makes the offending row unrepresentable, and an attempt
-- to write one is rejected --
--
--   user_arc_ideal_notes_owner_lane_shape CHECK (
--     (user_text IS NULL AND user_text_version IS NULL AND user_text_revision IS NULL)
--     OR (user_text IS NOT NULL AND length(user_text) > 0
--         AND user_text_version > 0 AND user_text_revision > 0))
--
-- so those two fields are already null whenever `user_text` is. The branch
-- below is therefore defence in depth for them, not a second bug fix: it makes
-- this function state its own contract instead of inheriting it from a
-- constraint on another table, so the read stays correct if that constraint is
-- ever relaxed.
--
-- NOT A RENDERING REGRESSION. The document's paragraphs do not reach the client
-- through this field: in the frontend's core payload `parts` is null in every
-- fixture, and the paragraph list is served by /recording-roots. An empty
-- `owner_edit.parts` and today's rejected block therefore render identically --
-- the difference is that this one validates, so the v2 read finally serves.
--
-- Everything else is 0329's definition, unchanged. 0327/0328/0329 are applied,
-- checksum-pinned and in the ledger, so none of them is edited. Idempotent +
-- additive: CREATE OR REPLACE of one function, safe to re-run. No table, column
-- or data change.

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
