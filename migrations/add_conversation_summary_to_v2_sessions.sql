-- Phase A2.1 — rolling conversation summary for the interview surface.
--
-- Replaces the practice of replaying full `previous_turns` to the
-- LLM on every turn (which grows quadratically in tokens) with a
-- running digest persisted on the session row. Per the spec:
--
--   inject `summary + last 2 raw turns` instead of full previous_turns
--
-- One column per session: the most-recent ≤~150-token digest written
-- by services/conversation_summary.py after each turn. NULL until
-- the first update fires; the prompt builder simply omits the
-- summary block when NULL (cold-start unaffected).
--
-- updated_at lets us answer "is this summary stale?" if the upload
-- path fires the async update late or fails entirely.
--
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'v2_sessions'
      AND column_name = 'conversation_summary'
  ) THEN
    ALTER TABLE v2_sessions
      ADD COLUMN conversation_summary TEXT DEFAULT NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'v2_sessions'
      AND column_name = 'conversation_summary_updated_at'
  ) THEN
    ALTER TABLE v2_sessions
      ADD COLUMN conversation_summary_updated_at TIMESTAMPTZ DEFAULT NULL;
  END IF;
END $$;

COMMENT ON COLUMN v2_sessions.conversation_summary IS
  'Phase A2.1 — running ≤~150-token digest of the interview '
  'conversation so far. Written async by services/conversation_'
  'summary.py after each turn upload; read by _generate_llm_'
  'question to replace the quadratic-cost full-history replay. '
  'NULL during cold-start (first turn) — prompt builder omits '
  'the summary block in that case.';

COMMENT ON COLUMN v2_sessions.conversation_summary_updated_at IS
  'When conversation_summary was last (re)generated. Lets the '
  'prompt builder detect staleness (e.g. async update failed, '
  'summary is N turns behind) and decide whether to include or '
  'log a drift warning.';
