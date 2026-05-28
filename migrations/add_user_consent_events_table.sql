-- Migration: user_consent_events
-- Append-only GDPR audit ledger for per-flip consent changes.
--
-- WHY THIS IS DISTINCT FROM user_consents
-- ---------------------------------------
-- ``user_consents`` is a single-row-per-(user, terms_version) record
-- of TOS / Privacy Policy acceptance. Idempotent upsert; immutable
-- once written. That table answers: "did this user accept v1.0 of
-- the terms, and when?".
--
-- ``user_consent_events`` (this table) is an append-only event log
-- of every per-toggle consent change — share_consent, mic_consent,
-- email_consent, terms_consent. Each PUT to /v2/user/sharing-
-- consent that actually changes a field appends one row here per
-- changed field. Yes flips, no flips, re-flips: all captured.
-- Answers: "show me everything user X ever clicked on the consent
-- UI, with timestamps and request metadata".
--
-- Per task 8 / FE handoff confirmation (option A on the
-- per-PUT-ledger question + option A2 on the schema decision —
-- new dedicated table, no destructive change to user_consents).
--
-- GDPR posture: stronger than current-state-only because a
-- disputed "I never agreed to share my data" claim can be
-- answered with a concrete row showing the user_id + the
-- consent_type + the bool + the timestamp + the request IP.
--
-- Idempotent migration.

CREATE TABLE IF NOT EXISTS user_consent_events (
    id              UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID         NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    -- Which consent flag changed. Matches the four fields the
    -- /v2/user/sharing-consent endpoint accepts.
    consent_type    TEXT         NOT NULL
        CHECK (consent_type IN ('mic_consent', 'share_consent',
                                'email_consent', 'terms_consent')),
    -- The value the user set it to. NULL is permitted in the
    -- column for the rare case where a future endpoint clears a
    -- consent back to "unanswered" — today's PUT only writes
    -- TRUE/FALSE so production rows will be one of those.
    consent_value   BOOLEAN,
    -- When the user clicked. Distinct from created_at (which the
    -- DB stamps automatically) so a future bulk-import / backfill
    -- can preserve the original timestamp without losing the
    -- "when did this row land in our DB" audit trail.
    set_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- "Show me every consent event for user X, newest first" —
-- the common audit query.
CREATE INDEX IF NOT EXISTS idx_user_consent_events_user_set_at
    ON user_consent_events (user_id, set_at DESC);

-- "Show me every share_consent flip on a given date" — bulk
-- audit / GDPR data-subject access response.
CREATE INDEX IF NOT EXISTS idx_user_consent_events_type_set_at
    ON user_consent_events (consent_type, set_at DESC);

COMMENT ON TABLE user_consent_events IS
    'Append-only GDPR audit ledger for per-toggle consent flips. '
    'Distinct from user_consents (which is a TOS/Privacy '
    'acceptance record). Every successful PUT to /v2/user/sharing-'
    'consent that changes a field appends one row here PER '
    'changed field. Never UPDATE rows; only INSERT.';

COMMENT ON COLUMN user_consent_events.consent_type IS
    'Which consent flag changed. Enum CHECK matches the four '
    'fields the FE-facing endpoint accepts.';

COMMENT ON COLUMN user_consent_events.consent_value IS
    'The value the user set it to (TRUE = opted in, FALSE = '
    'opted out). NULL reserved for a future "clear to unanswered" '
    'endpoint that does not exist today.';

COMMENT ON COLUMN user_consent_events.set_at IS
    'When the user clicked (server clock). Distinct from '
    'created_at so a future backfill can preserve the original '
    'click time without losing the DB-insertion audit trail.';

COMMENT ON COLUMN user_consent_events.ip_address IS
    'Client IP at click time (best-effort via X-Forwarded-For). '
    'Stored for GDPR audit evidence only.';

NOTIFY pgrst, 'reload schema';
