-- Life Panel — provenance for rows drafted from an uploaded document
-- (FE document dock, 2026-07-31).
--
-- WHY A THIRD ORIGIN COLUMN. life_items already records two provenances:
-- `origin_case_id` (a `#mistake` case the engine worked a principle out of)
-- and `origin_note_id` (something typed into the chat). A row that came out
-- of an uploaded document has NEITHER — the person wrote it in a file, the
-- draft step read it back, and they ticked it on a screen. Without a third
-- column that row is indistinguishable from one the engine derived, and
-- /panel/principles/:id renders the five slots and the application log for
-- both. Recording it is what keeps "the engine proposed this" honest.
--
-- The `source` enum that would say 'import' lives on life_notes, not on
-- items, so it is not available to reuse here; and reusing origin_note_id
-- would mean writing an id that points at no note.
--
-- NULLABLE AND UNSTAMPED BY DEFAULT. Every existing row keeps NULL, which is
-- the truth about it. /v2/life/setup/apply-proposed fills the column only
-- when it is told which document was drafted from AND that document resolves
-- to one of the caller's own — never guessed from "the latest upload", which
-- would quietly mis-attribute a row when someone uploads a second document
-- between drafting and ticking.
--
-- NO FOREIGN KEY, matching origin_case_id: the panel's hard-delete removes
-- documents and items independently (BE-10), and a cascade there would turn
-- "delete my uploads" into "delete the rows I made from them".
--
-- RUN THIS IN THE SUPABASE SQL EDITOR. Idempotent — re-running is a no-op.
-- Nothing is dropped. life_items already has RLS enabled (add_life_panel.sql
-- §5) and adding a column does not disturb it; this file creates no table, so
-- it enables none.

ALTER TABLE life_items
    ADD COLUMN IF NOT EXISTS origin_document_id uuid;

-- "Which rows came out of this document" is the read that makes the column
-- worth having. Partial, like life_items_origin_case_idx: the overwhelming
-- majority of rows are NULL here and do not belong in the index.
CREATE INDEX IF NOT EXISTS life_items_origin_document_idx
    ON life_items (origin_document_id)
    WHERE origin_document_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────
-- POST-CONDITION — verify the column actually landed. A half-applied
-- migration would let the apply endpoint drop provenance silently on every
-- write; raise instead, so a partial run is a failed run.
-- ─────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'life_items'
           AND column_name = 'origin_document_id'
    ) THEN
        RAISE EXCEPTION
            'life_items.origin_document_id was not created';
    END IF;
END $$;
