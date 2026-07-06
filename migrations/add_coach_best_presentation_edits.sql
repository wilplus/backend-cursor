-- willab — coach-owned ideal-text correction (founder 2026-07-06, bigger-scope
-- decision on the $25 pricing pass): the coach directly rewrites the
-- auto-assembled best-presentation text per slide. The auto draft is NEVER
-- shown to the student — only this coach-corrected version, and only once
-- EVERY slide has been through the coach (see services/best_presentation.py
-- coach_finalized) AND the arc is paid.
--
-- Mirrors best_presentation_edits (the pre-existing USER pencil-edit table)
-- exactly, but coach-authored + service-role-only (never client-read/written
-- directly by a student — routes/v2_routes.py's new /v2/coach/arc/<id>/...
-- endpoints, @require_admin_or_coach, are the sole writers).
CREATE TABLE IF NOT EXISTS coach_best_presentation_edits (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    arc_id      UUID NOT NULL,
    slide_index INTEGER NOT NULL,
    text        TEXT NOT NULL,              -- the coach's corrected slide text
    edited_by   UUID,                       -- the coach who saved it
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (arc_id, slide_index)
);

CREATE INDEX IF NOT EXISTS idx_coach_best_presentation_edits_arc
    ON coach_best_presentation_edits (arc_id);

-- Service-role only (coach-authored, never a direct client write/read).
ALTER TABLE coach_best_presentation_edits ENABLE ROW LEVEL SECURITY;

-- Rollback (manual):
--   DROP TABLE IF EXISTS coach_best_presentation_edits;
