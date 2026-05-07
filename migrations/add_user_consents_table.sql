-- Migration: user_consents
-- Stores a timestamped, immutable record of each user's acceptance of the
-- Terms of Service and Privacy Policy.
--
-- This table is written once at account-creation time and is never updated
-- (only INSERTed). If terms are updated in the future, a new row is added
-- with a higher `terms_version` value so the full acceptance history is
-- preserved for compliance audits.
--
-- The `ip_address` and `user_agent` fields are captured from the HTTP request
-- at registration time and are stored solely for GDPR compliance evidence.

CREATE TABLE IF NOT EXISTS user_consents (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    terms_accepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Semantic version of the Terms/Privacy Policy the user accepted.
    -- Increment this string whenever the legal documents are materially updated.
    terms_version   TEXT        NOT NULL DEFAULT '1.0',
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- One row per version per user (idempotent upsert key)
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_consents_user_version
    ON user_consents (user_id, terms_version);

-- Admin queries: "show me all users who accepted version X"
CREATE INDEX IF NOT EXISTS idx_user_consents_version
    ON user_consents (terms_version);

-- Admin queries: "show me consent history for user Y"
CREATE INDEX IF NOT EXISTS idx_user_consents_user_id
    ON user_consents (user_id);

COMMENT ON TABLE user_consents IS
    'Immutable GDPR consent ledger. One row per user per terms version. '
    'Never UPDATE existing rows — only INSERT new ones when terms change.';

COMMENT ON COLUMN user_consents.terms_version IS
    'Semver string matching the "Last updated" date in the published legal docs '
    '(e.g. "1.0" = Terms dated 7 May 2026). Bump when docs are materially revised.';

COMMENT ON COLUMN user_consents.ip_address IS
    'IPv4/IPv6 address of the registering client. Stored for compliance audit '
    'evidence only. Processed under GDPR Art. 6(1)(c) (legal obligation).';
