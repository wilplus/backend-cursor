-- willab beta — lounge_messages (BE contract §3.15 + Appendix A).
--
-- The Lounge is HOME and must read like a continuous chat that survives
-- reload + device switch. Today the FE thread is in-memory; this is the
-- per-user server store the FE rehydrates on mount and appends to.
--
-- Scope guardrails (do not violate — BE contract §2 / AC-6):
--   * text/transcripts ONLY — never audio (Lounge speech is client-side
--     Web Speech, not Whisper).
--   * the thread is NEVER part of the coach packet and NEVER feeds
--     profile / inferred_learner_profile.
--   * continuity only — user-deletable; account deletion cascades.
--
-- Ownership: the FE persists every bubble it renders, INCLUDING bot
-- replies (contract §7.6 — FE-append). /v2/chat/query stays stateless
-- about the thread; BE does not write bot turns server-side.
--
-- Idempotency: UNIQUE(user_id, client_id) makes append + merge-on-signup
-- both no-op-on-retry. The FE owns client_id (dedup) and
-- client_created_at (the ordering key that survives the unsigned→signed
-- merge).
--
-- Idempotent migration. Safe to re-run.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS lounge_messages (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    client_id         UUID NOT NULL,              -- FE-generated; idempotency + dedup
    role              TEXT NOT NULL,              -- 'user' | 'bot' | 'system'
    kind              TEXT NOT NULL,              -- 'text' | 'joke' | 'status' | 'recording_summary' | 'insight'
    body              TEXT NOT NULL DEFAULT '',
    metadata          JSONB,                      -- e.g. { session_id, insight_ref } on status/insight lines
    client_created_at TIMESTAMPTZ NOT NULL,       -- FE-stamped; the ordering key (preserves merge order)
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, client_id)                   -- idempotent append + merge
);

-- Primary read path: rehydrate latest N for a user, page up via cursor.
CREATE INDEX IF NOT EXISTS lounge_messages_user_created_ix
    ON lounge_messages (user_id, client_created_at);

-- Enum guards (idempotent via pg_constraint probe). role/kind kept as
-- TEXT + CHECK rather than native enums so adding a kind later is an
-- ALTER CONSTRAINT, not a type migration.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'lounge_messages_role_check'
    ) THEN
        ALTER TABLE lounge_messages ADD CONSTRAINT lounge_messages_role_check
            CHECK (role IN ('user', 'bot', 'system'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'lounge_messages_kind_check'
    ) THEN
        ALTER TABLE lounge_messages ADD CONSTRAINT lounge_messages_kind_check
            CHECK (kind IN ('text', 'joke', 'status', 'recording_summary', 'insight'));
    END IF;
END$$;

-- ── Row-Level Security (BE contract §7.9 — the RLS half) ────────────
-- The Flask BE uses the Supabase service-role key, which BYPASSES RLS,
-- so the @require_auth endpoint guard (scoping every query to
-- request.user_id) is the load-bearing protection. These policies are
-- defense-in-depth: if anything ever queries this table with a user's
-- own JWT (direct Supabase client), it can only ever touch its own
-- rows. Owner-only on all four verbs.
ALTER TABLE lounge_messages ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'lounge_messages' AND policyname = 'lounge_owner_select'
    ) THEN
        CREATE POLICY lounge_owner_select ON lounge_messages
            FOR SELECT USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'lounge_messages' AND policyname = 'lounge_owner_insert'
    ) THEN
        CREATE POLICY lounge_owner_insert ON lounge_messages
            FOR INSERT WITH CHECK (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'lounge_messages' AND policyname = 'lounge_owner_update'
    ) THEN
        CREATE POLICY lounge_owner_update ON lounge_messages
            FOR UPDATE USING (auth.uid() = user_id) WITH CHECK (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'lounge_messages' AND policyname = 'lounge_owner_delete'
    ) THEN
        CREATE POLICY lounge_owner_delete ON lounge_messages
            FOR DELETE USING (auth.uid() = user_id);
    END IF;
END$$;

COMMENT ON TABLE lounge_messages IS
    'willab beta §3.15 — per-user Lounge chat thread (text only, never '
    'audio, never in coach packet, never profiled). FE-append incl. bot '
    'turns; idempotent on (user_id, client_id); client_created_at is the '
    'ordering key surviving unsigned→signed merge. RLS owner-only '
    '(defense-in-depth; Flask service-role bypasses it).';

NOTIFY pgrst, 'reload schema';
