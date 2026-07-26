-- RLS SWEEP — enable row level security on every public table (2026-07-25).
--
-- Founder directive: "security is non-negotiable, especially with EU voice and
-- transcript data." Closes the gap documented in docs/RLS-AUDIT.md, raised by
-- the Journal review.
--
-- ── THE EXPOSURE ──────────────────────────────────────────────────────────
-- The FE ships NEXT_PUBLIC_SUPABASE_ANON_KEY inlined into the browser bundle
-- (Next inlines NEXT_PUBLIC_* at compile time), so anyone can read it out of
-- the JS and call PostgREST directly:
--
--     GET https://<project>.supabase.co/rest/v1/<table>?select=*
--          apikey: <anon key lifted from the bundle>
--
-- Supabase's default grants to `anon`/`authenticated` on the public schema make
-- that succeed on any table WITHOUT RLS — including charisma_snippets
-- (per-snippet transcripts), v2_sessions, v2_reports, recording_feelings and
-- user_consents. This path bypasses Flask entirely, so no amount of API-side
-- owner checking defends it. RLS is the only control on it.
--
-- ── WHY THIS IS SAFE ──────────────────────────────────────────────────────
-- Verified before writing (see docs/RLS-AUDIT.md):
--   * the backend connects with SUPABASE_SERVICE_ROLE_KEY (services/db.py),
--     which BYPASSES RLS — the API is unaffected;
--   * the backend never uses the anon key at runtime;
--   * the FE performs NO direct table reads — its only .from() calls are
--     supabase.storage.from(bucket). The single .from("v2_sessions") hit is
--     inside a comment describing a version that now routes through Flask.
--
-- So RLS with ZERO policies is the correct shape: `anon` and `authenticated`
-- can do nothing, the service-role backend keeps full access.
--
-- ── WHY THIS IS DYNAMIC RATHER THAN A FIXED LIST ──────────────────────────
-- It sweeps what the LIVE database actually reports (pg_tables.rowsecurity)
-- instead of a list derived from migration files, which can be stale, can miss
-- a table created in the dashboard, and can name tables that never shipped.
-- Consequence: this is self-healing — re-run it after any future migration and
-- it catches anything that slipped through.
--
-- Guards:
--   * skips tables that ALREADY have RLS (so re-runs are true no-ops);
--   * skips EXTENSION-OWNED tables (pg_depend deptype 'e'); enabling RLS on,
--     say, PostGIS's spatial_ref_sys would break the extension. Only pgcrypto
--     and uuid-ossp are installed today and neither creates tables, but the
--     guard keeps this safe if that changes;
--   * skips anything that is not an ordinary table (views/matviews/foreign
--     tables are not in pg_tables anyway);
--   * RAISE NOTICE per table + a summary, so the run is auditable.
--
-- NO POLICIES ARE CREATED. If a table ever needs genuine end-user access via
-- the anon/authenticated role, add an explicit policy for that table in its own
-- migration — do not disable RLS again.
--
-- ── DRY RUN FIRST (recommended) ───────────────────────────────────────────
-- DDL is transactional in Postgres, so you can see exactly what this would
-- change and then throw it away:
--
--     BEGIN;
--     \i migrations/add_rls_all_public_tables.sql
--     -- read the NOTICE lines: one per table, plus the summary
--     ROLLBACK;          -- nothing changed; re-run with COMMIT when happy
--
-- This file has NOT been executed against any database — there is no local
-- Postgres in the dev environment to validate it against. Do the dry run.

DO $$
DECLARE
    r            record;
    changed_count integer := 0;
    skipped_ext   integer := 0;
BEGIN
    FOR r IN
        SELECT c.oid, c.relname
          FROM pg_class      c
          JOIN pg_namespace  n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public'
           AND c.relkind IN ('r', 'p')  -- ordinary + partitioned tables
           AND c.relrowsecurity = false -- already-enabled tables are skipped
         ORDER BY c.relname
    LOOP
        -- Never touch a table an extension owns.
        IF EXISTS (
            SELECT 1 FROM pg_depend d
             WHERE d.objid = r.oid
               AND d.classid = 'pg_class'::regclass
               AND d.deptype = 'e'
        ) THEN
            skipped_ext := skipped_ext + 1;
            RAISE NOTICE 'RLS sweep: SKIP % (extension-owned)', r.relname;
            CONTINUE;
        END IF;

        EXECUTE format(
            'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', r.relname);
        changed_count := changed_count + 1;
        RAISE NOTICE 'RLS sweep: enabled on %', r.relname;
    END LOOP;

    RAISE NOTICE 'RLS sweep complete: % table(s) changed, % extension-owned skipped',
                 changed_count, skipped_ext;
END $$;


-- ── VERIFY (run this after; it should return ZERO rows) ───────────────────
--
-- SELECT tablename
--   FROM pg_tables
--  WHERE schemaname = 'public' AND rowsecurity = false
--  ORDER BY tablename;
--
-- Cross-check in the dashboard: Advisors → Security Advisor → the
-- "RLS disabled in public" lint should be empty.
--
-- ── CONFIRM THE HOLE IS ACTUALLY CLOSED (optional, end-to-end) ────────────
-- Before: this returned rows. After: it must return [] or a permission error.
--
--   curl -s "https://<project>.supabase.co/rest/v1/charisma_snippets?select=id&limit=1" \
--        -H "apikey: <ANON key>" -H "Authorization: Bearer <ANON key>"
