-- Booking page: a percentage off the first lesson for people who have not
-- had one yet (founder 2026-10-13). 0 = no offer. Additive and idempotent.
ALTER TABLE public.booking_settings
    ADD COLUMN IF NOT EXISTS new_user_discount_pct INTEGER NOT NULL DEFAULT 0;

-- Booking without paying (founder 2026-10-13, temporary): when on, the page
-- offers "Book without paying" next to the payment button.
ALTER TABLE public.booking_settings
    ADD COLUMN IF NOT EXISTS allow_skip_payment BOOLEAN NOT NULL DEFAULT false;
