-- willab — per-PIECE provenance for the discernment system (founder
-- 2026-07-20, "it is critical").
--
-- The master text is a per-piece MIX of takes (80% v1 + 20% v2 → 48/20/32…).
-- One row per (arc, piece slot):
--   * the INCUMBENT — the piece currently in the master text (its take is
--     the version badge the FE renders);
--   * the CHALLENGER — the ranking's new winner when it OUTRANKS the
--     incumbent: the text NEVER swaps silently (founder decision
--     2026-07-20: incumbent stays, badge glows), it waits as
--     status='pending_swap' until the student accepts (swap lands, badge
--     flips, version bumps) or rejects (challenger remembered in
--     rejected_snippet_ids, never re-offered);
--   * challenger_why — a deterministic TEMPLATE KEY (energy | steadiness |
--     coverage | overall), copy lives FE-side (AC-9: no numbers, no raw
--     vocabulary in storage or on the wire).
--
-- piece_key = the ranking's slot (slide index for decked, section index
-- for deckless — the unit the cross-take ranking actually judges).
--
-- L1: both incumbent and challenger are VERBATIM actual takes — this table
-- only records WHICH take the student chose. AC-9: take_index is
-- provenance (the badge), never a score.
--
-- Idempotent; RLS on, no policy (service-role only).
CREATE TABLE IF NOT EXISTS public.ideal_piece_provenance (
    arc_id               TEXT NOT NULL,
    piece_key            INT  NOT NULL,
    incumbent_snippet_id TEXT NOT NULL,
    incumbent_session_id TEXT NULL,
    incumbent_take_index INT  NULL,
    incumbent_text       TEXT NULL,     -- the frozen verbatim at pin time
    display_text         TEXT NULL,     -- the served piece text (post-bake)
    status               TEXT NOT NULL DEFAULT 'settled'
                         CHECK (status IN ('settled', 'pending_swap')),
    challenger_snippet_id TEXT NULL,
    challenger_session_id TEXT NULL,
    challenger_take_index INT  NULL,
    challenger_text       TEXT NULL,
    challenger_why        TEXT NULL,
    rejected_snippet_ids  JSONB NOT NULL DEFAULT '[]',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arc_id, piece_key)
);
CREATE INDEX IF NOT EXISTS idx_ideal_piece_provenance_arc
    ON public.ideal_piece_provenance (arc_id);
ALTER TABLE public.ideal_piece_provenance ENABLE ROW LEVEL SECURITY;
