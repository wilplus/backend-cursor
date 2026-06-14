-- willab Phase 4 / Prompt 1 — Snippet-Recognition Learning Subsystem (SHADOW).
--
-- The model trains on training_labels (direction-v1) ⋈ charisma_snippets.metrics
-- (the 11 acoustic features) and predicts in SHADOW only — it influences
-- nothing (no selection change, no direction pre-fill). These two tables hold
-- the versioned model registry + the shadow prediction log. Service-role only
-- (RLS on, no policies → the anon/auth keys can't read them; the service-role
-- key bypasses RLS). Additive + idempotent.

-- ── Model registry ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS model_versions (
    version         TEXT PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          TEXT NOT NULL DEFAULT 'shadow',   -- shadow | archived
    schema_version  TEXT,                             -- e.g. direction-v1
    corpus_size     INTEGER,
    metrics         JSONB,                            -- eval metrics
    artifact_ref    TEXT                              -- object-storage key
);
ALTER TABLE model_versions ENABLE ROW LEVEL SECURITY;

-- ── Shadow prediction log (transient / analytics only) ────────────────────
CREATE TABLE IF NOT EXISTS shadow_predictions (
    id                  BIGSERIAL PRIMARY KEY,
    session_id          TEXT,
    snippet_id          TEXT,
    model_version       TEXT,
    predicted_label     TEXT,
    confidence          DOUBLE PRECISION,
    coach_actual_label  TEXT,            -- backfilled when the coach labels
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE shadow_predictions ENABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS idx_shadow_predictions_snippet
    ON shadow_predictions (snippet_id);
CREATE INDEX IF NOT EXISTS idx_shadow_predictions_model
    ON shadow_predictions (model_version);

-- ── Selection provenance on the labels (additive, nullable) ───────────────
-- So a future unbiased/random-sampling lane is distinguishable from the
-- heuristic-selected corpus the shadow model trains on today.
ALTER TABLE training_labels
    ADD COLUMN IF NOT EXISTS selection_source TEXT DEFAULT 'heuristic',
    ADD COLUMN IF NOT EXISTS heuristic_version TEXT;
