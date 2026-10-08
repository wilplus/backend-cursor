-- A speaker's skip keeps an empty receipt (founder decision N12, 2026-09-26;
-- decision tree 2026-10-08, Q3 YES and Q4 YES: "empty receipt", not delete).
--
-- THE PROBLEM. tombstone_phase1_purge_lineage_v1 (0379) erases
-- feedback_revisions.revision_payload as a child of evidence_spans, through
-- the governed branch it added to reject_canonical_feedback_mutation(). But
-- since 0327 that is no longer the table's guard: feedback_revisions_append_only
-- runs reject_confident_moment_mutation_v1(), which raises on every UPDATE.
-- So the wipe raised and rolled back whenever a feedback_revisions row with a
-- payload hung off an evidence span the purge was erasing - in practice, a
-- speaker's "no helper words" skip (record_root_phrase_skip_v1: rater_role
-- 'owner', rater_id the speaker's USER id). The account or project erasure
-- could not finish (rehearsed on the released lane 2026-10-08). Of the
-- fifteen tables in the wipe plan, this is the only one whose guard lacked
-- the branch.
--
-- THE FIX, WITHOUT OPENING THE TABLE.
--   1. feedback_revisions gets its own guard, reject_feedback_revision_mutation_v1.
--      It refuses exactly what 0327's refused, with the same error
--      (CONFIDENT_MOMENT_APPEND_ONLY), but for one governed UPDATE, 0379's
--      conditions to the letter:
--        * willab.purge_wipe_request_id is set (only
--          tombstone_phase1_purge_lineage_v1 sets it, for its own transaction);
--        * that purge request is `in_progress` with a sealed inventory;
--        * only revision_payload changes, and only to '{}';
--      plus one more: the row is an OWNER row. A coach's revision keeps its
--      words in `value`, its payload only names the output kind, and its
--      digest covers both; erasing the payload would erase nothing the coach
--      said and break the row's own record. Coach rows stop the inventory
--      before anything is erased (feedback_revision_subjects / _reviewers are
--      external_review), so the wipe never reaches one; if it ever did, the
--      UPDATE raises and the whole wipe rolls back - fail closed.
--      reject_confident_moment_mutation_v1 itself is NOT changed: the other
--      0327 tables that share it keep it exactly.
--   2. The wipe counts, as `not_blank`, any owner row of the account's user
--      ids whose payload is still not erased. An owner row hangs off its
--      speaker's own Take's evidence span (record_paragraph_decision_v1 makes
--      the span with the Take's owner principal), so the wipe's scope holds it
--      and this adds zero. If one ever sat outside the scope, the purge's
--      registry entry would count it and the wipe would leave its payload:
--      this makes that a TOMBSTONE_CONTENT_REMAINS failure, never a silent
--      "retained". A project deletion's graph has no user ids, so it adds
--      nothing there: a project's rows are exactly its spans' children.
--      Patched in place from the installed body, as 0423 patches its guard.
--
-- NOTHING RUNS FROM THIS FILE. It swaps one trigger's function and edits one
-- function body; no row is read or changed. A purge still starts only when an
-- operator runs it.
--
-- ADDITIVE AND IDEMPOTENT. CREATE OR REPLACE FUNCTION; the trigger is dropped
-- and re-created in this transaction, so there is no instant without a guard;
-- the patch skips a body that already carries its marker.

BEGIN;

CREATE OR REPLACE FUNCTION public.reject_feedback_revision_mutation_v1()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    wipe_request TEXT := current_setting('willab.purge_wipe_request_id', true);
BEGIN
    -- N12: a running, frozen purge may empty an owner row's payload, and
    -- nothing else.
    IF TG_OP = 'UPDATE' AND NULLIF(wipe_request, '') IS NOT NULL
       AND OLD.rater_role = 'owner'
       AND (to_jsonb(OLD) - 'revision_payload') =
           (to_jsonb(NEW) - 'revision_payload')
       AND NEW.revision_payload = '{}'::jsonb
       AND EXISTS (
           SELECT 1 FROM public.data_purge_requests purge
            JOIN public.data_purge_inventory_manifests manifest
              ON manifest.purge_request_id = purge.id
           WHERE purge.id::text = wipe_request
             AND purge.state = 'in_progress'
       ) THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'CONFIDENT_MOMENT_APPEND_ONLY';
END;
$$;

REVOKE ALL ON FUNCTION public.reject_feedback_revision_mutation_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS feedback_revisions_append_only ON public.feedback_revisions;
CREATE TRIGGER feedback_revisions_append_only
    BEFORE UPDATE OR DELETE ON public.feedback_revisions
    FOR EACH ROW EXECUTE FUNCTION public.reject_feedback_revision_mutation_v1();

-- The wipe counts an owner row it could not reach as content left behind.
DO $owner_rows_counted$
DECLARE
    target regprocedure :=
        'public.tombstone_phase1_purge_lineage_v1(uuid)'::regprocedure;
    definition text;
    marker constant text := '/* 0448 owner rows counted */';
    anchor constant text :=
        'PERFORM set_config(''willab.purge_wipe_request_id'', '''', true);';
    branch constant text := $branch$/* 0448 owner rows counted */
    -- A speaker's own feedback_revisions rows (rater_id = a user id of the
    -- frozen graph) that still carry a payload: zero when every one hung off
    -- a span this wipe reached, anything else a failure.
    IF to_regclass('public.feedback_revisions') IS NOT NULL THEN
        SELECT count(*) INTO remaining
          FROM public.feedback_revisions revision
         WHERE revision.rater_role = 'owner'
           AND revision.rater_id::text IN (
               SELECT jsonb_array_elements_text(
                   COALESCE(manifest.subject_graph->'user_ids', '[]'::jsonb)))
           AND NOT public.purge_lineage_value_erased_v1(revision.revision_payload);
        not_blank := not_blank + remaining;
    END IF;

    $branch$;
BEGIN
    definition := pg_get_functiondef(target);
    IF position(marker IN definition) > 0 THEN
        RETURN;  -- applied by an earlier run
    END IF;
    IF (length(definition) - length(replace(definition, anchor, '')))
       / length(anchor) <> 1 THEN
        RAISE EXCEPTION 'OWNER_ROWS_ANCHOR_NOT_UNIQUE';
    END IF;
    EXECUTE replace(definition, anchor, branch || anchor);
    IF position(marker IN pg_get_functiondef(target)) = 0 THEN
        RAISE EXCEPTION 'OWNER_ROWS_BRANCH_DID_NOT_LAND';
    END IF;
END
$owner_rows_counted$;

REVOKE ALL ON FUNCTION public.tombstone_phase1_purge_lineage_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.tombstone_phase1_purge_lineage_v1(UUID)
    TO service_role;

COMMIT;
