-- Force-alignment on reads (F1-CORE handoff §3, 2026-08-03).
-- One row per READ session: the read audio aligned against the exact
-- ideal-text version the user read (ground truth). aligned_transcript =
-- script-faithful transcript; words = per-word timings (ms) with the
-- matched script index; deviations = structured skips / substitutions /
-- insertions (signal, not noise). Idempotent; degrades gracefully — the
-- worker's alignment step just warns until this runs.

CREATE TABLE IF NOT EXISTS read_alignments (
  session_id UUID PRIMARY KEY,
  arc_id UUID,
  ideal_version INT,
  aligned_transcript TEXT,
  words JSONB,
  deviations JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_read_alignments_arc
  ON read_alignments (arc_id, ideal_version);

ALTER TABLE read_alignments ENABLE ROW LEVEL SECURITY;
GRANT ALL ON read_alignments TO service_role;
