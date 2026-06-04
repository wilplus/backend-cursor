-- willab beta — strong_sides_library (design §7, contract §1/§3.11).
--
-- The user's growing collection of the COACH'S OWN notes. After each
-- delivered session, on the user's READ of insights (§3.11 — ingest on
-- read, not at publish), the coach-tagged snippets land here: snippet
-- reference + raw data + the coach's note + tag. The Lounge bot
-- retrieves + replays these ("refresh your strong lines").
--
-- LIBRARIAN, NOT JUDGE (§7): this store holds human-authored coach
-- notes the user already received — safe to replay. It must NEVER be
-- used to compute trajectory/improvement; that's the post-PhD Learning
-- Effectiveness System, out of scope. No cross-session synthesis fields.
--
-- Idempotent ingest: UNIQUE(user_id, snippet_id) so re-reading insights
-- never duplicates a library entry.
--
-- Idempotent migration.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS strong_sides_library (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    session_id   UUID NOT NULL,
    snippet_id   UUID NOT NULL,
    note         TEXT NOT NULL,              -- the coach's words (replayed verbatim)
    tag          TEXT NOT NULL,              -- 'strong' | 'to_work_on'
    snippet_ref  JSONB,                      -- {transcript, features, audio_ref,
                                             --  start_offset_ms, duration_ms}
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, snippet_id)
);

CREATE INDEX IF NOT EXISTS strong_sides_library_user_created_ix
    ON strong_sides_library (user_id, created_at);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'strong_sides_library_tag_check'
    ) THEN
        ALTER TABLE strong_sides_library ADD CONSTRAINT strong_sides_library_tag_check
            CHECK (tag IN ('strong', 'to_work_on'));
    END IF;
END$$;

-- RLS owner-only (defense-in-depth; Flask service-role bypasses it, the
-- @require_auth guard is load-bearing — mirrors lounge_messages).
ALTER TABLE strong_sides_library ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'strong_sides_library' AND policyname = 'strong_sides_owner_select'
    ) THEN
        CREATE POLICY strong_sides_owner_select ON strong_sides_library
            FOR SELECT USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'strong_sides_library' AND policyname = 'strong_sides_owner_modify'
    ) THEN
        CREATE POLICY strong_sides_owner_modify ON strong_sides_library
            FOR ALL USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
    END IF;
END$$;

COMMENT ON TABLE strong_sides_library IS
    'willab beta §7 — per-user collection of coach-tagged snippets, '
    'ingested on the user''s READ of insights (§3.11). Librarian-not-'
    'judge: replay of human-authored notes only, never trajectory '
    'synthesis. UNIQUE(user_id, snippet_id) = idempotent ingest.';

NOTIFY pgrst, 'reload schema';
