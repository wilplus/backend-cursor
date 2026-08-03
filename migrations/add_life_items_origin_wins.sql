-- Life Panel — provenance for principles proposed from the Wins wall
-- (piece 6 of the founder-agreed program, 2026-08-02: wins → proposed
-- principles).
--
-- WHY A FOURTH ORIGIN COLUMN, AND WHY AN ARRAY. life_items already records
-- three provenances: `origin_case_id` (a #mistake the engine worked a
-- principle out of), `origin_note_id` (something typed into the chat) and
-- `origin_document_id` (a row ticked out of an uploaded document). A
-- principle proposed from the Wins wall has NONE of those — and, unlike a
-- case, it is usually grounded in SEVERAL wins at once: the whole point of
-- the derivation is a pattern across them, and "which wins taught this" is
-- the record that keeps the proposal honest. Hence jsonb, not uuid: the
-- grounding is a set, and flattening it to one id would silently discard the
-- others.
--
-- NULLABLE AND UNSTAMPED BY DEFAULT. Every existing row keeps NULL, which is
-- the truth about it. Only the wins derivation writes the column, and only
-- with the ids of wins that were actually in the window the model read —
-- never inferred after the fact.
--
-- NO FOREIGN KEY AND NO INDEX, matching origin_case_id's reasoning: the
-- panel's hard-delete removes wins and principles independently (BE-10), and
-- the read ("which wins ground this principle") is per-row on one user's
-- data — a GIN index over a mostly-NULL jsonb column would be cost without a
-- query to serve.
--
-- ORDERING IS NOT A DEPLOY BLOCKER. The derivation retries its insert
-- without the column when the write is refused: an unrun migration costs the
-- provenance, never the proposal.
--
-- RUN THIS IN THE SUPABASE SQL EDITOR. Idempotent — re-running is a no-op.
-- Nothing is dropped. life_items already has RLS enabled (add_life_panel.sql
-- §5) and adding a column does not disturb it; this file creates no table,
-- so it enables none.

ALTER TABLE life_items
    ADD COLUMN IF NOT EXISTS origin_win_ids jsonb;

-- ─────────────────────────────────────────────────────────────────────────
-- POST-CONDITION — verify the column actually landed. A half-applied
-- migration would let the derivation drop its grounding silently on every
-- write; raise instead, so a partial run is a failed run.
-- ─────────────────────────────────────────────────────────────────────────
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'public'
           AND table_name = 'life_items'
           AND column_name = 'origin_win_ids'
    ) THEN
        RAISE EXCEPTION
            'life_items.origin_win_ids was not created';
    END IF;
END $$;
