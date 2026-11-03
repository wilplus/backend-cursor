-- an_iphone_keeps_its_push_address (push in the iPhone app; founder, the
-- Claude Code chat, 3 November 2026: the coach's feedback and a new chat
-- message, asked after the first feedback; N385, for N365 item 4)
--
-- Where Apple's push service reaches a person's iPhone, so the backend can
-- tell them "The feedback from your coach is in!" (N171) and that someone in
-- their chats wrote (services/push_devices.py).
--
--   push_devices   One row per iPhone address (Apple's device token, hex),
--                  the account it was last given for. environment: which of
--                  Apple's two services answered it ('production', or
--                  'sandbox' for an app run from Xcode), null until the
--                  first push. The row goes with the account.
--
-- A device token lets anyone holding Apple's key for this app send that
-- phone a notification, so the table is the backend's alone: read and written
-- by the service role only; nothing for anon or authenticated. Nothing is
-- sent without the APNs key on Railway (APNS_KEY_ID, APNS_TEAM_ID,
-- APNS_AUTH_KEY); the migration itself needs no environment variable.
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS; nothing is dropped and no
-- row is written, rewritten or removed. One transaction; explicit grants to
-- service_role, as 0505 to 0507.
--
-- Rollback (a new forward migration): leave the table; dropping it is a
-- separate, previewed retention operation.

BEGIN;

CREATE TABLE IF NOT EXISTS public.push_devices (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    token         TEXT NOT NULL UNIQUE,
    platform      TEXT NOT NULL DEFAULT 'ios',
    environment   TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT push_devices_token_shape CHECK (token ~ '^[0-9a-f]{64,200}$'),
    CONSTRAINT push_devices_platform CHECK (platform IN ('ios')),
    CONSTRAINT push_devices_environment CHECK (environment IS NULL OR environment IN ('production', 'sandbox'))
);

CREATE INDEX IF NOT EXISTS push_devices_user_idx ON public.push_devices (user_id);

ALTER TABLE public.push_devices ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.push_devices FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.push_devices TO service_role;

COMMIT;
