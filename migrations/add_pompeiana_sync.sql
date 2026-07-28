-- Pompeiana — cross-device novena state (founder 2026-07-27). The Pompeian
-- rosary PWA moves behind the WillpowerLab login, on its own domain, and a
-- user's progress follows them across devices.
--
-- WHY THIS LIVES IN THE WILLAB REPO: Pompeiana signs in against the SAME
-- Supabase project that backs willab (routes/auth.py is a passthrough to
-- supabase.auth, and auth.py verifies against that project's JWKS), so these
-- tables share a database with every willab table. The schema therefore
-- belongs in willab's review path even though no willab code reads it.
--
-- WHY THESE TABLES HAVE POLICIES AND THE WILLAB TABLES DO NOT: every other
-- table here is service-role only (RLS on, no policy) because the Flask route
-- owner-gates the request. Pompeiana is a static PWA with NO SERVER — it holds
-- the public anon key and talks to PostgREST directly, so the policies below
-- ARE the access control. Without them, any logged-in willab user could read
-- every user's rows with nothing but the anon key.
--
-- NO DELETE POLICY, on purpose: a novena's progress must not be deletable by
-- the client. "Start over" is an UPDATE to a fresh run_id (see the FE's
-- furthest-progress-wins rule), never a DELETE.
--
-- Idempotent — safe to re-run. Additive only: no drops, including no policy
-- drops (the DO-block guard is the house pattern, cf.
-- add_strong_sides_library_table.sql).

-- ── 1. Novena progress ───────────────────────────────────────────────────
-- ONE row per user (user_id is the PK), so two devices racing is a
-- single-row conflict rather than duplicate rows, and the client's
-- `Prefer: resolution=merge-duplicates` upsert needs no conflict target.
--
-- `state` holds the app's existing localStorage blob plus the two fields the
-- conflict rule needs:
--   { run_id, started_at, day, step_index, rep, language, ... }
-- Progress is compared as [day, step_index, rep] WITHIN a run_id, so a stale
-- device can never drag a user backwards mid-novena; a newer started_at wins
-- ACROSS runs, so novena #2 at day 1 beats finished novena #1 at day 54.
-- The server does not enforce that — it is the client's rule — but the shape
-- is why `state` is jsonb rather than columns.
CREATE TABLE IF NOT EXISTS pompeiana_state (
    user_id    UUID PRIMARY KEY
               REFERENCES auth.users (id) ON DELETE CASCADE
               DEFAULT auth.uid(),
    state      JSONB       NOT NULL DEFAULT '{}'::JSONB,
    -- Client-sent on write (PostgREST upsert does not re-run the default).
    -- DIAGNOSTIC ONLY — the conflict rule reads `state`, never this column,
    -- so a device with a wrong clock cannot win by lying about the time.
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE pompeiana_state ENABLE ROW LEVEL SECURITY;

-- GRANTS ARE SEPARATE FROM RLS, and both are required. A policy filters which
-- ROWS a role may touch; it grants no access to the TABLE. With policies but
-- no grant, every PostgREST call fails "permission denied for table" — which
-- is how this is normally discovered, in production, on every request.
-- Supabase's default privileges usually cover this implicitly; stating it
-- explicitly means the migration does not depend on that setup being intact,
-- and it documents the intended privilege set.
--
-- `anon` gets NOTHING, on purpose: the founder chose a HARD LOGIN GATE
-- (2026-07-27), so an unauthenticated caller has no business reaching these
-- tables at all. No DELETE either — see the no-delete-policy note above.
GRANT SELECT, INSERT, UPDATE ON pompeiana_state TO authenticated;
REVOKE ALL ON pompeiana_state FROM anon;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'pompeiana_state'
          AND policyname = 'pompeiana_state_owner_select'
    ) THEN
        CREATE POLICY pompeiana_state_owner_select ON pompeiana_state
            FOR SELECT USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'pompeiana_state'
          AND policyname = 'pompeiana_state_owner_insert'
    ) THEN
        CREATE POLICY pompeiana_state_owner_insert ON pompeiana_state
            FOR INSERT WITH CHECK (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'pompeiana_state'
          AND policyname = 'pompeiana_state_owner_update'
    ) THEN
        CREATE POLICY pompeiana_state_owner_update ON pompeiana_state
            FOR UPDATE USING (auth.uid() = user_id)
                       WITH CHECK (auth.uid() = user_id);
    END IF;
END$$;

COMMENT ON TABLE pompeiana_state IS
    'Pompeiana novena progress, one row per user, synced across devices. '
    'Client-facing via the anon key — the RLS policies are the access '
    'control, not a Flask route.';

-- ── 2. The user's pasted scripture ───────────────────────────────────────
-- Pompeiana ships scripture REFERENCES only; the user pastes their own
-- translation. Founder 2026-07-27: that syncs across devices too.
--
-- A SEPARATE TABLE, not a key inside `state`, because the access pattern is
-- the opposite: 20 mysteries x 10 languages of prose, written rarely and read
-- once at boot, versus a progress blob rewritten on every bead tap. Folding
-- it into `state` would mean re-sending all of it on each tap and growing one
-- row without bound.
CREATE TABLE IF NOT EXISTS pompeiana_scripture (
    user_id    UUID NOT NULL
               REFERENCES auth.users (id) ON DELETE CASCADE
               DEFAULT auth.uid(),
    -- Keys from the app's own data package (mysteries.json / languages.json).
    -- TEXT, not an enum or FK: the data package is the source of truth and
    -- ships with the client, so the database must not need a migration when
    -- a language or mystery is added there.
    mystery_id TEXT NOT NULL,
    language   TEXT NOT NULL,
    text       TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, mystery_id, language)
);

-- No extra index: the PK's leading column is user_id, so "everything for this
-- user" (the only read this table serves) is already a prefix scan.

ALTER TABLE pompeiana_scripture ENABLE ROW LEVEL SECURITY;

-- Same split as above: the grant opens the table, the policies scope the rows.
GRANT SELECT, INSERT, UPDATE ON pompeiana_scripture TO authenticated;
REVOKE ALL ON pompeiana_scripture FROM anon;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'pompeiana_scripture'
          AND policyname = 'pompeiana_scripture_owner_select'
    ) THEN
        CREATE POLICY pompeiana_scripture_owner_select ON pompeiana_scripture
            FOR SELECT USING (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'pompeiana_scripture'
          AND policyname = 'pompeiana_scripture_owner_insert'
    ) THEN
        CREATE POLICY pompeiana_scripture_owner_insert ON pompeiana_scripture
            FOR INSERT WITH CHECK (auth.uid() = user_id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'pompeiana_scripture'
          AND policyname = 'pompeiana_scripture_owner_update'
    ) THEN
        CREATE POLICY pompeiana_scripture_owner_update ON pompeiana_scripture
            FOR UPDATE USING (auth.uid() = user_id)
                       WITH CHECK (auth.uid() = user_id);
    END IF;
END$$;

COMMENT ON TABLE pompeiana_scripture IS
    'The user''s own pasted scripture text, per mystery per language. '
    'Separate from pompeiana_state because it is written rarely and read at '
    'boot, the opposite pattern from novena progress.';

-- ── Verification (run as TWO different signed-in users, not service-role) ──
--   select * from pg_policies where tablename like 'pompeiana%';   -- 6 rows
--   -- as user A, with the ANON key + A's JWT:
--   select * from pompeiana_state;      -- exactly A's row, never B's
--   -- with no Authorization header:
--   select * from pompeiana_state;      -- zero rows, not the table
-- A policy that is present but wrong looks identical to a correct one until
-- it is tested with a second real user. Do not skip that step.
--
-- Rollback (manual):
--   DROP TABLE IF EXISTS pompeiana_scripture;
--   DROP TABLE IF EXISTS pompeiana_state;
