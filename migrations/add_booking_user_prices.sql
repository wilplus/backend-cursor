-- Booking page: a price per person and tokens with every lesson
-- (founder 2026-10-13).
--
--   booking_settings.bonus_tokens   tokens each paid lesson adds to the
--                                   booker's account (default 40,000)
--   booking_user_prices             the admin's per-person lesson price,
--                                   set from /admin/tokens
--   bookings.user_id                booking now needs a signed-in account
--   bookings.list_price_cents       the price everyone else pays, so a
--                                   discount is visible afterwards
--   bookings.bonus_tokens           tokens promised at checkout
--   bookings.tokens_granted_at      when they reached the account
--
-- Idempotent and additive: IF NOT EXISTS everywhere, nothing dropped.

ALTER TABLE public.booking_settings
    ADD COLUMN IF NOT EXISTS bonus_tokens INTEGER NOT NULL DEFAULT 40000;

ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS user_id UUID;
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS list_price_cents INTEGER;
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS bonus_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE public.bookings ADD COLUMN IF NOT EXISTS tokens_granted_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS public.booking_user_prices (
    user_id      UUID PRIMARY KEY,
    price_cents  INTEGER NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT booking_user_prices_price_check CHECK (price_cents >= 0)
);

ALTER TABLE public.booking_user_prices ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.booking_user_prices FROM anon, authenticated;
