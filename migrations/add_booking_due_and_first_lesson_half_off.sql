-- Founder 2026-10-13: while payment is off, a booking still shows what the
-- person will pay (their price at booking time, e.g. the first-lesson
-- discount), and first-time people get 50% off. Additive; safe to re-run.
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS due_cents INTEGER;

UPDATE public.booking_settings SET new_user_discount_pct = 50
WHERE COALESCE(new_user_discount_pct, 0) = 0;
