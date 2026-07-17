-- willab — preserve the MACHINE ideal-text draft beside the coach's working
-- copy (founder re-lock 2026-07-17: the instant lane).
--
-- The instant lane serves the machine-assembled ideal text to the student
-- FREE the moment take 3 lands, while the coach-perfected `text` stays behind
-- approval + the $25 unlock. Until now the single `text` column meant the
-- first coach edit DESTROYED the machine draft — the two must coexist:
--   * text        — the working/perfected copy (coach edits own it)
--   * auto_text   — the frozen machine copy (re-records refresh it; coach
--                   edits never touch it; the free instant surface serves it)
--
-- Idempotent. Backfill: machine-owned rows (updated_by IS NULL) copy their
-- text into auto_text so pre-migration arcs serve instantly too.
--
-- L1 note: auto_text is only ever assemble_ideal_text_block output —
-- verbatim-select + light continuity polish, never an AI free-write.
ALTER TABLE public.coach_arc_ideal_text
    ADD COLUMN IF NOT EXISTS auto_text TEXT NULL,
    ADD COLUMN IF NOT EXISTS auto_updated_at TIMESTAMPTZ NULL;

UPDATE public.coach_arc_ideal_text
   SET auto_text = text,
       auto_updated_at = updated_at
 WHERE updated_by IS NULL
   AND approved_at IS NULL
   AND auto_text IS NULL;
