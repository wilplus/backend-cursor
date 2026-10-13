-- Booking page v1 (founder 2026-10-13): people book a paid 1-on-1 lesson with
-- the admin at willpowerlab.com/book/<slug>.
--
-- Two tables, both backend-only (RLS on, no anon/authenticated grants):
--   booking_settings  one row: the page link, price, hours, buffers, calendar
--                     and meeting links the admin edits at /admin/booking.
--   bookings          one row per booking. A row starts 'held' while the guest
--                     pays on Stripe and becomes 'confirmed' when Stripe says
--                     it is paid. A hold past held_until no longer blocks the
--                     slot, so an abandoned checkout frees itself.
--
-- booking_hold() is the only writer of new rows: it takes a transaction-level
-- advisory lock and refuses a time that overlaps a live booking (with the
-- buffers), so two people paying at once cannot get the same slot.
--
-- Idempotent and additive: IF NOT EXISTS everywhere, nothing dropped.

CREATE TABLE IF NOT EXISTS public.booking_settings (
    id                 SMALLINT PRIMARY KEY DEFAULT 1,
    slug               TEXT NOT NULL DEFAULT 'artur',
    title              TEXT NOT NULL DEFAULT '1-on-1 lesson',
    host_name          TEXT NOT NULL DEFAULT 'Artur Willoński',
    duration_min       INTEGER NOT NULL DEFAULT 60,
    price_cents        INTEGER NOT NULL DEFAULT 12000,
    currency           TEXT NOT NULL DEFAULT 'usd',
    buffer_before_min  INTEGER NOT NULL DEFAULT 15,
    buffer_after_min   INTEGER NOT NULL DEFAULT 15,
    notice_hours       INTEGER NOT NULL DEFAULT 12,
    horizon_days       INTEGER NOT NULL DEFAULT 30,
    timezone           TEXT NOT NULL DEFAULT 'Europe/Warsaw',
    weekly_hours       JSONB NOT NULL DEFAULT
        '{"1":[["09:00","17:00"]],"2":[["09:00","17:00"]],"3":[["09:00","17:00"]],"4":[["09:00","17:00"]],"5":[["09:00","13:00"]]}'::jsonb,
    calendar_ics_url   TEXT NOT NULL DEFAULT '',
    meet_url           TEXT NOT NULL DEFAULT '',
    enabled            BOOLEAN NOT NULL DEFAULT false,
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT booking_settings_single_row CHECK (id = 1),
    CONSTRAINT booking_settings_slug_check CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
    CONSTRAINT booking_settings_duration_check CHECK (duration_min BETWEEN 15 AND 240),
    CONSTRAINT booking_settings_price_check CHECK (price_cents >= 0),
    CONSTRAINT booking_settings_buffers_check
        CHECK (buffer_before_min BETWEEN 0 AND 240 AND buffer_after_min BETWEEN 0 AND 240),
    CONSTRAINT booking_settings_window_check
        CHECK (notice_hours BETWEEN 0 AND 720 AND horizon_days BETWEEN 1 AND 365),
    CONSTRAINT booking_settings_hours_check CHECK (jsonb_typeof(weekly_hours) = 'object')
);

INSERT INTO public.booking_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.bookings (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    start_at           TIMESTAMPTZ NOT NULL,
    end_at             TIMESTAMPTZ NOT NULL,
    status             TEXT NOT NULL DEFAULT 'held',
    held_until         TIMESTAMPTZ,
    guest_name         TEXT NOT NULL,
    guest_email        TEXT NOT NULL,
    guest_timezone     TEXT NOT NULL DEFAULT 'UTC',
    note               TEXT NOT NULL DEFAULT '',
    title              TEXT NOT NULL,
    price_cents        INTEGER NOT NULL,
    currency           TEXT NOT NULL,
    meet_url           TEXT NOT NULL DEFAULT '',
    stripe_session_id  TEXT UNIQUE,
    confirmed_at       TIMESTAMPTZ,
    emails_sent_at     TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT bookings_status_check CHECK (status IN ('held', 'confirmed', 'cancelled')),
    CONSTRAINT bookings_time_check CHECK (end_at > start_at)
);

CREATE INDEX IF NOT EXISTS bookings_start_idx ON public.bookings (start_at);

ALTER TABLE public.booking_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bookings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.booking_settings FROM anon, authenticated;
REVOKE ALL ON TABLE public.bookings FROM anon, authenticated;

-- Hold a slot for a guest who is about to pay. Returns the new booking id, or
-- NULL when the time overlaps a confirmed booking or an unexpired hold
-- (each side widened by the buffers).
CREATE OR REPLACE FUNCTION public.booking_hold(
    p_start_at        TIMESTAMPTZ,
    p_end_at          TIMESTAMPTZ,
    p_buffer_before   INTEGER,
    p_buffer_after    INTEGER,
    p_held_until      TIMESTAMPTZ,
    p_guest_name      TEXT,
    p_guest_email     TEXT,
    p_guest_timezone  TEXT,
    p_note            TEXT,
    p_title           TEXT,
    p_price_cents     INTEGER,
    p_currency        TEXT,
    p_meet_url        TEXT
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_id UUID;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('public.bookings'));

    IF EXISTS (
        SELECT 1 FROM public.bookings b
        WHERE (b.status = 'confirmed'
               OR (b.status = 'held' AND b.held_until > now()))
          AND b.start_at < p_end_at + make_interval(mins => p_buffer_after)
          AND b.end_at > p_start_at - make_interval(mins => p_buffer_before)
    ) THEN
        RETURN NULL;
    END IF;

    INSERT INTO public.bookings (
        start_at, end_at, status, held_until, guest_name, guest_email,
        guest_timezone, note, title, price_cents, currency, meet_url
    ) VALUES (
        p_start_at, p_end_at, 'held', p_held_until, p_guest_name, p_guest_email,
        p_guest_timezone, p_note, p_title, p_price_cents, p_currency, p_meet_url
    ) RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;

REVOKE ALL ON FUNCTION public.booking_hold(
    TIMESTAMPTZ, TIMESTAMPTZ, INTEGER, INTEGER, TIMESTAMPTZ, TEXT, TEXT, TEXT,
    TEXT, TEXT, INTEGER, TEXT, TEXT
) FROM PUBLIC, anon, authenticated;
