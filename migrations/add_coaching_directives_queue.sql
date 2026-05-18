-- Phase Directives-Queue (BE) — user-level 5-step coaching arc
--
-- Replaces the single-question admin override
-- (user_settings.queued_override_question) and the per-snippet
-- next_question_1..5 / intent_tag_1..5 columns (which conceptually
-- steer the NEXT TURN of a conversation, not a snippet) with a
-- proper user-scoped table.
--
-- One active arc per user at a time. Five rows per arc, position
-- 1..5 (CHECK). When the chat / interview surface needs the next
-- AI question, it pops the lowest-position un-exhausted row,
-- marks it exhausted, and uses its `question` verbatim. When the
-- queue is empty, the surface falls back to the dynamic
-- _generate_llm_question pipeline.
--
-- "One active arc per user" enforced by UNIQUE (user_id, position):
-- on POST the application layer DELETEs the existing rows for the
-- user before INSERTing the new five. Exhausted rows are NOT kept
-- across re-POSTs — the historical audit lives in the application
-- log (logger.info with structured fields), not in this table.
--
-- created_by_admin_id is NULLABLE — admin tooling that goes
-- through service-role keys (cron, scripts) won't have it.
--
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'public'
      AND table_name = 'coaching_directives_queue'
  ) THEN
    CREATE TABLE coaching_directives_queue (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id UUID NOT NULL
        REFERENCES auth.users(id) ON DELETE CASCADE,
      position INT NOT NULL
        CHECK (position BETWEEN 1 AND 5),
      intent_tag TEXT NOT NULL,
      question TEXT NOT NULL,
      exhausted BOOLEAN NOT NULL DEFAULT FALSE,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      created_by_admin_id UUID NULL,
      UNIQUE (user_id, position)
    );

    -- Hot read pattern: "next un-exhausted directive for this
    -- user, lowest position first" (db.pop_next_directive). The
    -- partial index keeps it tiny — at most 5 rows per user
    -- before exhausting.
    CREATE INDEX idx_cdq_user_next_unconsumed
      ON coaching_directives_queue (user_id, position)
      WHERE NOT exhausted;
  END IF;
END $$;

COMMENT ON TABLE coaching_directives_queue IS
  'Phase Directives-Queue (BE) — user-level 5-step coaching arc. '
  'Admin authors a sequence of questions; the chat / interview '
  'surface pops them one at a time in position order, marking '
  'each exhausted as it fires. When empty, the surface falls back '
  'to the dynamic LLM question generator. Re-POST by the admin '
  'replaces the whole arc atomically (DELETE + INSERT in one '
  'transaction at the application layer).';

COMMENT ON COLUMN coaching_directives_queue.intent_tag IS
  'Free-text label the LLM suggester emits alongside each '
  'question (e.g. "warm-up", "probe", "challenge", "reflect", '
  '"close"). Not an enum — admins can edit to anything. Stored '
  'so the turn-execution log can later attribute which intent '
  'the AI is pursuing.';

COMMENT ON COLUMN coaching_directives_queue.exhausted IS
  'TRUE once the chat / interview surface has consumed this '
  'directive as a turn. Pop is atomic-ish (two-step SELECT then '
  'UPDATE; race is theoretical for admin-driven workflows).';

COMMENT ON COLUMN coaching_directives_queue.created_by_admin_id IS
  'auth.users.id of the admin who POSTed the arc. NULL for '
  'service-role writes (cron, scripts). Used only for human '
  'audit; row lifecycle does not depend on it.';
