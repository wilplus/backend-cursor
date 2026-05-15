-- Capture the user's own Yes/No label on a snippet's "charismatic"
-- read, separate from the admin's coach_label.
--
-- Why a separate column from coach_label / labeled_by_admin_id:
--   - coach_label is the ground-truth admin annotation we use to
--     train + ship the dashboard.
--   - user_charisma_label is the user's self-verification, captured
--     mid-chat ("Would you label your voice here as Charismatic?
--     Yes / No"). Strong RLHF signal — when the user disagrees with
--     the admin, that's a flagging moment worth retraining on.
--
-- Schema choice: BOOLEAN. The user-facing UX is a binary
-- ActionBubble ("Yes" / "No"), and the question is always framed
-- against whatever label the admin already gave (the admin says
-- "this was charismatic" — the user confirms or denies). NULL
-- means "not labelled yet" — the chat state machine drives the
-- column from NULL → true/false once and never overwrites without
-- explicit user intent.
--
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'charisma_snippets'
      AND column_name = 'user_charisma_label'
  ) THEN
    ALTER TABLE charisma_snippets
      ADD COLUMN user_charisma_label BOOLEAN DEFAULT NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'charisma_snippets'
      AND column_name = 'user_charisma_label_set_at'
  ) THEN
    ALTER TABLE charisma_snippets
      ADD COLUMN user_charisma_label_set_at TIMESTAMPTZ DEFAULT NULL;
  END IF;
END $$;

-- Partial index — the RLHF export query reads only labelled rows.
-- Skipping NULLs keeps the index small (most rows are never
-- labelled by the user).
CREATE INDEX IF NOT EXISTS idx_charisma_snippets_user_label
  ON charisma_snippets(user_id, user_charisma_label)
  WHERE user_charisma_label IS NOT NULL;

COMMENT ON COLUMN charisma_snippets.user_charisma_label IS
  'User-confirmed self-label captured mid-chat via the coaching '
  'state machine. TRUE = user labels this snippet as charismatic, '
  'FALSE = user disagrees. NULL = not yet labelled. Distinct from '
  'coach_label (admin annotation) — the (admin, user) pair is the '
  'RLHF signal.';

COMMENT ON COLUMN charisma_snippets.user_charisma_label_set_at IS
  'When user_charisma_label was last written. Lets us window-filter '
  'RLHF training data by label vintage.';
