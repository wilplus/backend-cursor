-- 0362 · Two D11 writers take their locks again.
--
-- FOUND ON A REHEARSAL CLUSTER 2026-09-25. In production,
-- `public.mark_phase1_storage_object_purged_v1` no longer carries the
-- advisory-lock preamble 0327 wrote into it. The manifest walk added with
-- this file then found a second writer in the same state:
-- `public.accept_phase1_processing_authorization_v1`.
--
-- HOW THEY WERE LOST. 0327 (add_confident_moment_coaching_bundle_v1.sql)
-- closes every writer that can change the D11 read inventory. It reads each
-- registered function with `pg_get_functiondef`, inserts a marked preamble
-- after the body's `BEGIN`, and re-executes the result. The preamble exists
-- only in the database, never in any file's source text. So a later
-- migration that re-issues one of those functions from source removes it
-- without a word. Two did:
--
--   * 0335 (enable_practice_phase1_purpose.sql) re-issued
--     accept_phase1_processing_authorization_v1 to ask the purpose registry
--     instead of a hardcoded phase-2 list. Lost: "D11 writer: authorization
--     receipt" (rollout policy, then service principal).
--   * 0354 (deletion_reaches_practice_objects.sql) re-issued
--     mark_phase1_storage_object_purged_v1 to add the practice branch. Lost:
--     "D11 writer: object purge". That preamble locks, in order, the rollout
--     policy, the service principal, then each of the subject's project,
--     take and feedback-v3 membership inventories, speaker attempts and
--     processing audio objects.
--
-- `finalize_phase1_purge_v3` keeps its own marker; nothing replaced it.
--
-- WHAT THAT OPENS. Neither writer queues behind the writers D11 serialises
-- against it any more: membership freezes, document snapshots, renders,
-- enrollment and rollout changes. An object mark can then interleave with a
-- membership or snapshot writer that has already read the subject's
-- inventory. The finalize step still serialises; the per-object step does
-- not.
--
-- WHY NOTHING CAUGHT IT. The rehearsal lane applied 0327 LAST, after 0354, so
-- 0327's injection landed on 0354's body and the marker tests passed on a
-- function state production never had. The lane never applied 0335 at all.
-- The lane now re-applies 0354 after 0327, as the manifest does, then this
-- file. A unit-tier test (tests/test_d11_writer_markers_survive_the_manifest.py)
-- walks the manifest and fails if any file after 0327 replaces a registered
-- writer without carrying or re-injecting its marker.
--
-- THE REPAIR IS 0327's OWN. Each registry entry below is byte-identical to
-- 0327's entry for that function (the test compares them). The loop is
-- 0327's loop: skip when the marker is present; otherwise insert after
-- `BEGIN` and re-execute the CURRENT definition, which keeps 0335's registry
-- check and 0354's practice branch. Re-issuing their text with the preamble
-- added would work once, then the next replacement would lose it again.
--
-- STRICTER ON DRIFT THAN 0327. It refuses if a function is absent, if its
-- body does not have exactly one `BEGIN` line, or if a parameter the preamble
-- reads is not one of the function's parameters. After re-executing, it reads
-- the definition again and refuses if the marker did not land.
--
-- NOT COVERED HERE: `accept_phase1_processing_authorization_v2` (0357),
-- which is what services/processing_authorization.py calls today. It was
-- never in 0327's registry, so it has no preamble to restore. Whether it
-- joins the registry is a separate decision.
--
-- ADDITIVE AND IDEMPOTENT. No table, column or row is created, altered or
-- dropped. Re-running finds both markers and changes nothing. Replacing a
-- function preserves its ACL; the REVOKE/GRANT pairs restate the
-- service_role-only grant each already has, by exact signature.
--
-- THIS OPENS NOTHING. An authorised erasure or acceptance still completes,
-- behind the same locks as every other D11 writer.

DO $d11_writer_reclosure$
DECLARE
 spec jsonb;
 target regprocedure;
 definition text;
 injection text;
 openings integer;
 missing text;
BEGIN
 FOR spec IN SELECT value FROM jsonb_array_elements($registry$
 [
  {"signature":"public.accept_phase1_processing_authorization_v1(uuid,text,text,text,text,text,text,boolean,text,text,text,timestamptz,text)","marker":"D11 writer: authorization receipt","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||p_acquisition_principal_id::text,0));\n"},
  {"signature":"public.mark_phase1_storage_object_purged_v1(uuid,text,uuid,text,text,text,text)","marker":"D11 writer: object purge","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||request.acquisition_principal_id::text,0)) FROM public.data_purge_requests request WHERE request.id=p_purge_request_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-project-inventory:'||project_row.id::text,0)) FROM public.projects project_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=project_row.owner_principal_id WHERE request.id=p_purge_request_id ORDER BY project_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('confident-moment-take-inventory:'||take_row.id::text,0)) FROM public.v2_sessions take_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=take_row.owner_principal_id WHERE request.id=p_purge_request_id ORDER BY take_row.id;\n PERFORM pg_advisory_xact_lock(hashtextextended('feedback-v3-membership-inventory:'||membership.project_id::text||':'||membership.take_id::text,0)) FROM public.feedback_v3_memberships membership JOIN public.data_purge_requests request ON request.acquisition_principal_id=membership.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY membership.project_id,membership.take_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-speaker-attempt:'||object_row.recording_attempt_id::text,0)) FROM public.processing_audio_objects object_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=object_row.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY object_row.recording_attempt_id;\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-processing-audio-object:'||object_row.id::text,0)) FROM public.processing_audio_objects object_row JOIN public.data_purge_requests request ON request.acquisition_principal_id=object_row.acquisition_principal_id WHERE request.id=p_purge_request_id ORDER BY object_row.id;\n"}
 ]$registry$::jsonb) LOOP
  target:=to_regprocedure(spec->>'signature');
  IF target IS NULL THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_REGISTRY_DRIFT: %',spec->>'signature';
  END IF;
  definition:=pg_get_functiondef(target);
  IF position(spec->>'marker' IN definition)=0 THEN
   openings:=(length(definition)-length(replace(definition,E'\nBEGIN\n','')))/length(E'\nBEGIN\n');
   IF openings<>1 THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_BODY_DRIFT: % (% BEGIN lines)',spec->>'signature',openings;
   END IF;
   SELECT string_agg(DISTINCT used.name,',') INTO missing
     FROM (SELECT (regexp_matches(spec->>'sql','\m(p_[a-z0-9_]+)','g'))[1] AS name) used
     JOIN pg_proc procedure ON procedure.oid=target
    WHERE NOT used.name=ANY(COALESCE(procedure.proargnames,ARRAY[]::text[]));
   IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_BODY_DRIFT: % (no parameter %)',spec->>'signature',missing;
   END IF;
   injection:=' -- '||(spec->>'marker')||E'\n'||(spec->>'sql');
   definition:=regexp_replace(definition,E'\nBEGIN\n',E'\nBEGIN\n'||injection);
   EXECUTE definition;
   IF position(spec->>'marker' IN pg_get_functiondef(target))=0 THEN
    RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_BODY_DRIFT: % (marker did not land)',spec->>'signature';
   END IF;
  END IF;
 END LOOP;
END
$d11_writer_reclosure$;

REVOKE ALL ON FUNCTION public.accept_phase1_processing_authorization_v1(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_phase1_processing_authorization_v1(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT
) TO service_role;
REVOKE ALL ON FUNCTION public.mark_phase1_storage_object_purged_v1(
    UUID,TEXT,UUID,TEXT,TEXT,TEXT,TEXT
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.mark_phase1_storage_object_purged_v1(
    UUID,TEXT,UUID,TEXT,TEXT,TEXT,TEXT
) TO service_role;
