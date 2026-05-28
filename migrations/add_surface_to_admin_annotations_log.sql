-- Phase 18.x: tag each RLHF row with the edit surface it came from.
--
-- admin_annotations_log now collects rows from multiple write
-- paths with distinct semantics:
--
--   "session_kpi_narrative"  — admin edited the Performance
--                               summary narrative via
--                               PATCH /v2/admin/sessions/<id>/
--                               kpi-narrative. Pipeline-only edit;
--                               user-side never re-fires.
--   "publish_session_comment" — admin clicked Publish; the
--                               session-level final_human_comment
--                               row that pairs ai_predicted_session_
--                               comment with the admin's final.
--   "publish_question_p1".."p5"
--                              — per-position Director's Script
--                               question rows written by the same
--                               publish action.
--
-- Without a tag column, the weekly RLHF cron can't tell these
-- apart — which matters for "are corrections to the narrative
-- higher signal than corrections to the publish comment?" kind
-- of analysis. Pure metadata; no FE consumer.
--
-- Nullable so old rows + any future writer that forgets to set
-- it just lands NULL (graceful — the cron filters NULL out of
-- per-surface aggregates rather than crashing). New writers
-- should always set it.
--
-- Idempotent.

ALTER TABLE admin_annotations_log
    ADD COLUMN IF NOT EXISTS surface TEXT;

COMMENT ON COLUMN admin_annotations_log.surface IS
    'Phase 18.x — names the admin-edit write path this row came '
    'from. Values: "session_kpi_narrative" | "publish_session_'
    'comment" | "publish_question_p1".."p5". NULL on rows written '
    'before this column existed.';

-- Partial index for per-surface RLHF analytics. The cron's
-- "corrections only" filter already has its own index; this one
-- helps aggregate "all rows on surface X" queries.
CREATE INDEX IF NOT EXISTS idx_admin_annotations_log_surface
    ON admin_annotations_log(surface)
    WHERE surface IS NOT NULL;

NOTIFY pgrst, 'reload schema';
