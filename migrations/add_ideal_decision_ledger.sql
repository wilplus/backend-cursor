-- willab — the ideal-text DECISION LEDGER (founder 2026-07-20).
--
-- Gradual refinement, step 2: the per-ARC memory of every decision the
-- student made about their text, keyed by NORMALIZED PHRASE (not snippet)
-- so decisions survive re-picking across takes:
--   * approved  → baked into every future machine copy where the phrase
--                 still occurs (assemble-time), never reversed, never
--                 re-underlined;
--   * dismissed → that suggestion is never generated again for the phrase.
-- A reverted approval DELETES the row (the phrase becomes suggestible
-- again — the student changed their mind, the slate is clean).
--
-- kind: 'polish' (compose smoothing), 'replace', 'emphasize' — matches the
-- star lanes. source: 'user_star' now; 'user_edit'/'recurring' arrive with
-- the protected-phrases pass (PR-3).
--
-- L1: the ledger stores only what the STUDENT explicitly decided; baking
-- applies their decisions, the canonical selection stays verbatim-first.
-- AC-9: internal table — nothing here is a user payload.
--
-- Idempotent; RLS on, no policy (service-role only).
CREATE TABLE IF NOT EXISTS public.ideal_decision_ledger (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    arc_id           TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('polish', 'replace', 'emphasize')),
    target_phrase    TEXT NOT NULL,      -- normalized (the matching key)
    display_phrase   TEXT NULL,          -- original casing (the bake source)
    replacement_text TEXT NULL,          -- what the phrase becomes (polish/replace)
    decision         TEXT NOT NULL CHECK (decision IN ('approved', 'dismissed')),
    source           TEXT NULL,          -- user_star | user_edit | recurring
    snippet_id       TEXT NULL,          -- provenance only, never the key
    version          INT NULL,           -- ideal-text version at decision time
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ideal_ledger_key
    ON public.ideal_decision_ledger (arc_id, kind, target_phrase);
CREATE INDEX IF NOT EXISTS idx_ideal_ledger_arc
    ON public.ideal_decision_ledger (arc_id);
ALTER TABLE public.ideal_decision_ledger ENABLE ROW LEVEL SECURITY;
