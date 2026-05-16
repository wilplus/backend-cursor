-- Per-position RLHF signal for the 5-question Director's Script.
--
-- Before: one row per session captured the admin_comment +
-- single next_question pair. After: one row per session for the
-- admin_comment AND five additional rows per session, one per
-- script position, each with its own (predicted, final) pair and
-- was_corrected flag.
--
-- This is a strictly richer training signal — the fine-tune
-- corpus can train one question position at a time, or all five
-- as a sequence, instead of being stuck with session-level
-- aggregates.
--
-- Backwards compatible: existing rows carry question_position
-- IS NULL (legacy single-question signal). New per-position rows
-- always set it. The partial index keeps lookups cheap.
--
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'admin_annotations_log'
      AND column_name = 'question_position'
  ) THEN
    ALTER TABLE admin_annotations_log
      ADD COLUMN question_position INT DEFAULT NULL
        CHECK (
          question_position IS NULL
          OR question_position BETWEEN 1 AND 5
        );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'admin_annotations_log'
      AND column_name = 'intent_tag'
  ) THEN
    ALTER TABLE admin_annotations_log
      ADD COLUMN intent_tag TEXT DEFAULT NULL;
  END IF;
END $$;

-- Position-scoped correction selector for the weekly fine-tune
-- cron. Partial index — most rows will be accepted-as-is or
-- session-level (NULL position), so the per-position correction
-- set stays compact.
CREATE INDEX IF NOT EXISTS idx_admin_annotations_log_position_corrections
  ON admin_annotations_log(question_position, created_at DESC)
  WHERE question_position IS NOT NULL AND was_corrected = TRUE;

COMMENT ON COLUMN admin_annotations_log.question_position IS
  'For per-position 5-question script rows: which position (1..5) '
  'this row captures. NULL for legacy session-level rows that '
  'logged a single next_question or for the session-level '
  'admin_comment row.';

COMMENT ON COLUMN admin_annotations_log.intent_tag IS
  'The intent_tag the AI proposed for this position (ground-'
  'emotion, test-application, rehearse-tactic, challenge-belief, '
  'close-loop, etc.). Soft vocabulary — used as a per-position '
  'feature for fine-tuning.';
