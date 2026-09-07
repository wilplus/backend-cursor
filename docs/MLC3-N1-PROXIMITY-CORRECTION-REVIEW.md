# MLC-3 N1 Proximity Foundation — Corrective Review Packet

Status: local release preparation, assigned migration 0317, disabled scope only

Release base: `b87441dd54f746edd248e15c3049270bc4443395`

This packet integrates the accepted N1 proximity correction into the current
backend release line. Release preparation assigns it migration `0317`; it does
not activate a producer or route, serve an exercise, create an exposure,
collect real data, create a dataset, train, evaluate, promote, deploy, or
modify production data.

## Replay identity correction

`freeze_exercise_n1_pattern_snapshot_v1` now serializes on the immutable
candidate-set identity rather than on the caller-provided idempotency key.
After acquiring the lock, it rebuilds the complete candidate inventory and
recomputes its hashes before handling a replay.

A replay is accepted only when all of the following still match:

- candidate set;
- acquisition principal;
- source-pattern result;
- ordinal-policy version;
- complete ordered candidate inventory;
- candidate count;
- inventory and snapshot hashes;
- non-serving and non-dataset flags;
- complete persisted companion-candidate count.

Reusing an idempotency key for another candidate set raises
`N1_PATTERN_SNAPSHOT_REPLAY_CONFLICT`. Different retry keys for the same
immutable candidate set converge on the existing frozen snapshot only when
the complete identity remains equal.

The RPC acquires locks in one fixed order: natural candidate-set identity,
then caller idempotency key. This preserves same-set convergence while making
cross-set reuse concurrency-safe. A competing request waits for the winner,
then returns the typed replay conflict rather than a raw uniqueness error.

## Finite-range correction

All four supported/preferred ratio bounds are finite at two independent
boundaries:

- the registration RPC rejects null, `NaN`, `Infinity`, `-Infinity`, invalid
  ordering, and values outside the positive finite range;
- the table has a named finite-range constraint, installed again during
  migration reapplication, so direct or future privileged writes cannot
  bypass the same invariant.

The existing ordering contract remains unchanged.

## Deletion-lineage release correction

Full release verification found that the new subject-linked N1 relations were
not classified by the authoritative deletion dependency registry. The release
package therefore adds acquisition-principal lineage to every persisted N1
candidate and classifies these subject-linked relations as fail-closed external
review dependencies:

- `exercise_n1_source_pattern_results`;
- `exercise_n1_pattern_snapshots`;
- `exercise_n1_pattern_candidates`.

The global exercise-version compatibility profile is explicitly classified as
non-subject catalogue configuration. No deletion adapter or automatic deletion
behavior is introduced. This preserves the existing rule that unknown or
unreviewed subject dependencies block purge completion rather than being
silently skipped.

## Composite acquisition-principal identity correction

Every N1 child now inherits ownership through a database-enforced composite
identity rather than through an independently writable UUID:

```text
exercise_candidate_sets (id, acquisition_principal_id)
    -> exercise_n1_pattern_snapshots
       (candidate_set_id, acquisition_principal_id)
       <- exercise_n1_source_pattern_results
          (id, acquisition_principal_id)
    -> exercise_n1_pattern_candidates
       (candidate_set_id, acquisition_principal_id)
```

Named composite unique constraints provide the referenced parent identities.
Named composite foreign keys reject both a snapshot that combines principals
and a candidate that borrows a valid candidate-set ID from another principal.
The acquisition principal is also frozen explicitly into source-result,
inventory-candidate, and snapshot hashes. Constraint creation is guarded by
catalog checks, so clean and populated reapplication remain safe without
dropping an existing constraint.

## Regression evidence

The focused PostgreSQL suite contains:

- a same-source, cross-candidate-set retry-key regression that requires
  `N1_PATTERN_SNAPSHOT_REPLAY_CONFLICT` and proves the first snapshot remains
  unchanged;
- a forced two-connection race that blocks the first insert, starts a second
  candidate set with the same key, and verifies one immutable winner plus one
  typed `N1_PATTERN_SNAPSHOT_REPLAY_CONFLICT`;
- 12 RPC rejection cases: four bounds × three non-finite values;
- 12 independent table-constraint rejection cases: four bounds × three
  non-finite values;
- cross-principal snapshot rejection through both the candidate-set and source
  result composite identities;
- cross-principal candidate rejection through its exact parent snapshot;
- valid RPC creation plus byte-identical idempotent replay;
- deletion-inventory attribution for every source result, snapshot and
  companion candidate;
- the pre-existing provenance, exact-clip, complete-inventory, typed-exclusion,
  RLS/RPC-only and disabled-boundary cases.

Verification on a new disposable PostgreSQL database:

- prerequisites, M3-2, M3-3, and assigned migration 0317 applied;
- M3-3 and N1 migrations reapplied successfully;
- focused N1 PostgreSQL suite: **34 passed**;
- production-coordinate runner rehearsal baselined the repository's historical
  `0001..0316` block, applied `0317` successfully, reported `nothing pending`
  on the second run, and passed the same **34 tests** against that schema;
- populated-schema reapplication passed with all immutable rows and composite
  constraints intact;
- negative control against the previous SQL: both new regressions failed
  (**2 failed**) and pass after correction;
- deletion-registry classification suite: **14 passed**;
- full backend CI: **4,862 passed, 196 skipped**, with migration verification,
  Ruff and mypy passing;
- release-schema inspection confirmed RLS on all four N1 tables, SELECT-only
  service-role table access, and database constraints forcing both
  `serves_user=false` and `dataset_eligible=false`;
- `git diff --check`: passed.

No network provider, live R2 object, real user data, production database, or
production configuration was accessed.

## Checksum-pinned files

```text
31b9733d7cc35db787e2877847dd42348092df9ff5e3e1bc8cca6b1f79674ca7  migrations/add_mlc3_n1_source_pattern_provenance.sql
f11284ad6f9ddde90e44efcceeda8c39515e1e023f965016b5a06f608f8df250  tests/test_mlc3_n1_source_pattern_postgres.py
59c05bd334a11260568f304675138d9ecbd3b6cfc2566e6f413604f8594fba3a  tests/integration/mlc3_n1_source_pattern_rehearsal.sh
dd9e0b91cc398836839d007cdafdd6e37bbcd588065acb6a7bf17000471158c2  migrations/manifest.txt
92ab4e46a8f7dcc635873789d095d531dde39fdf3f945b9b5b9a946b7cb861cd  services/data_purge_registry.py
4a9cc175d9ab5edcd6bfd8059e3c4f8b8ad477395e7b152d998bd035cd5a2c24  tests/test_phase1_deletion_completion.py
```

## Preserved boundaries

- Migration is assigned as `0317` in the local release manifest but is not
  committed, pushed, applied to production, deployed, or activated.
- Writes remain validating-RPC-only; service-role table access remains
  read-only.
- Rows remain append-only, RLS-protected, `serves_user=false`, and
  `dataset_eligible=false`.
- Human judgments and product actions cannot provide the source pattern.
- No serving, exposure, collection, dataset, training, evaluation, promotion,
  deployment, or activation path was introduced.

## Release re-review request

> **ML/DATA IMPLEMENTATION RE-REVIEW REQUEST — N1 migration 0317 acquisition-principal lineage correction**
>
> Review the checksum-pinned release package against base
> `b87441dd54f746edd248e15c3049270bc4443395`. Verify the accepted N1 replay and
> finite-number corrections plus the composite candidate-set, snapshot,
> source-result and candidate acquisition-principal identities. Verify that
> principal identity participates in immutable hashes, cross-principal rows
> fail at the database boundary, deletion inventory attributes every N1 row to
> its exact acquisition principal, and apply/reapply preserves RPC-only, RLS,
> append-only, non-serving and non-dataset boundaries.
>
> Evidence: clean and populated disposable PostgreSQL apply/reapply; 34 focused
> PostgreSQL tests including the forced two-connection race and new principal
> rejections; negative control 2 failed against previous SQL; 14
> deletion-registry tests; full backend CI 4,862 passed and 196 skipped;
> migration verification, Ruff, mypy and diff checks passed.
>
> No push, deployment, production migration, activation, exposure, collection,
> dataset creation, training, evaluation, or promotion is authorized.
