-- Task 10 — Next-session icebreaker (split-sinks pattern).
--
-- After session N finalizes, an LLM call reads the session's snippets
-- + admin coaching comments and writes ONE personalized icebreaker
-- question. Admin reviews/edits/regenerates from Tab 1 (Sessions &
-- Analysis). On session N+1's first chat turn, the soft-queue read in
-- /v2/user/chat/first-question delivers the question and marks it
-- delivered.
--
-- Six columns, mirroring the kpi-narrative split-sinks pattern:
--
--   next_session_icebreaker_ai_draft               TEXT
--     Immutable AI baseline. Pinned at generation time. Overwritten
--     ONLY by the generator path (regenerate endpoint or finalize
--     re-runs). Admin edits NEVER touch this column.
--
--   next_session_icebreaker_ai_draft_generated_at  TIMESTAMPTZ
--     When the LLM produced the draft. Used for the FE "AI · hh:mm
--     UTC" timestamp and for the regenerate rate-limit window.
--
--   next_session_icebreaker                        TEXT
--     Current editable value. Defaults to the AI draft at generation
--     time; admin PUTs override it. NULL when status='skipped' (admin
--     explicitly cleared) OR when AI draft never landed.
--
--   next_session_icebreaker_edited_at              TIMESTAMPTZ
--     When the admin last saved an edit. NULL means "never edited"
--     (current == ai_draft). FE renders an "Edited" badge when set.
--
--   next_session_icebreaker_status                 TEXT
--     'pending'   — generated, waiting for n+1 to consume it
--     'skipped'   — admin saved empty; n+1 falls back to default
--                   first-question
--     'delivered' — n+1's first-question route popped it; immutable
--                   from this point on (FE shows read-only card)
--     CHECK constraint enforces the enum. Defaults to 'pending'.
--
--   next_session_icebreaker_generation_error       TEXT
--     Short tag when the LLM call failed: 'llm_timeout' |
--     'transcript_too_short' | 'llm_empty' | etc. NULL on success.
--     FE renders the "Generation failed — Regenerate" red banner
--     when this column is non-null AND ai_draft IS NULL.
--
-- Why a single status column (not booleans):
-- The states are mutually exclusive — a row can't be simultaneously
-- skipped and delivered. A TEXT enum with CHECK keeps the truth
-- table flat and queryable; booleans would let us write nonsense
-- (skipped=true, delivered=true) without DB-level rejection.
--
-- Idempotent. Safe to run twice.

ALTER TABLE v2_sessions
    ADD COLUMN IF NOT EXISTS next_session_icebreaker_ai_draft TEXT,
    ADD COLUMN IF NOT EXISTS next_session_icebreaker_ai_draft_generated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS next_session_icebreaker TEXT,
    ADD COLUMN IF NOT EXISTS next_session_icebreaker_edited_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS next_session_icebreaker_status TEXT DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS next_session_icebreaker_generation_error TEXT;

-- Enum guard. CHECK constraint is idempotent via the DO block:
-- adding an already-existing constraint would raise, so we probe
-- pg_constraint first.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'v2_sessions_next_session_icebreaker_status_check'
    ) THEN
        ALTER TABLE v2_sessions
            ADD CONSTRAINT v2_sessions_next_session_icebreaker_status_check
            CHECK (
                next_session_icebreaker_status IN (
                    'pending', 'skipped', 'delivered'
                )
            );
    END IF;
END$$;

COMMENT ON COLUMN v2_sessions.next_session_icebreaker_ai_draft IS
    'Task 10 — immutable AI baseline of the next-session icebreaker. '
    'Pinned at generation time by services.next_session_icebreaker; '
    'overwritten only on regenerate. Admin edits NEVER touch it.';

COMMENT ON COLUMN v2_sessions.next_session_icebreaker IS
    'Task 10 — admin-editable current value of the icebreaker. '
    'Defaults to the AI draft at generation time. The soft-queue '
    'read in /v2/user/chat/first-question consumes this value (not '
    'the AI draft) so admin edits make it to n+1.';

COMMENT ON COLUMN v2_sessions.next_session_icebreaker_status IS
    'Task 10 — pending | skipped | delivered. pending = waiting for '
    'n+1; skipped = admin cleared (n+1 falls back); delivered = n+1 '
    'consumed it. CHECK constraint enforces the enum.';

NOTIFY pgrst, 'reload schema';
