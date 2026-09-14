# Proposal — a rehearsal lane seeded from a production-shaped dump

*Status: PROPOSAL, not executed. Written 2026-09-14 as the "also missing"
item of the post-audit remediation programme. Nothing here activates any
gate, collects any data, or touches a migration.*

## The gap

Both rehearsal lanes (`tests/integration/*_rehearsal.sql` under a disposable
Postgres, and the `tests/*_postgres.py` suites gated on a `*_REHEARSAL_DSN`)
build from an **empty** database: `CREATE TABLE IF NOT EXISTS` from the
prerequisites file, then the migration under test, then synthetic rows the
test inserts itself.

Production is not empty. Four defects reached production on 2026-09-13 for
that single reason:

1. a legacy row with an empty-string value where every rehearsal row had a
   real one;
2. a trigger released by an earlier migration that raised `42703` (undefined
   column) on any owner-text edit, because the rehearsal schema never carried
   that trigger;
3. and 4. two security gates (`test_migration_security_rules.py`) that had
   never been applied to a file that was not yet in `manifest.txt`, so the
   rules were satisfied by omission.

An empty-database rehearsal can only prove a migration runs; it cannot prove
it runs against the data and objects that are actually there.

## The lane

**One additional opt-in rehearsal target, `rehearse-prod-shape`, that runs
every pending migration against a production-shaped schema dump before the
manifest entry is allowed to merge.**

What "production-shaped" means, and what it does not:

- **Schema, not data.** `pg_dump --schema-only` of production: every table,
  column default, constraint, index, function, trigger and RLS policy as it
  exists, including objects released by migrations that the disposable
  prerequisites file does not know about. This is what would have caught
  defect 2.
- **Row shapes, not rows.** A hand-maintained `legacy_shapes.sql` that
  inserts one row per known legacy shape (empty-string values, NULL in a
  column later made NOT NULL, a pre-rename table name still present) with
  synthetic ids and no user content. This is what would have caught defect 1.
  It grows by one row each time a production-only defect is diagnosed, so the
  lane accumulates the repo's scar tissue.
- **Every file, not the manifest.** The security-rule tests and the lane both
  iterate `migrations/*.sql` on disk, not `manifest.txt`, so a file that is
  present but unmanifested is still checked. This is what would have caught
  defects 3 and 4.

Run shape (no CI minutes involved; this is a `local_ci.sh --with-rehearsal`
step, opt-in like `--with-evals`):

```
createdb willab_rehearse
psql willab_rehearse < rehearsal/prod_schema.sql          # schema-only dump
psql willab_rehearse < rehearsal/legacy_shapes.sql        # known legacy rows
python scripts/migrate.py apply --dsn ... --pending       # what would run on boot
python scripts/migrate.py status --dsn ...                # checksum drift check
pytest tests/rehearsal --dsn ...                          # the *_postgres.py suites, pointed here
dropdb willab_rehearse
```

## What has to be decided before it exists

1. **Where the schema dump lives and who refreshes it.** A committed
   `rehearsal/prod_schema.sql` is the simplest (it is schema only; no user
   data, no secrets) but it goes stale. Proposal: refresh it as the first
   step of any PR that adds a migration, and let a test fail when the dump's
   recorded `schema_migrations` head is older than the manifest's.
2. **Supabase-specific objects.** The dump will reference `auth.users`,
   `storage.*` and `service_role`. The existing prerequisites file already
   fakes these (`CREATE EXTENSION pgcrypto`, `ALTER ROLE service_role
   BYPASSRLS`); the same stubs apply.
3. **Whether the `*_postgres.py` suites point at this lane.** They are held
   (Q-T2) pending founder re-confirmation. If they become the opt-in tier,
   this is the database they should run against, which makes them tests of
   production shape rather than of an empty schema.
4. **The checksum contract.** Migration 0327 is immutable in production
   (`39b62b50…`); the lane must run `migrate.py status` after apply so that an
   edited-after-apply file surfaces as drift here, before it surfaces on a
   container boot.

## Cost

One schema dump, one legacy-shapes file, one script target, one documentation
section in `docs/MIGRATIONS.md`. No new dependencies; `psycopg2-binary` and
`scripts/migrate.py` already exist. No CI minutes.
