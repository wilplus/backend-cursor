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
scripts/rehearsal_tier.sh --keep     # leave the cluster up; prints one DSN export per lane
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

Checkpoints of the checked-in Confident Moment recipe are cut from the same
build: `tests/integration/confident_moment_rehearsal.sh` reads
`CONFIDENT_MOMENT_CHECKPOINTS` (`<released file>=<database>` pairs) and clones
the lane right after that file applies. The canary and D4 lanes are such
checkpoints; neither suite can run on the finished chain (see the notes under
the table).

| Lane | Recipe | Database | DSN variable | Suites | Status |
|---|---|---|---|---|---|
| m33 | `mlc3_assignment_prerequisites.sql` → 0313, 0314, 0317 → `rpq_restoration_prerequisites.sql` → 0318–0321 (each applied twice) | `willab_m33_rehearsal` | `MLC3_REHEARSAL_DSN` | dark assignments (57), N1 source pattern (34), rooting-phrase qualification (24) | **verified 115/115** |
| d3 | m33 → 0322 | `willab_d3_rehearsal` | `COACH_GUIDANCE_REHEARSAL_DSN` | Coach Guidance D3 (14) | **verified 14/14** |
| service | d3 → 0323 | `willab_service_rehearsal` | `MLC3_FIRST_CLIENT_REHEARSAL_DSN` | First-Client Service D2 (73) | **verified 73/73** |
| confident-moment narrow | `tests/integration/confident_moment_rehearsal.sh narrow` (the checked-in recipe) | `willab_confident_moment_narrow` | `CONFIDENT_MOMENT_REHEARSAL_DSN` | coaching bundle (74) | **verified 74/74** |
| confident-moment released | `… confident_moment_rehearsal.sh released` | `willab_confident_moment_released` | `CONFIDENT_MOMENT_REHEARSAL_DSN` | production-shaped fixtures (9) | **verified 9/9** |
| canary | released lane, checkpoint right after 0325 `add_mlc3_founder_canary_security_closure.sql`, cloned; then `personalized_exercise_recommendation` and `coach_review` in `processing_purpose_registry` made operational with the five control columns the CHECK demands | `willab_d3_canary` | `MLC3_CANARY_READINESS_REHEARSAL_DSN` | founder canary readiness (9) | **verified 9/9** |
| d4 | narrow lane, checkpoint right after 0326 `add_mlc3_general_user_service_d4.sql`, cloned as the TEMPLATE the suite clones per test; two relaxations: `ml_judgments.id` gets a default, and every trigger on `reject_mlc2_immutable_mutation` / `reject_phase1_immutable_mutation` is disabled (the suite asserts nothing about immutability; the MLC-2 lanes do) | `willab_ga_template` | `MLC3_GENERAL_USER_REHEARSAL_DSN` | General-User Service D4 (34) | **verified 34/34** |

### Pending lane (reported NOT RUN)

One suite has no GREEN recipe. The runner reports it `NOT RUN` with the
reason, never as skipped, never as passed, and never as "expected to fail":

| Suite | Where it stands | Why it is not a lane yet |
|---|---|---|
| `test_mlc3_coach_inline_authoring_d5_postgres.py` | narrow lane, checkpoint right after 0324, plus the two D4 relaxations: **11/12**, fixture setup complete | the one failure is an assertion, not a fixture gap: `tests/test_mlc3_coach_inline_authoring_d5_postgres.py:782` expects two items in the visible blind batch and `prepare_coach_inline_blind_batch_v1` returns one. That is a behavioural question for D5's owner. 0324 is the right checkpoint: the same suite scores 5/12 at 0326. |

The step-by-step recipes, including this one, are in
`docs/REHEARSAL-TIER-PENDING-LANE-RECIPES.md` (established by execution on a
clean rebuild, 2026-09-14). Two corrections to what this page said before
that work:

1. The canary count difference was never caused by the narrow lane dropping
   `processing_one_active_policy_idx` (the index is present in the released
   lane). It was the six purpose rows seeded false, which the lane now fixes.
2. The canary suite must not run on the finished chain. 0326 supersedes
   `reserve_exercise_practice_service_upload_v1` with `_v2` and revokes v1 from
   `service_role` (deliberately; v2 calls v1 internally), while
   `scripts/check_mlc3_founder_canary_readiness.py` still lists v1 in
   `_REQUIRED_RPC_SIGNATURES`. From 0326 on, the deployed readiness audit
   therefore reports one false missing grant, and the suite scores 7/9 there.
   The revocation is right and the required list is stale against it. That is
   a founder decision about a production monitor, not a lane recipe; it is
   recorded here so nobody "fixes" the lane instead.

Closing the pending lane means resolving that assertion (or the behaviour
behind it) and then adding the checkpoint, the relaxations and the row above,
the same way the canary and D4 lanes were added. The founder ran these suites
by hand before their releases (#486, #487, #488, #490); the fixture databases
those runs used were not checked in, which is why the recipes had to be
reconstructed.

### Every lane has a wall clock

`scripts/rehearsal_tier.sh` runs each lane under `timeout` (default 900 s,
`REHEARSAL_LANE_TIMEOUT=<seconds>` to override) and reports a lane that hits
it as `FAIL … timed out after Ns — a hung test, not a slow one`, with the
number of tests that had passed before the stall. The slowest lane takes about
40 s, so the limit only ever catches a hang. The wrapper is coreutils
`timeout` (`gtimeout` on macOS); without either the lanes run unbounded and
the runner says so.

It exists because of a real one, seen once in three runs on 2026-09-14 while
folding the lanes above (not caused by the fold; the suite is unchanged since
#490): `test_confident_moment_coaching_bundle_postgres.py::`
`test_ack_render_revalidates_exact_coach_source_authority_in_both_orders`
`[render-reviewer_access]`. Its render-first branch holds a `FOR UPDATE` row
lock on the reviewer's `coach_users` row in one connection, submits the
withdrawing writer to a `ThreadPoolExecutor`, and polls `pg_stat_activity` for
that writer to block (`wait_for_lock`, 5 s deadline, raises). When the poll
misses its deadline the exception leaves the `with ThreadPoolExecutor` block,
whose exit joins the worker — which is blocked on the row lock the test still
holds, and which only the test's own `finally` (outside the block) would
release. The tier, and the CI job, then wait forever. The fix belongs in the
test (release `first` before the pool can join: `try … except BaseException:
first.rollback(); raise` around the wait-and-commit), but that file is in the
Confident Moment reviewed-hash manifest, so it goes through the packet's
re-freeze-and-review rule as its own change, not this one.

## When it is required

**The trigger is the change, not discipline.** `scripts/rehearsal_trigger.sh`
exits 0 when the diff against `origin/main` touches `migrations/`,
`tests/integration/`, the tier's own runner `scripts/rehearsal_tier.sh`, or an
MLC-3 storage module (the list is in the script).
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
   `scripts/rehearsal_tier.sh`; if it needs the chain as it stood at an
   earlier migration, cut a checkpoint with `CONFIDENT_MOMENT_CHECKPOINTS`;
   if the template lacks an object it needs, add it to the checked-in recipe,
   not to the test. A relaxation is acceptable only when the suite asserts
   nothing about the guard being relaxed, and it is stated next to the lane.
3. Run `scripts/rehearsal_tier.sh` and paste the result into the PR.

## Relation to the proposal for a production-shaped lane

The template is built from an empty database plus the narrow prerequisites
files. It does not carry production row shapes or the released trigger
definitions that only exist in production, which is the gap
`docs/audits/2026-09-14-proposal-production-shaped-rehearsal-lane.md`
describes. That lane, when it exists, is a second template for this same
runner.
