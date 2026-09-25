-- 0365 · The optional yes takes the D11 locks.
--
-- THE GAP. 0327 (add_confident_moment_coaching_bundle_v1.sql) closes every
-- writer that can change the D11 read inventory. One of them is
-- `accept_phase1_processing_authorization_v1`, "D11 writer: authorization
-- receipt": it locks the rollout policy, then the principal's service lock.
-- 0357 (a_receipt_can_record_an_optional_yes.sql) added
-- `accept_phase1_processing_authorization_v2` next to v1, and
-- services/processing_authorization.accept() now calls v2. v2 was never in
-- 0327's registry, and 0327's verifier counts overloads by name, so a new name
-- was never checked. The acceptance path in use takes no D11 lock at all.
-- 0364 put v1's lost preamble back and left v2 alone; this file covers v2.
--
-- WHY v2 MUST SERIALISE. It writes the rows D11 reads, the same rows v1 writes:
--
--   * `processing_authorization_receipts`. The D11 readers pick the principal's
--     newest current receipt (resolve_mlc3_dual_purpose_receipt_v2,
--     require_feedback_language_delivery_scan_authority_v1), and an
--     enrollment revision stores which receipt it was bound to.
--   * `processing_authorization_receipt_purposes`. Those readers require the
--     receipt to name both `personalized_exercise_recommendation` and
--     `coach_review`. Under the unbundled policy those two are optional, and
--     v2 is the ONLY writer that can record them. v2 is therefore what turns
--     that authority on for a principal.
--
-- Without the locks, an acceptance can commit between an enrollment's or a
-- delivery scan's read of the receipt and that writer's own commit. The
-- writer then binds to a receipt that is no longer the principal's newest.
-- Every other writer of this inventory queues on the same two locks; v2
-- should too.
--
-- THE REPAIR IS 0327's OWN, AS IN 0364. The lock SQL and marker are v1's
-- entry, byte for byte; only the signature differs
-- (tests/test_d11_writer_markers_survive_the_manifest.py compares them). The
-- loop is 0364's: skip when the marker is present; otherwise insert after
-- `BEGIN` and re-execute the CURRENT definition, so 0357's body is kept. It
-- refuses if the function is absent, if its body does not have exactly one
-- `BEGIN` line, if the preamble reads a parameter the function lacks, or if
-- the marker did not land.
--
-- 0327's verifier is not edited. It runs once, inside 0327, and editing an
-- applied migration changes nothing in production. From here on the manifest
-- walk (tests/test_d11_writer_markers_survive_the_manifest.py) treats v2 as a
-- registered writer: a later file that re-issues v2 from source without the
-- marker fails the build and names itself.
--
-- LOCK ORDER. Rollout policy, then the service principal: the order every
-- D11 writer uses, so this adds no new edge a deadlock could form on. The
-- rollout lock is global, so acceptances queue behind one another and behind
-- rollout changes. That is the cost v1 has carried since 0327. An acceptance
-- is one short transaction per person, off the record→process→Ideal Text loop.
--
-- ADDITIVE AND IDEMPOTENT. No table, column or row is created, altered or
-- dropped. Re-running finds the marker and changes nothing. Replacing a
-- function preserves its ACL; the REVOKE/GRANT pair restates the
-- service_role-only grant 0357 gave it, by exact signature.
--
-- THIS OPENS NOTHING. Every acceptance v2 accepts today it still accepts, with
-- the same receipt, the same evidence hash and the same result. It only waits
-- behind the same locks as every other D11 writer.

DO $d11_writer_closure_v2_receipt$
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
  {"signature":"public.accept_phase1_processing_authorization_v2(uuid,text,text,text,text,text,text,boolean,text,text,text,timestamptz,text,text[])","marker":"D11 writer: authorization receipt","sql":" PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-rollout-policy-v2',0));\n PERFORM pg_advisory_xact_lock(hashtextextended('mlc3-service-principal:'||p_acquisition_principal_id::text,0));\n"}
 ]$registry$::jsonb) LOOP
  target:=to_regprocedure(spec->>'signature');
  IF target IS NULL THEN
   RAISE EXCEPTION 'CONFIDENT_MOMENT_WRITER_REGISTRY_DRIFT: %',spec->>'signature';
  END IF;
  definition:=pg_get_functiondef(target);
  IF position(spec->>'marker' IN definition)=0 THEN
   -- Whole lines, newline-sensitive, as 0364 counts them: counting
   -- E'\nBEGIN\n' substrings would read two adjacent BEGIN lines as one.
   SELECT count(*) INTO openings FROM regexp_matches(definition,'^BEGIN$','gn');
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
$d11_writer_closure_v2_receipt$;

REVOKE ALL ON FUNCTION public.accept_phase1_processing_authorization_v2(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,
    TEXT[]
) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.accept_phase1_processing_authorization_v2(
    UUID,TEXT,TEXT,TEXT,TEXT,TEXT,TEXT,BOOLEAN,TEXT,TEXT,TEXT,TIMESTAMPTZ,TEXT,
    TEXT[]
) TO service_role;
