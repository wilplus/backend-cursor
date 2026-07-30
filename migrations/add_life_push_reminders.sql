-- Life Panel — OPT-IN web-push reminders (founder decision 2026-07-30,
-- item 12).
--
-- L-4 ("zero nudges") is AMENDED by explicit founder decision, narrowly: the
-- ONE sanctioned outbound path is a web-push reminder the user turned on
-- themselves, per slot, in the panel settings. Every default in this file is
-- FALSE — a user who never touches the settings receives exactly nothing,
-- which is the same as before this migration existed. Everything else L-4
-- bans stays banned (test_life_panel.py::NoNudgesTests holds the line).
--
-- The slot ladder (founder, extended 2026-07-30): daily morning, daily
-- evening, then the checkout cadence — weekly, monthly, quarterly, yearly,
-- fiveyear, tenyear. The longer cadences deep-link to EXISTING surfaces (the
-- weekly review, the panel home where the horizon strategy documents live);
-- no new views and no new checkout tables. Delivery lives ONLY in
-- services/life_reminders.py; generation (ensure_daily_card /
-- ensure_evening_pass) still contains no delivery code.
--
-- RUN THIS IN THE SUPABASE SQL EDITOR. Idempotent — every statement is
-- IF NOT EXISTS / guarded; re-running is a no-op. Nothing is dropped.
--
-- RLS on every table IN THIS FILE, zero policies, same reasoning as
-- add_life_panel.sql: `anon`/`authenticated` can do nothing; the backend's
-- service-role key serves everything through /v2/life/* behind the consent
-- gate. A push endpoint URL is a capability (anyone holding it can send that
-- browser a message), so these rows are as fence-worthy as the corpus.

-- ═════════════════════════════════════════════════════════════════════════
-- 1. SUBSCRIPTIONS — one row per browser push endpoint
-- ═════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS life_push_subscriptions (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid        NOT NULL,
    -- The push service URL. UNIQUE: re-subscribing the same browser updates
    -- rather than duplicates, and a delivery failure (404/410) deletes by it.
    endpoint   text        NOT NULL UNIQUE,
    p256dh     text        NOT NULL,
    auth       text        NOT NULL,
    user_agent text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS life_push_subscriptions_user_idx
    ON life_push_subscriptions (user_id);

ALTER TABLE life_push_subscriptions ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 2. SETTINGS — the opt-in switches. ALL DEFAULT FALSE (the founder's
--    constraint: OFF unless the user explicitly enables a slot).
-- ═════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS life_reminder_settings (
    user_id           uuid PRIMARY KEY,
    morning_enabled   boolean     NOT NULL DEFAULT false,
    evening_enabled   boolean     NOT NULL DEFAULT false,
    weekly_enabled    boolean     NOT NULL DEFAULT false,
    -- The checkout ladder (founder, 2026-07-30). Same rule as the three
    -- above: OFF until the user flips the switch.
    monthly_enabled   boolean     NOT NULL DEFAULT false,
    quarterly_enabled boolean     NOT NULL DEFAULT false,
    yearly_enabled    boolean     NOT NULL DEFAULT false,
    fiveyear_enabled  boolean     NOT NULL DEFAULT false,
    tenyear_enabled   boolean     NOT NULL DEFAULT false,
    -- Minutes east of UTC for the user's local day (JS: -getTimezoneOffset()).
    -- Used to compute the LOCAL date a reminder is idempotent against.
    tz_offset_minutes int         NOT NULL DEFAULT 0,
    updated_at        timestamptz NOT NULL DEFAULT now()
);

-- Both paths, one file (the add_life_panel.sql precedent): the CREATE above
-- carries the checkout columns for a fresh database; these cover a dev
-- database where an earlier cut of this file may already have run.
ALTER TABLE life_reminder_settings ADD COLUMN IF NOT EXISTS monthly_enabled   boolean NOT NULL DEFAULT false;
ALTER TABLE life_reminder_settings ADD COLUMN IF NOT EXISTS quarterly_enabled boolean NOT NULL DEFAULT false;
ALTER TABLE life_reminder_settings ADD COLUMN IF NOT EXISTS yearly_enabled    boolean NOT NULL DEFAULT false;
ALTER TABLE life_reminder_settings ADD COLUMN IF NOT EXISTS fiveyear_enabled  boolean NOT NULL DEFAULT false;
ALTER TABLE life_reminder_settings ADD COLUMN IF NOT EXISTS tenyear_enabled   boolean NOT NULL DEFAULT false;

ALTER TABLE life_reminder_settings ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 3. LOG — idempotency, not analytics. One row per (user, slot, local day);
--    the unique index is what makes a double-fired cron a no-op.
-- ═════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS life_reminder_log (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    uuid NOT NULL,
    slot       text NOT NULL CHECK (slot IN ('morning', 'evening', 'weekly',
                                             'monthly', 'quarterly', 'yearly',
                                             'fiveyear', 'tenyear')),
    sent_on    date NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS life_reminder_log_user_slot_day_uniq
    ON life_reminder_log (user_id, slot, sent_on);

ALTER TABLE life_reminder_log ENABLE ROW LEVEL SECURITY;

-- ═════════════════════════════════════════════════════════════════════════
-- 4. USER COPY — the founder's check-in lines, per-user editable
--    (founder decision 2026-07-30: "my copy as default, editable")
-- ═════════════════════════════════════════════════════════════════════════
-- The daily check-in's mantra header and distraction question ship with the
-- founder's own strings as defaults (src/lib/life/copy.ts). A user may
-- reword them; NULL means "use the default", so clearing a field is how you
-- get the original line back. Rides in this file because it is the same
-- unapplied migration and there is no existing per-user prefs table in
-- add_life_panel.sql to extend (life_setup holds form state, not
-- preferences). Separate table on purpose — reminders and copy are separate
-- concerns that happen to share a migration, not a row.
CREATE TABLE IF NOT EXISTS life_user_copy (
    user_id             uuid PRIMARY KEY,
    mantra_title        text,
    mantra_question     text,
    distraction_question text,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE life_user_copy ENABLE ROW LEVEL SECURITY;

-- ─────────────────────────────────────────────────────────────────────────
-- POST-CONDITION — RLS actually landed on all four (N1). Raise, so a
-- partial run is a failed run.
-- ─────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    unprotected text;
BEGIN
    SELECT string_agg(c.relname, ', ')
      INTO unprotected
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public'
       AND c.relname IN ('life_push_subscriptions',
                         'life_reminder_settings',
                         'life_reminder_log',
                         'life_user_copy')
       AND NOT c.relrowsecurity;
    IF unprotected IS NOT NULL THEN
        RAISE EXCEPTION 'tables without row level security: %', unprotected;
    END IF;
END $$;
