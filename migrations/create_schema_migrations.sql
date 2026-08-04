-- The migration ledger — what has actually been applied to THIS database.
--
-- Before this table, "which migrations ran in prod?" was answered by grepping
-- Railway logs for Postgres error codes (42703 missing column, 42501 missing
-- grant) — i.e. you found out a migration had been missed when a user hit the
-- bug. This table is the answer instead.
--
-- Bootstrapping: scripts/migrate.py runs this file itself before doing
-- anything else, so there is no chicken-and-egg problem. It is also safe to
-- paste into the Supabase SQL Editor by hand — that is still a supported way
-- to work here, and it must stay that way (no DATABASE_URL on the founder's
-- machine; see docs/RLS-AUDIT.md).
--
-- Deliberately NOT in manifest.txt: the ledger cannot be an entry in the list
-- it tracks.
--
-- Idempotent + additive, per the standing constraint. Re-running is a no-op.

CREATE TABLE IF NOT EXISTS public.schema_migrations (
    -- Zero-padded manifest version, e.g. '0042'. TEXT (not INT) so the
    -- primary key sorts the same way the manifest reads.
    version TEXT PRIMARY KEY,

    -- Manifest filename at apply time. Kept for readability; `version` is the
    -- identity. A rename shows up as drift in `migrate.py status`.
    filename TEXT NOT NULL,

    -- sha256 of the file bytes when applied. This is what catches the silent
    -- killer: someone edits an already-applied .sql, prod keeps the old
    -- schema, and every environment quietly disagrees. `status` flags it.
    checksum TEXT NOT NULL,

    applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Who/what applied it: 'ci', 'railway-deploy', a username, or 'baseline'.
    -- Set from MIGRATION_ACTOR; free text, never parsed for logic.
    applied_by TEXT,

    -- Wall-clock ms the statement took. NULL for baselined rows (nothing ran).
    execution_ms INTEGER,

    -- TRUE  = assumed already present (hand-applied before tracking existed);
    --         the SQL was NOT executed by the runner.
    -- FALSE = the runner executed this file against this database.
    -- The 239 pre-existing migrations get TRUE. Everything after gets FALSE.
    -- Without this column a baselined row is indistinguishable from a real
    -- apply, and "it's in the table" would stop meaning "it definitely ran".
    baselined BOOLEAN NOT NULL DEFAULT FALSE
);

-- "What landed in the last deploy?" and the ordering checks in `status`.
CREATE INDEX IF NOT EXISTS schema_migrations_applied_at_idx
    ON public.schema_migrations (applied_at DESC);

-- RLS ON, zero policies (amended 2026-08-03, PR #328).
--
-- This previously read "RLS off matches the other internal/ops tables; this
-- table holds no user data." The first half is true and the second is too —
-- but both reason about READS, and RLS-off is not a read setting. Supabase's
-- default grants to anon/authenticated make a public table without RLS
-- WRITABLE via PostgREST by anyone holding the anon key from the browser
-- bundle (docs/RLS-AUDIT.md). For a migration ledger that is worse than a
-- leak, because the runner TRUSTS this table:
--
--   * INSERT a row for a pending version -> `migrate.py apply` treats it as
--     already applied and SILENTLY SKIPS the migration. Prod never gets the
--     schema change and nothing reports an error.
--   * DELETE rows -> migrations re-run.
--   * UPDATE checksum -> defeats the drift detection this file exists to
--     provide, which is the "silent killer" the column comment above names.
--
-- Safe for every consumer: `scripts/migrate.py` connects via DATABASE_URL as
-- the table OWNER (owners are exempt from RLS absent FORCE ROW LEVEL
-- SECURITY), and the backend's service_role has BYPASSRLS. Verified against
-- PostgreSQL 16.13. Same shape as the 2026-07-25 sweep: enable it, add no
-- policies. `schema_migrations` postdates that sweep, so nothing else covers
-- it.
ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;

--
-- Guarded because `service_role` is a Supabase role, not a Postgres one: a
-- bare GRANT aborts with 42704 (role does not exist) on a plain Postgres —
-- a local dev database, or a CI container. The runner executes this file on
-- every invocation, so an unguarded GRANT would make the tool unusable
-- anywhere but Supabase.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT ALL ON public.schema_migrations TO service_role;
    END IF;
END
$$;
