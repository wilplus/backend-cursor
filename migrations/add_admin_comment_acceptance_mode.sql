-- Per-snippet RLHF signal — captures whether the admin accepted
-- the AI-drafted admin_comment raw or corrected it before save.
--
-- Pairs with admin_annotations_log (which is session-level): this
-- column is per-snippet and lets the weekly fine-tuning pipeline
-- pull a higher-resolution signal — every snippet's accept/correct
-- decision, not just the session-level aggregate.
--
-- Values:
--   'accepted_as_is'  → positive RLHF signal; the model was right
--   'admin_corrected' → correction trajectory; the model needs to
--                       learn from the (ai_draft_admin_comment,
--                       admin_comment) diff
--   NULL              → never reviewed yet (legacy or pending row)
--
-- The CHECK is intentionally minimal so the column can grow new
-- enum values later (e.g. 'admin_flagged') without a migration
-- ceremony; only the two values we ship today are accepted.
--
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'charisma_snippets'
      AND column_name = 'admin_comment_acceptance_mode'
  ) THEN
    ALTER TABLE charisma_snippets
      ADD COLUMN admin_comment_acceptance_mode TEXT DEFAULT NULL
        CHECK (
          admin_comment_acceptance_mode IS NULL
          OR admin_comment_acceptance_mode IN (
            'accepted_as_is', 'admin_corrected'
          )
        );
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'charisma_snippets'
      AND column_name = 'admin_comment_acceptance_set_at'
  ) THEN
    ALTER TABLE charisma_snippets
      ADD COLUMN admin_comment_acceptance_set_at TIMESTAMPTZ DEFAULT NULL;
  END IF;
END $$;

-- Weekly cron filter: "all admin_corrected rows from the last
-- N days". Partial index — most rows will be 'accepted_as_is' or
-- NULL once steady-state hits, so the corrections set stays small.
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_corrections
  ON charisma_snippets(admin_comment_acceptance_set_at DESC)
  WHERE admin_comment_acceptance_mode = 'admin_corrected';

COMMENT ON COLUMN charisma_snippets.admin_comment_acceptance_mode IS
  'Per-snippet RLHF signal set when the admin saves the comment '
  'via POST /v2/admin/snippets/<id>/comment. '
  '"accepted_as_is" = positive signal (AI draft was right); '
  '"admin_corrected" = correction trajectory (paired with '
  'ai_draft_admin_comment as the (predicted, final) training '
  'pair). NULL = never reviewed.';

COMMENT ON COLUMN charisma_snippets.admin_comment_acceptance_set_at IS
  'When admin_comment_acceptance_mode was last written. Lets the '
  'weekly RLHF cron window-filter the training set by vintage.';
