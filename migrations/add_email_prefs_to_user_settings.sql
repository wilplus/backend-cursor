-- Phase 14: per-user email preferences (publish-results unsubscribe).
--
-- The new PostSessionResultsEmail template includes an unsubscribe
-- footer link that opens /unsubscribe?token=<...>; the unsubscribe
-- handler flips a per-category preference here so future publish-
-- results emails skip this user. RFC 8058 List-Unsubscribe headers
-- on the email itself route to the same flow, so Gmail / Apple
-- "one-click unsubscribe" buttons also land here.
--
-- Shape decisions
-- ---------------
--   email_pref_publish_results — single boolean per category. We
--     considered a generic "marketing_off" mega-flag but per-
--     category gives finer-grained control as more email types
--     get added without a migration each time.
--   unsubscribed_at / source   — minimal audit so support can tell
--     "the user did this through the email link" vs "admin
--     toggled it via dashboard" vs "auto-disabled from bounce".
--
-- All columns are nullable / default TRUE so existing users
-- continue to receive the email until they opt out.
--
-- Idempotent.

ALTER TABLE user_settings
    ADD COLUMN IF NOT EXISTS email_pref_publish_results BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS unsubscribed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS unsubscribed_source TEXT;

COMMENT ON COLUMN user_settings.email_pref_publish_results IS
    'Phase 14 — TRUE (default) means the user receives the publish-'
    'results email when an admin publishes their session results. '
    'FALSE means skip the send. Flipped by /v2/public/unsubscribe '
    '(token-based) or by admin in the dashboard.';
COMMENT ON COLUMN user_settings.unsubscribed_at IS
    'Phase 14 — when the user (or admin) last unsubscribed from the '
    'publish-results email. NULL while the user is still subscribed.';
COMMENT ON COLUMN user_settings.unsubscribed_source IS
    'Phase 14 — origin of the most recent unsubscribe action: '
    '"email_token" (footer link click), "list_unsubscribe" (RFC 8058 '
    'header), "admin" (dashboard toggle), or "system" (bounce auto-'
    'disable).';

NOTIFY pgrst, 'reload schema';
