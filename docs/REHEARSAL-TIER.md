# The rehearsal tier — PostgreSQL-bound tests, run against a disposable cluster

*Established 2026-09-14 (audit Q-T2, founder decision). This is the documented
run target for `tests/*_postgres.py`.*

## What it is

Eleven test modules under `tests/` can only run against a real PostgreSQL
(ten named `*_postgres.py` plus `test_confident_moment_production_fixtures.py`): they apply migrations, exercise RPCs under
`SET ROLE service_role`, race concurrent connections, and assert on what the
database did. Ten of them gate themselves on a `*_REHEARSAL_DSN` variable
with a module-level `skipif(..., reason="disposable … rehearsal only")`
(`test_rooting_coverage_policy_postgres.py` reads SQL text and needs no
database; it runs in the unit tier).

Before this tier existed those ten modules reported about 260 cases as
**skipped** on every ordinary run — "ran, chose not to", when the truth was
"never runnable here". They are the only tests of
`services/first_client_repository.py` and the MLC-3 storage paths, and they
are the tests that verified migration 0327 before it reached production.

## How it is reported

| Run | What happens to the nine modules |
|---|---|
| `pytest` (unit tier, CI `checks`, `local_ci.sh`) | **deselected**, and the terminal summary prints `rehearsal tier — NOT RUN: N tests in M modules (deselected, not skipped)` with the command that runs them |
| `scripts/rehearsal_tier.sh` | verified lanes built, run, torn down; exit 0 only if every verified lane passed; pending lanes printed as `NOT RUN` with the reason |
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
(the fixtures refuse any other host — nothing listens on TCP), then the lanes
below. **Each suite was written against the migration chain as it stood at
its own slice**; later migrations install append-only triggers that the
suite's fixture helpers trip. So lanes are checkpoints of one chain, cloned
under the database-name prefix each fixture demands — not clones of the final
schema. One `pytest` invocation per lane, so a suite only ever sees its own
database. Every row marked *verified* was run to green on 2026-09-14.

| Lane | Recipe | Database | DSN variable | Suites | Status |
|---|---|---|---|---|---|
| m33 | `mlc3_assignment_prerequisites.sql` → 0313, 0314, 0317 → `rpq_restoration_prerequisites.sql` → 0318–0321 (each applied twice) | `willab_m33_rehearsal` | `MLC3_REHEARSAL_DSN` | dark assignments (57), N1 source pattern (34), rooting-phrase qualification (24) | **verified 115/115** |
| d3 | m33 → 0322 | `willab_d3_rehearsal` | `COACH_GUIDANCE_REHEARSAL_DSN` | Coach Guidance D3 (14) | **verified 14/14** |
| service | d3 → 0323 | `willab_service_rehearsal` | `MLC3_FIRST_CLIENT_REHEARSAL_DSN` | First-Client Service D2 (73) | **verified 73/73** |
| confident-moment narrow | `tests/integration/confident_moment_rehearsal.sh narrow` (the checked-in recipe) | `willab_confident_moment_narrow` | `CONFIDENT_MOMENT_REHEARSAL_DSN` | coaching bundle (74) | **verified 74/74** |
| confident-moment released | `… confident_moment_rehearsal.sh released` | `willab_confident_moment_released` | `CONFIDENT_MOMENT_REHEARSAL_DSN` | production-shaped fixtures (9) | **verified 9/9** |

### Pending lanes (reported NOT RUN)

Three suites have **no verified recipe** and the runner reports them
`NOT RUN` with the reason, never as skipped and never as passed:

| Suite | Why | Best result found while investigating |
|---|---|---|
| `test_mlc3_coach_inline_authoring_d5_postgres.py` | migration 0324 needs `ml_presentations` (MLC-2 foundation), but with the MLC-2 migrations applied the suite's helpers trip `reject_mlc2_immutable_mutation` | narrow chain stopped after 0324, plus `ALTER TABLE ml_judgments ALTER COLUMN id SET DEFAULT gen_random_uuid()`: 11/12 |
| `test_mlc3_founder_canary_readiness_postgres.py` | 0325 needs `submit_mlc2_confidence_blind_judgment_v1` (MLC-2 confidence producer); one readiness count differs on the narrow chain (`required_operational_purpose_count` 0 ≠ 1, the narrow lane drops `processing_one_active_policy_idx`) | narrow chain stopped after 0325: 8/9 |
| `test_mlc3_general_user_service_d4_postgres.py` | 0326 needs 0324; on the narrow chain ten tests trip the MLC-2 / phase-1 append-only triggers during fixture setup | narrow chain stopped after 0326, cloned as the D4 template: 24/34 |

Closing a pending lane means writing its recipe into
`scripts/rehearsal_tier.sh` (a chain checkpoint plus whatever relaxation the
suite's author used) and moving the row up. The founder ran these suites by
hand before their releases (#486, #487, #488, #490); the fixture databases
those runs used were not checked in.

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
