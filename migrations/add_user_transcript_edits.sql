-- willab — user transcript edits (founder 2026-07-07): the user can correct
-- the transcript text on their own readout. The edit is the USER'S layer —
-- the coach keeps reviewing the ORIGINAL transcript (charisma_snippets /
-- slide_transcripts are untouched); readout reads prefer the edit for
-- display only. Mirrors best_presentation_edits (the user pencil-edit
-- precedent) with two target kinds:
--   * a snippet's transcript        → snippet_id set, chunk_index NULL
--   * a deckless full-transcript    → chunk_index set (index into the
--     ~50-word full_transcript_chunks), snippet_id NULL
--
-- Service-role only (RLS on, no policy); the /v2 route owner-gates by
-- session.user_id. Idempotent — safe to re-run.

CREATE TABLE IF NOT EXISTS user_transcript_edits (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id   UUID NOT NULL,
    snippet_id   UUID NULL,
    chunk_index  INTEGER NULL,
    text         TEXT NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, snippet_id),
    UNIQUE (session_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_user_transcript_edits_session
    ON user_transcript_edits (session_id);

ALTER TABLE user_transcript_edits ENABLE ROW LEVEL SECURITY;

-- Rollback (manual):
--   DROP TABLE IF EXISTS user_transcript_edits;
