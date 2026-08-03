-- FUNCTION GRANT SWEEP — revoke anon/authenticated EXECUTE on public functions.
--
-- The companion to add_rls_all_public_tables.sql (2026-07-25), for the door
-- that sweep does not cover.
--
-- ─────────────────────────────────────────────────────────────────────────
-- WHY THIS EXISTS
-- ─────────────────────────────────────────────────────────────────────────
-- docs/RLS-AUDIT.md closed the TABLE exposure: anyone can lift
-- NEXT_PUBLIC_SUPABASE_ANON_KEY out of the browser bundle and call PostgREST
-- directly, and RLS is the only control on that path. That sweep enabled RLS
-- on every public table.
--
-- RLS is table-level. It says nothing about FUNCTIONS, and PostgREST publishes
-- every function in the exposed schema at
--
--     POST https://<project>.supabase.co/rest/v1/rpc/<name>
--
-- Two Postgres defaults make that dangerous the moment anyone writes one:
--
--   1. CREATE FUNCTION grants EXECUTE to PUBLIC. Not to the owner — to
--      everyone. You have to take it away explicitly.
--   2. Supabase's default privileges additionally grant anon / authenticated
--      on functions in `public`, so even revoking from PUBLIC alone can leave
--      a direct grant behind.
--
-- Until 2026-08-03 this repo had ZERO functions, so the surface did not exist
-- and nobody had to think about it. migrations/add_token_charge_rpc.sql is the
-- first one, and it moves money. This file makes the lockdown a property of
-- the database rather than a thing each new migration has to remember —
-- the same reasoning that made the RLS sweep dynamic instead of a fixed list.
--
-- ─────────────────────────────────────────────────────────────────────────
-- WHAT IT DOES / DOES NOT TOUCH
-- ─────────────────────────────────────────────────────────────────────────
-- Revokes ALL (i.e. EXECUTE) from PUBLIC, anon and authenticated on every
-- function and procedure owned by this project in the `public` schema.
--
-- Guards:
--   * skips EXTENSION-OWNED routines (pg_depend deptype 'e'). Revoking EXECUTE
--     on, say, pgcrypto's gen_random_uuid() would break any DEFAULT that calls
--     it for a non-owner role. Only pgcrypto and uuid-ossp are installed today;
--     the guard survives that changing.
--   * skips aggregate and window routines (prokind), which are not RPC
--     endpoints and whose grants belong to whatever created them.
--   * re-runs are true no-ops — REVOKE on an already-revoked privilege is
--     silent and free. Self-healing: run it after any future migration and it
--     catches whatever slipped through. **You have to actually re-run it** —
--     see the default-privileges section at the bottom for why nothing at the
--     database level can do this for you.
--   * RAISE NOTICE per routine plus a summary, so the run is auditable.
--
-- It does NOT grant anything. service_role is unaffected — it is a superuser-
-- adjacent role that bypasses these grants, and the backend connects with
-- SUPABASE_SERVICE_ROLE_KEY, so the API keeps working. Any function that
-- genuinely needs end-user execution gets an explicit
-- `GRANT EXECUTE ... TO authenticated` in its OWN migration, written
-- deliberately — the same rule as "add a policy, do not disable RLS".
--
-- ─────────────────────────────────────────────────────────────────────────
-- PREVIEW FIRST (read-only, changes nothing)
-- ─────────────────────────────────────────────────────────────────────────
--   SELECT n.nspname, p.proname,
--          pg_get_function_identity_arguments(p.oid) AS args,
--          has_function_privilege('anon',          p.oid, 'EXECUTE') AS anon,
--          has_function_privilege('authenticated', p.oid, 'EXECUTE') AS authed
--     FROM pg_proc p
--     JOIN pg_namespace n ON n.oid = p.pronamespace
--    WHERE n.nspname = 'public'
--      AND p.prokind IN ('f', 'p')
--      AND NOT EXISTS (SELECT 1 FROM pg_depend d
--                       WHERE d.objid = p.oid AND d.deptype = 'e')
--    ORDER BY 2;
--
-- After the run, the anon/authed columns must both be false for every row.
--
-- Run: Supabase → SQL Editor → paste → Run (single transaction; a failure
-- applies nothing).

DO $$
DECLARE
    rec        record;
    role_name  text;
    n_touched  int := 0;
    n_skipped  int := 0;
BEGIN
    FOR rec IN
        SELECT p.oid,
               p.proname,
               pg_get_function_identity_arguments(p.oid) AS args,
               EXISTS (SELECT 1 FROM pg_depend d
                        WHERE d.objid = p.oid AND d.deptype = 'e') AS is_ext
          FROM pg_proc p
          JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public'
           AND p.prokind IN ('f', 'p')      -- functions + procedures only
         ORDER BY p.proname
    LOOP
        IF rec.is_ext THEN
            n_skipped := n_skipped + 1;
            RAISE NOTICE 'SKIP  public.%(%) — extension-owned',
                         rec.proname, rec.args;
            CONTINUE;
        END IF;

        EXECUTE format('REVOKE ALL ON FUNCTION public.%I(%s) FROM PUBLIC',
                       rec.proname, rec.args);

        FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                EXECUTE format(
                    'REVOKE ALL ON FUNCTION public.%I(%s) FROM %I',
                    rec.proname, rec.args, role_name);
            END IF;
        END LOOP;

        n_touched := n_touched + 1;
        RAISE NOTICE 'LOCK  public.%(%) — EXECUTE revoked from PUBLIC/anon/authenticated',
                     rec.proname, rec.args;
    END LOOP;

    RAISE NOTICE '── function grant sweep: % locked, % skipped (extension-owned)',
                 n_touched, n_skipped;
END $$;

-- ── Default privileges: a PARTIAL backstop. Read this before trusting it. ──
--
-- ⚠️ ALTER DEFAULT PRIVILEGES CANNOT STOP THE NEXT FUNCTION FROM BEING
-- WORLD-CALLABLE. This was measured on PostgreSQL 16.13, not assumed:
--
--     ALTER DEFAULT PRIVILEGES IN SCHEMA public
--         REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;   -- silently does NOTHING
--
-- ALTER DEFAULT PRIVILEGES can only remove privileges that were themselves
-- granted through ALTER DEFAULT PRIVILEGES. `EXECUTE TO PUBLIC` on a new
-- function is a BUILT-IN default, and pg_default_acl has no way to record its
-- absence — the stored row is MERGED with the built-in defaults at CREATE
-- time, so PUBLIC comes back every time. Four variants were tried (revoke
-- first, revoke last, one combined statement, and grant-to-PUBLIC-then-revoke
-- to try to materialise the entry); all four produced a new function with
-- `=X/postgres` — PUBLIC=EXECUTE — in its ACL, and anon inherits through
-- PUBLIC. There is no ordering that works, so do not "fix" this by
-- reordering it.
--
-- CONSEQUENCE, STATED PLAINLY: there is NO database-level backstop for future
-- functions. The real guards are the two below, and they are the whole
-- defence:
--
--   1. the explicit REVOKE in each function's OWN migration (verified to
--      work — after add_token_charge_rpc.sql, anon has no EXECUTE on
--      token_charge), enforced in CI by test_migration_security_rules.py;
--   2. re-running THIS sweep after any migration that adds a function.
--
-- What the block below DOES do, and it is worth doing: it removes Supabase's
-- DIRECT default grants to anon/authenticated, so a future function is not
-- additionally granted to them by name. That is a real narrowing — it just is
-- not sufficient on its own, because PUBLIC still carries EXECUTE.

DO $$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY['anon', 'authenticated'] LOOP
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            EXECUTE format(
                'ALTER DEFAULT PRIVILEGES IN SCHEMA public '
                'REVOKE EXECUTE ON FUNCTIONS FROM %I', role_name);
            RAISE NOTICE 'default privileges: direct grant to % removed from '
                         'future functions (PUBLIC still carries EXECUTE — '
                         'see the header)', role_name;
        END IF;
    END LOOP;
    RAISE WARNING 'A future CREATE FUNCTION in public is STILL callable via '
                  'PUBLIC. Every new function needs its own REVOKE, or re-run '
                  'this sweep after adding one.';
END $$;

-- ── STANDING RULE ────────────────────────────────────────────────────────
--
-- Every new `public` function gets, in the SAME migration that creates it:
--
--     REVOKE ALL ON FUNCTION public.<name>(<types>) FROM PUBLIC;
--     -- plus anon / authenticated, role-guarded
--     GRANT EXECUTE ON FUNCTION public.<name>(<types>) TO service_role;
--
-- Adding it later is a separate migration that has to be run separately, and
-- until it is, the function is world-callable. Mirrors the table rule at the
-- bottom of docs/RLS-AUDIT.md. Enforced in CI by test_migration_security_rules.py
-- so it cannot be forgotten quietly.
