-- willab beta — training_labels (design §14, contract §3.9b — PRIVATE lane).
--
-- The coach's per-snippet direction appraisal, captured at publish. This
-- is the classifier's ONLY training signal this phase (cold start: no
-- model → coach labels from scratch; steady state: accept/override a
-- pre-fill — the override is the high-value signal).
--
-- Schema (direction-v1, FE-locked):
--   value          'threat' | 'ambiguous' | 'challenge' (3-class appraisal)
--   schema_version 'direction-v1' (migration-ready to the 28→12-16
--                  scenario protocol later — augments, never replaces)
--   was_pre_filled / was_overridden — accept-vs-override is the signal;
--                  kept as DISTINCT booleans (never collapsed)
--
-- SPLIT-SINK (§2 / AC-9), enforced by storage + access:
--   * NEVER user-visible. No user endpoint reads this table.
--   * NEVER written into insights_payload, and the strong/to-work-on
--     tag is NEVER derived from this value (independent axes — auto-
--     deriving would leak the private appraisal).
--   * RLS denies all end-user access (no user policy); only the Flask
--     service-role (which bypasses RLS) reads/writes it.
--
-- Idempotent: UNIQUE(session_id, snippet_id) — re-publish updates the
-- current label for a snippet rather than duplicating.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS training_labels (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id     UUID NOT NULL,
    snippet_id     UUID NOT NULL,
    schema_version TEXT NOT NULL DEFAULT 'direction-v1',
    value          TEXT NOT NULL,              -- 'threat'|'ambiguous'|'challenge'
    labeled_by     UUID,                       -- the coach/admin user_id
    labeled_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    was_pre_filled BOOLEAN NOT NULL DEFAULT FALSE,
    was_overridden BOOLEAN NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (session_id, snippet_id)
);

CREATE INDEX IF NOT EXISTS training_labels_session_ix
    ON training_labels (session_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'training_labels_value_check'
    ) THEN
        ALTER TABLE training_labels ADD CONSTRAINT training_labels_value_check
            CHECK (value IN ('threat', 'ambiguous', 'challenge'));
    END IF;
END$$;

-- RLS ON with NO user policy → default-deny for any end-user JWT. The
-- service-role (Flask) bypasses RLS. This is the storage-level guarantee
-- that the private appraisal can never reach a user (AC-9), even if a
-- future endpoint bug tried to read it with a user token.
ALTER TABLE training_labels ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE training_labels IS
    'willab beta §14 — PRIVATE per-snippet direction appraisal '
    '(direction-v1: threat|ambiguous|challenge), captured at publish. '
    'Classifier training signal only. NEVER user-visible (RLS deny-all, '
    'no user policy), NEVER in insights_payload, tag never derived from '
    'it (split-sink §2/AC-9). UNIQUE(session_id,snippet_id) idempotent.';

NOTIFY pgrst, 'reload schema';
