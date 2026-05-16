-- RLHF training log: one row per session publish, capturing the
-- (AI prediction, human final) pair for the weekly fine-tuning
-- cron-job.
--
-- Distinct from admin_annotation_events (which is per-snippet,
-- per-field). This table is session-level — one row per Publish
-- click — and rolls up the two highest-signal fields we want to
-- train on: the overall "what would you tell this user"
-- admin_comment + the suggested next_question for their next
-- coaching loop.
--
-- was_corrected makes the training query trivial: weekly cron
-- selects rows WHERE was_corrected = TRUE and ships them as
-- the correction-pair training set. Acceptance rows (FALSE) are
-- still useful as positive examples that the prediction landed.
--
-- Run in Supabase SQL Editor. Idempotent.

CREATE TABLE IF NOT EXISTS admin_annotations_log (
    id                     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id             UUID        NOT NULL REFERENCES v2_sessions(id) ON DELETE CASCADE,
    ai_predicted_comment   TEXT,
    ai_predicted_question  TEXT,
    final_human_comment    TEXT,
    final_human_question   TEXT,
    was_corrected          BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Weekly cron-job filter: "all rows from this user / from the
-- last N days" — both supported by an ordered index on user_id.
CREATE INDEX IF NOT EXISTS idx_admin_annotations_log_user_created
    ON admin_annotations_log(user_id, created_at DESC);

-- One-row-per-session lookup the publish handler uses for
-- idempotency probes.
CREATE INDEX IF NOT EXISTS idx_admin_annotations_log_session
    ON admin_annotations_log(session_id);

-- Bulk training-set selector: "all corrections in the last week"
-- — the partial index keeps it tiny since acceptances dominate.
CREATE INDEX IF NOT EXISTS idx_admin_annotations_log_corrections
    ON admin_annotations_log(created_at DESC)
    WHERE was_corrected = TRUE;

COMMENT ON TABLE admin_annotations_log IS
  'Session-level RLHF training log. One row per admin Publish '
  'click captures the (AI prediction, human final) pair for the '
  'admin_comment + next_suggested_question fields. Weekly cron '
  'selects WHERE was_corrected = TRUE as the correction-pair '
  'fine-tuning set.';

COMMENT ON COLUMN admin_annotations_log.was_corrected IS
  'TRUE when the admin edited the AI suggestion before publish, '
  'FALSE when they accepted it raw. Computed in the publish '
  'handler by string-comparing ai_predicted_* vs final_human_*.';
