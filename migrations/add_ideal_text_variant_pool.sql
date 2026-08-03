-- willab — the VARIANT POOL + COMPOSITIONS (founder 2026-08-03).
--
-- The three usability fears this dissolves ("kills the app if any
-- happens"): (1) my previous take's text is lost after I record the next
-- one; (2) the new text is worse and I can't go back; (3) I want pieces
-- of both and have no way to put them together.
--
-- Root cause: the master keeps ONE incumbent + ONE challenger slot per
-- block — a newer winning offer OVERWRITES an older pending one, and the
-- student's whole-document edit lives as a blob a new version supersedes
-- ("retained, not shown"). Both are whole-copy-wins; neither can mix.
--
-- The model (founder-approved 2026-08-03, block-level granularity):
--   * ideal_text_block_variants — APPEND-ONLY pool: every candidate text
--     a block has ever had. source_kind 'take' = verbatim recorded pieces
--     (L1); 'user_edit' = the STUDENT's own restructuring of the block
--     (their words, never AI — L1-compatible). Nothing here is ever
--     overwritten or deleted by a new take.
--   * ideal_text_compositions — APPEND-ONLY revisions of the selection:
--     [{block_key, variant_id}] in block order. "My text" is a pointer
--     list, not a copy — undo/restore is repointing, never data loss.
--   * ideal_text_composition_head — the one live pointer per arc.
--
-- The blocks table stays the ASSEMBLY source of truth (flag OFF is
-- byte-for-byte today); the pool/compositions dual-write beside it and
-- the picker read paths gate on BLOCK_VARIANTS_ENABLED.
--
-- AC-9: take_index/source are provenance, never a score; no ranking
-- numbers are stored here. L2 untouched — offer judging stays the
-- blended ranking on the blocks lane.
--
-- Idempotent; additive; RLS on, no policy (service-role only).
CREATE TABLE IF NOT EXISTS public.ideal_text_block_variants (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    arc_id           TEXT NOT NULL,
    block_key        INT  NOT NULL,
    source_kind      TEXT NOT NULL
        CHECK (source_kind IN ('take', 'user_edit')),
    take_session_id  TEXT NULL,   -- 'take': the origin take (dedup key)
    take_index       INT  NULL,   -- the badge (1.0/2.0…) — provenance only
    pieces           JSONB NOT NULL DEFAULT '[]',
                                  -- [{snippet_id, text}] verbatim recorded
                                  -- pieces; [] for a user_edit variant
    text             TEXT NOT NULL,
    created_by       UUID NULL,   -- 'user_edit': the editing student
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- One take-sourced variant per (arc, block, take) — a worker re-run
-- refreshes nothing, duplicates nothing.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ideal_variants_take_once
    ON public.ideal_text_block_variants (arc_id, block_key, take_session_id)
    WHERE source_kind = 'take';
CREATE INDEX IF NOT EXISTS idx_ideal_variants_arc
    ON public.ideal_text_block_variants (arc_id, block_key);
ALTER TABLE public.ideal_text_block_variants ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.ideal_text_compositions (
    arc_id     TEXT NOT NULL,
    revision   INT  NOT NULL,
    selections JSONB NOT NULL DEFAULT '[]',
                                 -- [{block_key, variant_id}] block order
    reason     TEXT NULL
        CHECK (reason IN ('seed', 'accept', 'select', 'restore')),
    created_by UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arc_id, revision)
);
ALTER TABLE public.ideal_text_compositions ENABLE ROW LEVEL SECURITY;

CREATE TABLE IF NOT EXISTS public.ideal_text_composition_head (
    arc_id        TEXT PRIMARY KEY,
    head_revision INT  NOT NULL,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE public.ideal_text_composition_head ENABLE ROW LEVEL SECURITY;
