-- willab — editable Best-Presentation text (Prompt D, design review 2026-06-18).
--
-- The best-presentation is COMPOSED on every read from the user's best lines.
-- This stores a per-slide TEXT OVERRIDE so the user's pencil-edit persists: the
-- read returns the override when present, else the freshly-composed text. One
-- row per (arc, slide); editing the same slide upserts. Idempotent.
CREATE TABLE IF NOT EXISTS best_presentation_edits (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID,                       -- who saved it (owner)
    arc_id      UUID NOT NULL,
    slide_index INTEGER NOT NULL,
    text        TEXT NOT NULL,              -- the user's edited slide text
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (arc_id, slide_index)
);

CREATE INDEX IF NOT EXISTS idx_best_presentation_edits_arc
    ON best_presentation_edits (arc_id);
