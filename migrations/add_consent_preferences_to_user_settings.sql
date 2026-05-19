-- Migration: per-user runtime consent preferences (mic / share / email).
--
-- Three boolean preference columns + their set-at timestamps on
-- user_settings, driving the unified GET/PUT /v2/user/consent endpoint.
-- Terms-of-Service consent is NOT stored here — it remains in the
-- immutable user_consents ledger (one row per accepted version, for
-- compliance audit). The new endpoint READS that ledger to expose
-- terms_consent alongside the three runtime preferences below.
--
-- NULL semantics:
--   - NULL = the user has never been asked / has not answered this
--     prompt yet. The frontend uses NULL to decide whether to show
--     the consent moment at all.
--   - TRUE / FALSE = the user has explicitly answered. The endpoint
--     reports has_answered=true once any of the three is non-NULL
--     (or once the user has accepted the current terms version).
--
-- Timestamps:
--   - *_set_at records WHEN the preference was last toggled. Useful
--     for "you opted in to mic on <date>" UX and for audit on
--     potential GDPR data-subject requests. Updated every time the
--     preference value changes (including TRUE → FALSE).

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS mic_consent_preference   BOOLEAN     DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS mic_consent_set_at       TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS share_consent_preference BOOLEAN     DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS share_consent_set_at     TIMESTAMPTZ DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS email_consent_preference BOOLEAN     DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS email_consent_set_at     TIMESTAMPTZ DEFAULT NULL;

COMMENT ON COLUMN user_settings.mic_consent_preference IS
    'TRUE/FALSE = user answered the mic-access consent prompt. '
    'NULL = never asked. Drives the /v2/user/consent endpoint.';

COMMENT ON COLUMN user_settings.share_consent_preference IS
    'TRUE/FALSE = user answered the share-voice-clone consent prompt. '
    'NULL = never asked. Drives the /v2/user/consent endpoint.';

COMMENT ON COLUMN user_settings.email_consent_preference IS
    'TRUE/FALSE = user answered the email-notifications consent prompt. '
    'NULL = never asked. Drives the /v2/user/consent endpoint. '
    'Distinct from email_pref_publish_results which is a per-category '
    'unsubscribe (RFC 8058 List-Unsubscribe path) — this column is the '
    'top-level "do you want any email at all" toggle.';
