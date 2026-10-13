-- 0465 · The speaker may leave a WhatsApp number, so "the feedback from
-- your coach is in" can reach them on WhatsApp as well as in the app
-- (founder 2026-10-12, "Add Phone Input for WhatsApp Notifications").
--
-- WHY. The Lounge offers a second footer offer after "Add to home screen":
-- a phone number for WhatsApp. The number is the speaker's own opt-in; the
-- time they gave it is kept so the opt-in can be shown later.
--
-- WHAT.
--   1. `user_settings.whatsapp_phone` (TEXT, E.164 such as +447700900123,
--      NULL = no WhatsApp messages). services/whatsapp_notify.py is the one
--      writer and validates the format before it writes.
--   2. `user_settings.whatsapp_opted_in_at` (TIMESTAMPTZ), stamped when a
--      number is saved, cleared with it.
--   Both columns live on `user_settings`, which the account-deletion purge
--   already deletes (services/data_purge_registry.py), so a deleted
--   account takes its number with it. No new table, no grant change.
--
-- DEPLOY. Nothing sends until WHATSAPP_NOTIFICATIONS=true and the Meta
-- WhatsApp variables are set on the Railway services (see services/whatsapp_notify.py).
--
-- SAFE TWICE. ADD COLUMN IF NOT EXISTS; nothing is dropped or rewritten.

ALTER TABLE public.user_settings
    ADD COLUMN IF NOT EXISTS whatsapp_phone TEXT,
    ADD COLUMN IF NOT EXISTS whatsapp_opted_in_at TIMESTAMPTZ;

COMMENT ON COLUMN public.user_settings.whatsapp_phone IS
    'E.164 number the speaker gave for WhatsApp notifications; NULL = none.';
COMMENT ON COLUMN public.user_settings.whatsapp_opted_in_at IS
    'When the speaker saved their WhatsApp number (their opt-in).';

NOTIFY pgrst, 'reload schema';
