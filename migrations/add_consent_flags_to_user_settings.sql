-- Phase Single-Slot-Chat — four chat-surface consent flags.
--
-- Backs GET / PUT /v2/user/sharing-consent. Each user passes through
-- four YesNoPills consent moments during the chat funnel:
--   1. Microphone permission              → mic_consent
--   2. Share snippets with the coach      → share_consent
--   3. Receive weekly progress emails     → email_consent
--   4. Accept Terms & Privacy             → terms_consent
--
-- NULL = "not yet answered" → frontend shows the prompt for that
--        slot.
-- TRUE / FALSE = "answered" with that opt-in value.
--
-- has_answered (computed by the route handler, not a column) =
-- "any of the four is non-null". Frontend uses it as a coarse
-- "has the user been through the funnel at all" check; per-moment
-- gating uses the individual fields.
--
-- These are distinct from the user_consents table — that is the
-- immutable GDPR audit ledger written once at signup. These four
-- flags are the per-chat-slot preference state, intended to be
-- toggled by the user via the consent slots in the chat. The
-- terms_consent flag here lives alongside (not in place of) the
-- user_consents audit row.
--
-- Run in Supabase SQL Editor. Idempotent.

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'user_settings'
      AND column_name = 'mic_consent'
  ) THEN
    ALTER TABLE user_settings
      ADD COLUMN mic_consent BOOLEAN DEFAULT NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'user_settings'
      AND column_name = 'share_consent'
  ) THEN
    ALTER TABLE user_settings
      ADD COLUMN share_consent BOOLEAN DEFAULT NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'user_settings'
      AND column_name = 'email_consent'
  ) THEN
    ALTER TABLE user_settings
      ADD COLUMN email_consent BOOLEAN DEFAULT NULL;
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'user_settings'
      AND column_name = 'terms_consent'
  ) THEN
    ALTER TABLE user_settings
      ADD COLUMN terms_consent BOOLEAN DEFAULT NULL;
  END IF;
END $$;

COMMENT ON COLUMN user_settings.mic_consent IS
  'Chat-surface consent slot 1 — microphone permission. NULL = '
  'not yet answered (FE shows the prompt). TRUE/FALSE = answered. '
  'Distinct from the browser-level mediaDevices permission, which '
  'is OS-managed; this is the in-app user preference recorded '
  'when they tap the YesNoPills.';

COMMENT ON COLUMN user_settings.share_consent IS
  'Chat-surface consent slot 2 — share recorded snippets with the '
  'human coach. NULL = not yet answered. TRUE/FALSE = answered. '
  'On the GET /v2/user/sharing-consent response this value is '
  'ALSO echoed as the legacy `opt_in` field for back-compat '
  'until the FE migrates.';

COMMENT ON COLUMN user_settings.email_consent IS
  'Chat-surface consent slot 3 — receive weekly progress emails. '
  'NULL = not yet answered. TRUE/FALSE = answered. Separate from '
  'transactional emails (always sent for legal / safety reasons).';

COMMENT ON COLUMN user_settings.terms_consent IS
  'Chat-surface consent slot 4 — accept Terms & Privacy via the '
  'in-chat YesNoPills. NULL = not yet answered. TRUE = accepted. '
  'FALSE = explicitly declined (frontend should gate further use). '
  'This is NOT a substitute for the user_consents GDPR audit '
  'ledger; both should be populated when the user accepts.';
