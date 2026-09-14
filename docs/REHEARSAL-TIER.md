# The rehearsal tier — PostgreSQL-bound tests, run against a disposable cluster

*Established 2026-09-14 (audit Q-T2, founder decision). This is the documented
run target for `tests/*_postgres.py`.*

## What it is

Ten test modules under `tests/` end in `_postgres.py` and can only run
against a real PostgreSQL: they apply migrations, exercise RPCs under
`SET ROLE service_role`, race concurrent connections, and assert on what the
database did. Nine of them gate themselves on a `*_REHEARSAL_DSN` variable
with a module-level `skipif(..., reason="disposable … rehearsal only")`
(`test_rooting_coverage_policy_postgres.py` reads SQL text and needs no
database; it runs in the unit tier).

Before this tier existed those nine modules reported about 260 cases as
**skipped** on every ordinary run — "ran, chose not to", when the truth was
"never runnable here". They are the only tests of
`services/first_client_repository.py` and the MLC-3 storage paths, and they
are the tests that verified migration 0327 before it reached production.

## How it is reported

| Run | What happens to the nine modules |
|---|---|
| `pytest` (unit tier, CI `checks`, `local_ci.sh`) | **deselected**, and the terminal summary prints `rehearsal tier — NOT RUN: N tests in M modules (deselected, not skipped)` with the command that runs them |
| `scripts/rehearsal_tier.sh` | built, run, torn down; exit 0 only if every module passed |
| `WILLAB_REHEARSAL=1 pytest …` with a DSN missing | refuses to start (pytest usage error) — the tier never claims to have run when it did not |

The mechanism is `conftest.py` (`pytest_collection_modifyitems`), keyed on
each module's own skipif reason, not on the file name.

## How to run it

```sh
scripts/rehearsal_tier.sh            # build a disposable cluster, run, tear down
scripts/rehearsal_tier.sh --keep     # leave the cluster up; prints the six DSNs
scripts/rehearsal_tier.sh --dry-run  # list the modules, build nothing
scripts/local_ci.sh --with-rehearsal # the full gate plus the tier
```

Needs PostgreSQL 16 server binaries (`initdb`, `pg_ctl`, `psql`; Debian/
Ubuntu `postgresql-16`, macOS `postgresql@16`) and the gate's
`.venv-ci` (or `REHEARSAL_PYTHON=<python with pytest+psycopg2>`). On a root
shell the server processes are delegated to the `postgres` system user.

What the script builds: one cluster on a Unix socket under `/tmp/willab-*`
(the fixtures refuse any other host — nothing listens on TCP), one template
database built by the checked-in recipe
`tests/integration/confident_moment_rehearsal.sh narrow` (every
prerequisites file, then every released migration from MLC-2 through 0327,
the last applied twice as the idempotency check), and one clone of that
template per lane, named with the prefix each suite's fixture demands:

| Lane database | DSN variable | Suites |
|---|---|---|
| `willab_m33_rehearsal` | `MLC3_REHEARSAL_DSN` | dark assignments, N1 source pattern, rooting-phrase qualification |
| `willab_service_rehearsal` | `MLC3_FIRST_CLIENT_REHEARSAL_DSN` | First-Client Service D2 |
| `willab_d3_rehearsal` | `COACH_GUIDANCE_REHEARSAL_DSN` | Coach Guidance D3, coach inline authoring D5 |
| `willab_d3_canary` | `MLC3_CANARY_READINESS_REHEARSAL_DSN` | founder canary readiness |
| `willab_ga_template` | `MLC3_GENERAL_USER_REHEARSAL_DSN` | General-User Service D4 (clones the template per test) |
| `willab_confident_moment_narrow` | `CONFIDENT_MOMENT_REHEARSAL_DSN` | Confident Moment coaching bundle |

## When it is required

**The trigger is the change, not discipline.** `scripts/rehearsal_trigger.sh`
exits 0 when the diff against `origin/main` touches `migrations/`,
`tests/integration/`, or an MLC-3 storage module (the list is in the script).
Both `scripts/local_ci.sh` and the `checks` job in
`.github/workflows/tests.yml` consult it:

- triggered → the tier runs, and a tier that cannot run (no server binaries,
  a lane that fails to build) is **RED**;
- not triggered → the tier is reported `not run`, never `skipped`.

`test_local_ci_mirror.py` asserts that both sides consult the trigger and run
the same script.

## Adding a suite

1. Name it `tests/test_<thing>_postgres.py`, gate it on a `*_REHEARSAL_DSN`
   with a `skipif` whose reason says `rehearsal`, and have its fixture refuse
   any database whose name lacks the lane prefix and any host outside
   `/tmp/willab-*`.
2. If it needs a new lane, add the clone and the export in
   `scripts/rehearsal_tier.sh`; if the template lacks an object it needs, add
   it to the checked-in recipe, not to the test.
3. Run `scripts/rehearsal_tier.sh` and paste the result into the PR.

## Relation to the proposal for a production-shaped lane

The template is built from an empty database plus the narrow prerequisites
files. It does not carry production row shapes or the released trigger
definitions that only exist in production, which is the gap
`docs/audits/2026-09-14-proposal-production-shaped-rehearsal-lane.md`
describes. That lane, when it exists, is a second template for this same
runner.
