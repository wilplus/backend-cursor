-- 0421 · An accepted rewrite names its revision (contract 16; founder
--        2026-10-05, decisions log N48.1, "Closing the Gap" Wave 1 step 5;
--        coach-panel lock C11: "Accept writes a new version of the
--        Paragraph, labelled 'Correction accepted'").
--
-- A Paragraph's History reads the per-Slide document snapshots, which are
-- written only when a Take is finalized. An accepted rewrite writes an
-- `ideal_text_part_revision` through compare_and_set_user_ideal_edit_v1 with
-- action 'owner_part_text_updated' -- the same action as a plain owner edit
-- -- so nothing in the row said "this was an accepted proposal", and History
-- could not show it as its own row.
--
-- WHAT CHANGES, AND ONLY THAT.
--
--  1. One nullable column, `provenance`, on ideal_text_part_revision, with a
--     CHECK: NULL, or 'accepted_rewrite' on a revision that changed a
--     Paragraph's text. Every existing row stays NULL. There is no metadata
--     column on this table to reuse, and the row is immutable after insert
--     (ideal_text_part_revision_immutable), so the name has to be written
--     with the row, by the writer that inserts it.
--
--  2. The owner-edit writer's one revision INSERT gains that column. Its
--     value is 'accepted_rewrite' when, and only when, the row changes the
--     text of the one Paragraph accept_rewrite_into_part_v1 (0418) names for
--     this transaction (`willab.accepted_rewrite_part`, set and cleared by
--     that function alone); every other row, and every other caller, writes
--     NULL exactly as before. accept_rewrite_into_part_v1 itself is
--     unchanged: it already names the Paragraph for the transaction.
--
-- The INSERT is patched in place from the installed definition, as 0418
-- patched its guard: the function is 300 lines and copying it would fork it.
-- Each fragment must be found exactly once or the migration refuses loudly;
-- it is a no-op when already applied. Grants are kept by CREATE OR REPLACE.
--
-- No backfill: revisions written before this file carry no name and cannot
-- be told apart from an owner edit, so they stay NULL (never guessed).
--
-- Changes no rows. Idempotent.

BEGIN;

ALTER TABLE public.ideal_text_part_revision
    ADD COLUMN IF NOT EXISTS provenance text NULL;

ALTER TABLE public.ideal_text_part_revision
    DROP CONSTRAINT IF EXISTS ideal_text_part_revision_provenance_check;
ALTER TABLE public.ideal_text_part_revision
    ADD CONSTRAINT ideal_text_part_revision_provenance_check CHECK (
        provenance IS NULL
        OR (provenance = 'accepted_rewrite'
            AND action IN ('owner_part_text_updated',
                           'owner_part_text_updated_and_reordered')));

DO $accepted_rewrite_provenance$
DECLARE
    target regprocedure :=
        'public.compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)'::regprocedure;
    definition text;
    patched text;
    marker constant text := '/* 0421 accepted rewrite provenance */';
    columns_before constant text :=
        'owner_edit_operation_id,revision_contract_version)';
    columns_after constant text :=
        'owner_edit_operation_id,revision_contract_version,provenance)';
    values_before constant text :=
        'op.id,''ideal-text-part-revision-v2'');';
    values_after constant text :=
        'op.id,''ideal-text-part-revision-v2'',' || '/* 0421 accepted rewrite provenance */'
        || ' CASE WHEN change.item->>''action'' IN(''owner_part_text_updated'','
        || '''owner_part_text_updated_and_reordered'') '
        || 'AND (change.item->>''part_id'')::uuid='
        || 'NULLIF(current_setting(''willab.accepted_rewrite_part'',true),'''')::uuid '
        || 'THEN ''accepted_rewrite'' END);';
BEGIN
    definition := pg_get_functiondef(target);
    IF position(marker IN definition) > 0 THEN
        RETURN;  -- applied by an earlier run
    END IF;
    IF (length(definition) - length(replace(definition, columns_before, '')))
       / length(columns_before) <> 1
       OR (length(definition) - length(replace(definition, values_before, '')))
       / length(values_before) <> 1 THEN
        RAISE EXCEPTION 'ACCEPTED_REWRITE_PROVENANCE_LINE_NOT_UNIQUE';
    END IF;
    patched := replace(replace(definition, columns_before, columns_after),
                       values_before, values_after);
    EXECUTE patched;
    IF position(marker IN pg_get_functiondef(target)) = 0 THEN
        RAISE EXCEPTION 'ACCEPTED_REWRITE_PROVENANCE_EDIT_DID_NOT_LAND';
    END IF;
END
$accepted_rewrite_provenance$;

-- CREATE OR REPLACE (the EXECUTE above) preserves the ACL; re-stated so the
-- file is self-describing.
REVOKE ALL ON FUNCTION public.compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)
    FROM PUBLIC, anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.compare_and_set_user_ideal_edit_v1(uuid,text,integer,bigint,text,text,jsonb,text)
    TO service_role;

COMMIT;

NOTIFY pgrst, 'reload schema';
