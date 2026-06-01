-- tester-soft-v1 — Foundation discriminator columns.
--
-- Pure additive: every new column is nullable or carries a default
-- that matches current behavior. Existing code reads none of these
-- yet; the value is that data accumulating from today onward already
-- carries the markers we'll need for MVP2 / Final-MVP features
-- without a painful backfill later.
--
-- Columns added:
--
--   v2_sessions.source                  TEXT default 'interview'
--     'interview' | 'audit_upload' | 'imported'. Unblocks the
--     snippet-truncation admin orchestration (M1.2) — an audit
--     session needs to be distinguishable from an interview session
--     in admin Tab 1.
--
--   v2_sessions.parent_file_id          UUID NULL
--     FK target for audit-upload sessions: traces back to the
--     user_uploaded_files row the snippets came from. NULL on
--     organic 'interview' sessions.
--
--   recordings.prompt_intent            TEXT NULL
--     'self_assessment_baseline' | 'diagnostic' | 'audit' | NULL.
--     Lets M2.5 (session-2 baseline recording) tag the recording
--     distinctly so downstream pipelines (KPI delta math, snippet
--     extraction) can branch on intent without re-deriving from
--     UX context.
--
--   organization_id                     UUID NULL  (7 tables)
--     B2B-readiness insurance. No FK enforced yet, no behavior
--     change. When the B2B tenant model lands at Final MVP, the
--     migration is a one-day FK + RLS addition, not a multi-day
--     schema sweep.
--     Applied to: user_settings, v2_sessions, recordings,
--     charisma_snippets, stress_snippets, user_consents,
--     user_uploaded_files.
--     NOT applied to auth.users (Supabase-managed; out of bounds).
--
-- New table:
--
--   chat_question_pool                  (empty seed)
--     Schema for M1.3. Empty pool means the existing question-
--     selection logic is unchanged. Admin CRUD endpoints land
--     alongside this migration; the routing service ships in a
--     later commit when content has been seeded.
--
-- Idempotent. Safe to re-run.

-- ── v2_sessions ────────────────────────────────────────────────────

ALTER TABLE v2_sessions
    ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'interview',
    ADD COLUMN IF NOT EXISTS parent_file_id UUID,
    ADD COLUMN IF NOT EXISTS organization_id UUID;

-- Enum-style CHECK on source. Idempotent via DO/EXISTS probe.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'v2_sessions_source_check'
    ) THEN
        ALTER TABLE v2_sessions
            ADD CONSTRAINT v2_sessions_source_check
            CHECK (source IN ('interview', 'audit_upload', 'imported'));
    END IF;
END$$;

COMMENT ON COLUMN v2_sessions.source IS
    'tester-soft-v1 — session origin discriminator. Default '
    '''interview'' covers the existing diagnostic funnel; '
    '''audit_upload'' is created by M1.2 when admin accepts '
    'snippets from a user_uploaded_files row; ''imported'' is '
    'reserved for future bulk-import flows.';

COMMENT ON COLUMN v2_sessions.parent_file_id IS
    'tester-soft-v1 — for audit_upload sessions, links back to '
    'the user_uploaded_files row the snippets were carved from. '
    'NULL on organic interview sessions.';

-- ── recordings ─────────────────────────────────────────────────────

ALTER TABLE recordings
    ADD COLUMN IF NOT EXISTS prompt_intent TEXT,
    ADD COLUMN IF NOT EXISTS organization_id UUID;

COMMENT ON COLUMN recordings.prompt_intent IS
    'tester-soft-v1 — recording intent tag. Set by M2.5 to '
    '''self_assessment_baseline'' on the session-2 free-talk; '
    'else NULL (legacy diagnostic recordings need no tag). '
    'Downstream consumers branch on this for KPI delta math + '
    'snippet-extraction parameter selection.';

-- ── snippet tables ─────────────────────────────────────────────────
-- charisma_snippets already has question_tone (interview funnel,
-- migrations/interview_admin_upgrade.sql line 37) so MVP1 intent
-- tagging at the snippet level is already covered. Only B2B
-- insurance column added here.

ALTER TABLE charisma_snippets
    ADD COLUMN IF NOT EXISTS organization_id UUID;

ALTER TABLE stress_snippets
    ADD COLUMN IF NOT EXISTS organization_id UUID;

-- ── user-scoped tables (B2B insurance) ──────────────────────────────

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS organization_id UUID;

ALTER TABLE user_consents
    ADD COLUMN IF NOT EXISTS organization_id UUID;

ALTER TABLE user_uploaded_files
    ADD COLUMN IF NOT EXISTS organization_id UUID;

-- ── chat_question_pool (M1.3 schema only) ──────────────────────────
-- Router service is in services/question_pool.py and is opt-in:
-- an empty pool falls through to the legacy question-selection
-- code path, so this migration is no-op until content lands.

CREATE TABLE IF NOT EXISTS chat_question_pool (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intent          TEXT NOT NULL,
    text            TEXT NOT NULL,
    weight          INTEGER NOT NULL DEFAULT 100,
    locale          TEXT NOT NULL DEFAULT 'en',
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    position_hint   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      UUID,
    notes           TEXT
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_question_pool_intent_check'
    ) THEN
        ALTER TABLE chat_question_pool
            ADD CONSTRAINT chat_question_pool_intent_check
            CHECK (intent IN ('charisma', 'stress', 'trust', 'post_official'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chat_question_pool_position_check'
    ) THEN
        ALTER TABLE chat_question_pool
            ADD CONSTRAINT chat_question_pool_position_check
            CHECK (position_hint IS NULL OR position_hint IN ('opener', 'mid', 'closer'));
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS chat_question_pool_active_intent_locale_ix
    ON chat_question_pool (intent, locale)
    WHERE active IS TRUE;

COMMENT ON TABLE chat_question_pool IS
    'tester-soft-v1 / M1.3 — extensible question pool for chat '
    'surfaces. Empty pool = legacy question logic. Admin CRUD '
    'endpoints land alongside this migration; the routing '
    'service flips on once content has been seeded.';

NOTIFY pgrst, 'reload schema';
