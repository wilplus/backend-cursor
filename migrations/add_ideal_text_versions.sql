-- willab — per-VERSION ideal-text snapshots (founder 2026-07-20).
--
-- The gradual-refinement vision: each version bubble (1.0, 2.0, …) keeps
-- ITS OWN step readable — the text as it stood and that step's reasoning
-- (the pending stars at assembly time). The live row (coach_arc_ideal_text)
-- only ever holds the CURRENT version; without this table an old bubble
-- can only open the live notebook (the FE-verified gap, 2026-07-20).
--
-- Append-only, written by the worker when a version persists; idempotent
-- per (arc, version) — a no-change reassembly re-writes the same snapshot.
-- History starts at deploy: versions assembled before this table exist
-- only as their bubbles (the GET answers historical_unavailable and the
-- FE falls back to the live view).
--
-- moments: the SANITIZED pending suggestions at snapshot time (kind,
-- replacement, why, quote, trigger already clamped to 'polish'|null —
-- AC-9/CONSTRUCT enforced at WRITE time, nothing internal is stored).
--
-- Idempotent; RLS on, no policy (service-role only).
CREATE TABLE IF NOT EXISTS public.ideal_text_versions (
    arc_id     TEXT NOT NULL,
    version    INT  NOT NULL,
    text       TEXT NOT NULL,
    moments    JSONB NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arc_id, version)
);
CREATE INDEX IF NOT EXISTS idx_ideal_text_versions_arc
    ON public.ideal_text_versions (arc_id);
ALTER TABLE public.ideal_text_versions ENABLE ROW LEVEL SECURITY;
