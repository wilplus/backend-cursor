# Migrations — how schema changes reach a database

**Status:** shipped 2026-08-03. Replaces "apply by hand, then grep Railway
logs for Postgres error codes to find out what you missed."

---

## The problem this solves

There were 240 `.sql` files in `migrations/`, applied by hand, in no defined
order, with nothing recording what had run where. The only way to answer
*"which migrations ran in prod?"* was to wait for a user to hit a bug and
read the Postgres error code out of the Railway logs — `42703` for a missing
column, `42501` for a missing grant. `migrations/README.md` still documents
that as the procedure in places ("Run if Railway logs show 42703
missing-column warnings").

That works until it doesn't. A migration missed on an F1 surface — the
record → transcribe → coach → read loop — surfaces as a broken session, not
as a deploy failure.

Three pieces fix it:

| Piece | What it is |
|---|---|
| `migrations/manifest.txt` | The **order of record**. Every `.sql`, numbered, append-only. |
| `public.schema_migrations` | The **applied-state of record**, per database. |
| `scripts/migrate.py` | The runner: verify, status, plan, apply, baseline. |

---

## Day-to-day

### Adding a migration

```bash
python scripts/migrate.py new add_speaker_locale_to_recordings
```

Writes `migrations/add_speaker_locale_to_recordings.sql` and appends the next
version to the manifest. Write your SQL, keep it idempotent
(`IF NOT EXISTS`), commit both files together.

CI fails if a `.sql` is committed without a manifest entry — that file would
otherwise never run anywhere, which is the old failure mode with a new coat
of paint.

### Applying

```bash
python scripts/migrate.py status              # what this DB has, what's pending
python scripts/migrate.py plan                # what apply would do
python scripts/migrate.py apply               # run pending, in order
python scripts/migrate.py apply --dry-run     # pre-flight only
```

`apply` runs each file in its own transaction and writes its ledger row in
that same transaction, so a failure leaves neither the schema change nor the
claim that it happened. It stops at the first failure; already-applied files
are skipped on the retry.

### Applying by hand (still supported)

There is no `DATABASE_URL` on the founder's machine (see `docs/RLS-AUDIT.md`),
and the Supabase SQL Editor remains a first-class path:

```bash
python scripts/migrate.py plan --offline      # the ordered list
```

Paste each file into the SQL Editor in that order. Then, from anywhere that
*does* have `DATABASE_URL`, record what you ran:

```bash
python scripts/migrate.py baseline --to 0245
```

---

## Adopting this on an existing database (do this once, per database)

Prod already has all 239 original migrations applied by hand. **Do not run
`apply` against it** — that would replay files that drop tables and columns.

```bash
DATABASE_URL=... python scripts/migrate.py baseline --dry-run   # look first
DATABASE_URL=... python scripts/migrate.py baseline             # then confirm
```

**No `DATABASE_URL`?** Generate the SQL and paste it into the Supabase SQL
Editor, right after `create_schema_migrations.sql`:

```bash
python scripts/migrate.py baseline --sql          # needs no database
```

Generated on demand rather than committed as a `baseline.sql`, because a
checked-in one goes stale the moment a migration is added, and a stale
baseline silently under-records. It carries `ON CONFLICT (version) DO
NOTHING`, so it is re-runnable and can never overwrite a real runner-applied
row (`baselined = FALSE`) with an assumption.

`baseline` records every manifest entry as applied **without executing any
SQL**, marking each row `baselined = TRUE` so an assumption is never mistaken
for a verified apply. Tracking starts for real at the next migration.

Run it against staging first. On a genuinely empty database use `apply`
instead — baselining an empty DB permanently hides that nothing ever ran.

---

## Wiring it into deploys

`bin/railway-migrate.sh` is the entrypoint. Set it as the Railway
**pre-deploy command** on the service that owns migrations:

```
sh bin/railway-migrate.sh
```

### Which connection string

Supabase offers three, and two of them break things. Take the **session
pooler**:

| Option | Port | |
|---|---|---|
| Session pooler — `aws-0-<region>.pooler.supabase.com` | **5432** | ✅ use this |
| Transaction pooler — same host | 6543 | ❌ breaks the concurrency guard |
| Direct — `db.<ref>.supabase.co` | 5432 | ⚠️ IPv6-only on newer projects; Railway is IPv4 |

The transaction pooler is the dangerous one because it *appears* to work.
`apply` takes a `pg_advisory_lock` so two deploys can't apply the same
migration at once, and advisory locks are **session-scoped**. A transaction
pooler multiplexes connections per transaction, so the lock is taken on one
backend and released against another — the guard silently stops guarding, and
you only find out under a race. DDL in explicit transactions is unreliable
there for the same reason.

The runner detects a `:6543` URL and warns on every invocation. It does not
refuse: someone whose only reachable endpoint is the pooler should still be
able to migrate.

Railway runs a pre-deploy command to completion before routing traffic to the
new deployment: the schema lands before the code that needs it, and a
non-zero exit stops the deploy rather than shipping a backend into a database
it can't talk to.

Exit codes:

| Code | Meaning | Deploy |
|---|---|---|
| 0 | Applied, or nothing pending | continues |
| 1 | A migration failed, or was refused as destructive | **stops** |
| 2 | No `DATABASE_URL`, or psycopg2 missing | continues (unless `MIGRATE_REQUIRED=1`) |

Code 2 is deliberate: not every service in this project has a Postgres URL,
and those must still deploy. Set `MIGRATE_REQUIRED=1` on the one service that
owns migrations to make a missing database fatal *there*.

**Migrations are not on the web boot path.** CLAUDE.md's live-loop constraint
means a bad migration must never crash-loop the app. `bin/railway-web.sh` has
an opt-in `MIGRATE_ON_BOOT=1` hook for environments without a pre-deploy
command; it logs failures and boots anyway. Prefer the pre-deploy command.

---

## The safety rails

**Destructive SQL is refused.** CLAUDE.md: *never auto-drop tables, columns,
or migrations.* Files containing `DROP TABLE`, `DROP COLUMN`, `DROP SCHEMA`,
`TRUNCATE`, or `DELETE FROM` abort `apply` unless a human passes
`--allow-destructive`. Automation never passes it. Six files in the tree are
currently flagged; `migrate.py verify --verbose` lists them.

The scanner strips SQL comments first, and this matters: 30 files document
their own rollback in a comment (`-- Rollback: ALTER TABLE x DROP COLUMN ...`).
Flagging those would block a third of the tree, and someone would put
`--allow-destructive` in the deploy script to make it stop complaining —
strictly worse than no gate. `test_migrations.py` pins both directions.

**Checksum drift is reported.** Every applied file's sha256 is recorded.
Editing a file after it has been applied means the database was built from
different SQL than the repo now contains; `status` flags it. The fix is
always a new forward migration, never editing the old file to match.

**Concurrent runs are blocked** by a Postgres advisory lock, so two Railway
replicas booting together can't apply the same migration twice.

**Forward-only.** There is no `down`. Rollbacks are new migrations.

---

## About the ordering of 0001–0239

The true historical order is **unrecoverable** — files were applied by hand
and out of band, and nothing recorded when.

What *is* recoverable is the dependency order, which is the only property a
from-scratch rebuild actually needs: a file that `ALTER`s table T must come
after the file that `CREATE`s T. Each file's produced objects
(`CREATE TABLE/VIEW/TYPE`) and required objects (`ALTER`, `REFERENCES`,
`CREATE INDEX/POLICY/TRIGGER`, `GRANT`, `INSERT`, `UPDATE`) were extracted, a
DAG built, and a topological sort run with a deterministic tiebreak. Result:
**0 cycles, 0 ordering violations.** `test_migrations.py` re-checks the
invariant on every run, so a mis-ordered append fails CI.

Treat 0001–0239 as one baselined block, not a replayable timeline. Their
numbering is frozen — a hash in `test_migrations.py` fails the build if any
of them is renumbered or reordered, because those versions are already
recorded in prod's ledger.

**The manifest is not self-contained.** A few base tables (`recordings`,
`admin_users`) predate the migrations directory, and `auth.users` /
`storage.*` belong to Supabase. A from-scratch rebuild needs the Supabase
base schema first.

---

## Why not the Supabase CLI, Alembic, or Atlas

All three want to own the migration files. The Supabase CLI expects
timestamp-prefixed names under `supabase/migrations` and a linked project;
Alembic wants Python revisions with `down_revision` chains; Atlas wants a
declarative HCL schema it diffs against.

Adopting any of them means renaming or rewriting 239 files that are
referenced by name across `migrations/README.md`, `docs/*.md`, and the test
suite (`test_lounge_kind_migration.py` pins a migration filename and fails the
build when it drifts) — and inventing a history that can't be re-derived. The
rename alone is the kind of change that breaks the live loop for no F1 gain.

This runner implements the same core contract those tools do — ordered
versions, a `schema_migrations` ledger, checksum drift detection, runs in
CI/deploy — against the files as they already are, with a baseline path for
the hand-migrated prod database. If the layout is ever reworked, the manifest
is the migration path into whichever tool wins.

---

## CI

The `migrations` job in `.github/workflows/tests.yml` runs
`migrate.py verify --verbose` and `test_migrations.py`. Both are hermetic —
no database, no secrets, stdlib only — so the gate is green on day 1 and red
only when something is actually wrong.

Applying all 239 files to a throwaway Postgres would be a stronger check, but
they target Supabase (`auth.users`, `storage.*`, `service_role`), so that job
would be red for environmental reasons forever — and per this workflow's own
comments, *"a red-on-day-1 gate gets ignored."*

The runner itself was validated end-to-end against a real Postgres 16 before
merge: ledger bootstrap, baseline of all 239, apply with real DDL, destructive
refusal and override, checksum drift, atomic rollback of a failing migration,
and advisory-lock contention.
