-- Booking page: a percentage off the first lesson for people who have not
-- had one yet (founder 2026-10-13). 0 = no offer. Additive and idempotent.
ALTER TABLE public.booking_settings
    ADD COLUMN IF NOT EXISTS new_user_discount_pct INTEGER NOT NULL DEFAULT 0;
