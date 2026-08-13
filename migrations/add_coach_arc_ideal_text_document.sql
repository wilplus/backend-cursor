-- willab — the ideal text's PIECE PROVENANCE, persisted beside its text
-- (founder 2026-08-13, unblocking the acoustic swap lane).
--
-- WHY THIS EXISTS. services/part_acoustics.fold_session has read
-- `coach_arc_ideal_text.document -> pieces` since it shipped, and that column
-- has never existed — not in add_coach_arc_ideal_text.sql, not in either
-- ALTER since. So the read resolved to NULL, `pieces` came back empty, and the
-- function returned {} on EVERY call without logging: no arc_part_acoustics
-- row was ever written, `focus_part_id` returned None for every arc, and the
-- single-point-focus ratchet never engaged. A KPI that measured nothing looked
-- exactly like a quiet arc.
--
-- WHAT GOES IN IT. The assembled document's piece list —
--   [{snippet_id, take_session_id, take_index, start, end, text, slide_index}]
-- where start/end are CHARACTER offsets into the served text. That is the
-- anchor contract services/transcript_document.py already produces and tracked
-- changes already hang on; this only persists it so a later take can score the
-- CURRENT best-of assembly per part instead of reassembling it.
--
-- NOT the acoustics. `metrics` is deliberately absent from the stored shape
-- and joined in at fold time from the snippet rows (services/part_acoustics.py
-- `_with_metrics`). Persisting a copy of per-piece acoustics here would mint a
-- second, staler home for numbers that already have one, and the founder's
-- standing rule on filler/detector data is that measurements are versioned in
-- one place, never duplicated into a form that can silently drift from it.
--
-- AC-9: internal provenance only. Nothing in this column is a verdict and
-- nothing in it is surfaced; the served text is unchanged by this migration.
--
-- Idempotent, additive, nullable. Pre-migration arcs read NULL and fold
-- nothing — exactly today's behaviour — until their next assembly writes a
-- document. NO BACKFILL, on purpose: the piece list is only meaningful against
-- the text it was anchored to, and synthesising one from `text` alone would
-- fabricate offsets nobody measured.
ALTER TABLE public.coach_arc_ideal_text
    ADD COLUMN IF NOT EXISTS document JSONB NULL;

COMMENT ON COLUMN public.coach_arc_ideal_text.document IS
    'Piece provenance for the assembled ideal text: {"pieces": [{snippet_id, '
    'take_session_id, take_index, start, end, text, slide_index}], '
    '"take_session_id", "take_index"}. start/end are character offsets into '
    'the served text. Internal (AC-9); acoustics are joined at read time, '
    'never stored here.';
