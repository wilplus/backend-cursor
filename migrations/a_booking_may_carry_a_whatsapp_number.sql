-- a_booking_may_carry_a_whatsapp_number
--
-- A booking may carry the guest's WhatsApp number (founder 2026-10-25, N144).
-- The booking form asks for it, optionally; the confirmation of the time and
-- a reminder 1 hour before are sent there.
--
--   bookings.guest_whatsapp             the number in E.164 (+48600100200),
--                                       or NULL when the guest left none
--   bookings.whatsapp_reminder_sent_at  when the reminder was claimed, so a
--                                       cron that fires twice sends it once
--
-- Closing an account deletes the booking, or wipes the number from a paid
-- lesson's accounting record with the name and the email
-- (services/booking.erase_for_user).
--
-- Deploy order: this runs before the code that writes the columns (Railway's
-- pre-deploy migration step). The code only writes guest_whatsapp when a
-- number was given, so a booking without one never depends on it.
--
-- Idempotent + additive, per the standing constraint: safe to re-run.

ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS guest_whatsapp TEXT;
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS whatsapp_reminder_sent_at TIMESTAMPTZ;
