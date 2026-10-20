# M3-3 dark assignment frames — implementation review

Status: **IMPLEMENTED LOCALLY; REVIEW REQUIRED; NO ACTIVATION**

Design: MLC-3-D2. Base: accepted M3-2 `13ca59a`.
Owner: Señor Engineer. Product owner: Artur Willoński.
Migration: `0314 add_mlc3_dark_assignment_frames.sql` (not applied to production).

## Corrective review — five findings against `a417f3b`

The rejected implementation remains available at `a417f3b`. This revision
repairs its five reproduced defects; acceptance is still pending. Migration
0314 is amended while unshipped, not yet approved, and applied only to disposable
local databases. No accepted migration is edited and no historical frame is
rewritten. An environment that had deployed the rejected SQL would require a
separate forward migration, not checksum rebasing.

| Finding | Correction | Executable PostgreSQL proof |
| --- | --- | --- |
| Foreign acquisition history influenced ranking | Observations, excluded-observation IDs, prior assignments and concurrency-history checks are principal-scoped. A fixed `cross_principal_not_authorized` scope rule replaces foreign IDs/counts. The deferred finalizer rejects cross-principal history references. | Same speaker with two principals, both with and without A's revocation: B retains no A IDs and does not suppress A's exercise. Principal purge selectors inventory permitted dependencies; shared profile identity remains speaker-inventoried. |
| Late catalogue/source commits entered an earlier frame | Immutable `mlc3_input_xid` metadata on need, media, definition, version, catalogue/header-item and feedback-frame inputs; all must be committed and visible in the assignment's captured snapshot. | Uncommitted catalogue, catalogue plus new version, and source frame committed while the assignment waits all raise SQLSTATE `40001`. A fresh invocation may succeed; later replays preserve its frame and RNG. |
| Audio or coordinates invalidated during a lock wait | Recheck the canonical exact-evidence/audio join after locks, before writes and after frame writes. No-match requests use the same post-wait validity boundary. | Audio deletion and changed persisted snippet intervals during contention reject both creation and replay, leaving no partial frame. |
| Observation duplicate replay returned after revocation | Recheck current authorization and exact source after the potentially blocking `ON CONFLICT`/lookup. | Concurrent duplicate observations reject the waiter after revocation, source deletion, coordinate change or policy expiry. The first historically valid observation is not altered. |
| Policy retirement used transaction-start time | M3-3's volatile wrapper retains foundation consistency checks and additionally checks activation, retirement, permit freshness and effective blocks against wall-clock time. | Retirement during assignment contention rejects creation/replay. Old transactions cannot create/replay assignments or observations after retirement. |

The new rejection tests were run against the **unchanged rejected SQL** in
`willab_m33_baseline_probes`: **19/19 fail for the reproduced defects** (not
schema/setup failures). All pass against the corrective SQL. These are local
synthetic regression checks, not model evaluations or production operations.

## Authorization and filter

M3-3 authorizes dark catalogue inventories, deterministic gating/ranking,
non-serving probability/RNG provenance, assignment-time snapshots and
post-blind no-match requests. It does not authorize producers, user/coach
exposure, datasets, training, model evaluation, promotion, deployment or
production migrations. M3-2 and all prior migration files remain unchanged.

```text
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      Exact-clip exercise assignment and provenance advance the approved
          exercise foundation without altering F1, blindness, or user text.
REDIRECT: Review M3-3 and its PostgreSQL evidence; keep every producer absent
          and every serving/learning boundary closed.
```

## What runs, and what does not

There is **no runtime caller**: no route, worker, job, cron, flag, UI, provider
call or model invocation was added. Service-role-only SQL RPCs can be exercised
in a disposable database. They do not create an exposure, human judgment,
supervision example or dataset record.

Every personal M3-3 table has `serves_user=false` and
`dataset_eligible=false` enforced with NOT NULL/CHECK constraints. Candidate
frames additionally require `rendered_exposure_id IS NULL` and no model
assignment. Changing configuration cannot make these records serve users.
A future serving contract needs a separately reviewed implementation.

The M3-2 purpose remains inactive; this migration does not activate it or
create acceptance on anyone's behalf. Tests use explicitly synthetic local
receipts, predictions, hashes and catalogue content, never production data.

## Tables and authoritative write paths

| Table | Responsibility | Only write path |
| --- | --- | --- |
| `exercise_media_availability_checks` | Immutable, short-lived object-verification receipts | `record_exercise_media_availability_v1` |
| `learning_profile_observations` | Exact-clip acoustic inputs from a canonical prediction/run | `record_exercise_profile_observation_v1` |
| `exercise_selection_feature_snapshots` | Assignment-time features, visible observation IDs, history and exclusions | Atomic assignment finalizer |
| `exercise_candidate_sets` | Complete catalogue, versions, source block/candidate, pool/frame hashes | Atomic assignment finalizer |
| `exercise_candidates` | Every eligible/excluded version, typed reasons, rank and rational probability | Atomic assignment finalizer |
| `exercise_assignments` | Stable exact-clip/block/need assignment or honest no-match | `finalize_exercise_dark_assignment_v1` |
| `exercise_randomization_assignments` | Unit, protected seed, commitment, draw, simulated selection and repetition | Atomic assignment finalizer |
| `exercise_requests` | Exact no-match request after independent blind submission and reveal | `register_exercise_no_match_request_v1` |

`finalize_exercise_catalog_snapshot_v2` also supports an empty complete
catalogue, which is a valid no-match situation. The accepted v1 function is
unchanged. Migration 0314 relaxes the catalogue's positive-count check
to permit zero and adds immutable commit-visibility metadata to its inputs.
The v2 snapshot derives items in the database; it accepts no
caller-provided shortlist. A stale catalogue cannot be used for a **new**
assignment if an in-scope version is now missing from it. Replay preserves
the old assignment rather than recomputing it against a new catalogue.

All new tables have explicit RLS, no public/anonymous/authenticated access,
service-role SELECT only, and append-only triggers. Internal hash, evidence,
gate, RNG, authorization and validation helpers are not service-executable.
The deferred atomic-frame trigger is SECURITY DEFINER: it can check protected
helpers at commit without widening runtime grants.

## Evidence and need contract

An observation references an existing `ml_machine_predictions` row, its
classification run and evidence span. The database verifies principal,
speaker, Project, Take, recording attempt, source object/bucket/key/SHA/size,
persisted snippet interval and non-deleted source audio. Predictions from the
retired detector fail; only `voice-confidence-universal-v3` is admitted.

The new **unproduced** acoustic-output contract is
`mlc3-acoustic-observation-v1`: `raw_output.acoustic_features` is an object of
numeric features, and `audio_quality` is `usable`, `audio_unclear`, or
`unreliable`. Feature names must be allowlisted by an approved need contract
and the feature schema must agree with the classification run. Values are
copied from the immutable prediction—not supplied separately by an assignment
caller. Confidence scores, owner answers and coach ratings are not features
for adequacy, and no adequacy outcome is derived.

No real need contract, threshold or exercise is seeded or approved here.
The reviewed implementation accepts this deliberately small gate grammar in
an approved need's `operational_definition`:

```json
{
  "assignment_gate": {
    "schema_version": "exercise-need-gate-v1",
    "feature_ranges": {
      "<approved acoustic feature>": {"min": 0, "max": 1}
    }
  }
}
```

The example numbers are syntax only, **not approved acoustic thresholds**.
At least one bound is required. Every required feature must have a range.
Unknown keys, missing ranges, invalid bounds, missing source values and
unsupported contracts fail closed. Nonempty contraindication contracts are
excluded as `unsupported_safety_contract` until their specific reviewed
interpreter exists; free-form safety prose is never treated as a passing
boolean. The source remains exact, not a permanent judgment about the person.

## Complete gate, ranking and media evidence

Each catalogue version gets all applicable typed exclusions. The gate covers
inactive/retired and superseded versions, unapproved safety/needs, need and
language mismatch, unpublished case-specific content, missing/stale/failed
media verification, unusable audio, absent/out-of-contract features,
unsupported safety contracts and previous dark assignment of that version.

`exercise_media_availability_checks` is not an R2 probe. A future approved
adapter must actually verify the object and submit its evidence. The database
checks the observed hash against the immutable media identity, freezes the
latest committed verification receipt, and rejects unavailable/expired
receipts. This version uses a five-minute maximum verification lifetime.
No network adapter or verification producer is enabled by M3-3.

Only gate survivors are ranked. The **fallback tie-break** is exercise key in
PostgreSQL `C` collation, then descending version and exact version ID. It
makes **no claim of learned effectiveness**. Need compatibility precedes it.
No adequacy model or score is fabricated, and eligibility is never a label.

No eligible exercise produces `dark_no_match`, not fallback invented content.

## As-of snapshots and temporal boundaries

The finalizer captures a PostgreSQL visibility snapshot and wall-clock
assignment time before waiting for locks. Each observation stores an immutable
`xid8`, recorded/observed times and event sequence. Inclusion requires:

- exact speaker and need;
- the current acquisition principal for acoustic features **and history**;
- `observed_at < assignment_at` and `recorded_at < assignment_at`;
- transaction visible in the captured snapshot;
- not written by the current assignment transaction.

The frame freezes visible observation IDs/features/hashes, sequence/time
watermarks, excluded IDs and reason counts, prior dark assignment IDs, source
quality, exact source frame/block/candidate and implementation versions.
Late commits cannot enter the old snapshot by backdating their observation.
The same commit-visibility boundary applies to the catalogue header, every
catalogue item/version, definition, need, media identity and source feedback
frame. Their `mlc3_input_xid` is assigned by the database and is not accepted
by the public RPC signatures. For pre-existing inputs, the migration's xid
is a conservative known-committed lower bound, not invented historical timing.
Reapplying the migration preserves those values. Timestamp checks remain
additional bounds, never substitutes for commit visibility.
Future attempts, outcomes and coach judgments have no input path.

No baseline estimator is approved here: `baseline_version=not_used-dark-v1`
and an empty contributing-ID list record this explicitly. A later estimator
must be versioned and use the same as-of boundary. Missing baseline is not
silently replaced with zero. Owner response and rendered exercise exposure
are explicitly `not_collected_dark`, not fabricated labels or histories.

The canonical `learning_profiles`/speaker identity is reused. Acoustic
observations and history from another acquisition principal are out of scope,
not legalized by the current account's acceptance. No foreign IDs, features
or counts are copied even as exclusion metadata. A fixed scope/reason records
this boundary. Only same-speaker **and same-principal** dark assignment IDs
support repeat suppression; they are not imported user exposure or training
evidence. Cross-principal history reuse would require a separate reviewed
authorization and deletion-dependency contract; this slice does not add one.

## Stable non-serving randomization

The immutable unit is `(speaker, audio_lineage, source_block, need_contract,
exposure_policy_version)`. It has one assignment ID and one server-generated
32-byte seed. The seed is protected behind service-only table access; its
SHA-256 commitment and SHA-256-derived 52-bit uniform draw are frozen.

The simulation policy is `exercise-80-20-simulation-v1`:

- zero survivors: no selected exercise;
- one survivor: probability 1, `deterministic_singleton`;
- two or more: rank 1 receives exactly `4/5`; every other survivor receives
  `1 / (5 × (eligible_count − 1))`;
- numerator/denominator, decimal probability and rank are stored for every
  candidate; excluded candidates have probability zero;
- the simulated winner is derived from the frozen draw, never supplied;
- this dark version's minimum-probability marker is 0.01; lower propensities
  carry `insufficient_assignment_probability`;
- **every** record is additionally `dark_non_exposure` for causal evaluation.

The 80/20 ratio is not a speaker/data split. A 1% floor and five-minute media
receipt lifetime are versioned **dark implementation choices for review**, not
approval to expose exercises. The endpoint/horizon/attempt/missing-data and
evaluation contract remains unapproved and user-facing randomization disabled.

Retries, including concurrent first creation and a different transport key
for the same exact unit, return the same assignment/seed/draw. Conflicting
inputs fail. A profile+need lock prevents two clips from concurrently bypassing
repetition: history outside the captured visibility snapshot raises a typed
serialization retry instead of silently entering features. All history is
identified as **dark**; it must not be interpreted as actual prior practice.
Coach-authorized repeat overrides are not accepted by this dark contract;
until their later typed authoring contract exists, repeats fail closed.

## Atomicity, current authority and post-blind requests

Authorization is checked at entry, after keyed-lock waits, before frame writes
and after potentially blocking inserts. Replay also revalidates authority and
exact non-deleted audio **after contention**, including the observation
upsert's unique-key wait. Exact-source checks repeat after assignment/request
lock waits and before returning newly written results. The finalizer
requires READ COMMITTED so an old repeatable-read snapshot cannot preserve
revoked authority. Freshness uses wall clock, not a long transaction's start
time. Policy activation/retirement and effective service blocks also use wall
clock; M3-2's transaction-start-time checks alone are insufficient. Policy-
purpose and receipt/policy consistency still use the accepted M3-2 gate, with
an explicit policy-version/purpose consistency check in the M3-3 wrapper. No
independent consent registry or alternative legal basis is introduced.

One transaction writes snapshot, complete frame, candidates, assignment and
RNG. A deferred constraint trigger rejects incomplete/mismatched ownership,
inventory, probability/hash or selection state at commit. Failure rolls back
all new rows; no partial result is reported successful.

A no-match request additionally requires:

- actionable source need/audio (unusable evidence does not request invention);
- a blind confidence packet for the **same audio lineage**;
- the assigned coach's immutable `blind_coach` judgment on the same evidence;
- recorded submission followed by that coach's post-judgment reveal access;
- current source-principal authority on both creation and replay.

The row is `dark_pending`. There is no coach inbox delivery, notification,
authoring UI, user offer or exposure. The original blind payload is unchanged;
acoustic needs, candidates, RNG and the request never enter it. Judgment is
confidence evidence, not exercise-effectiveness truth.

## Deletion and rollback

Every new personal table carries a database-derived acquisition principal and
has an explicit entry in `services/data_purge_registry.py`. Its disposition
is `external_review`, using the existing principal graph: a match blocks
completion pending the canonical retention/deletion review, rather than being
missed, silently retained or removed by a generic resolver. Catalogue/media
availability metadata is global content. All personal observation/history
references inside each frame are same-principal, including excluded IDs;
the deferred finalizer enforces this, making the principal-only selectors
complete for these dependencies. The shared `learning_profiles` identity is
separately inventoried by speaker and remains an explicit-review blocker.
No cross-principal selection dependency is permitted in M3-3. No deletion
adapter is activated or production data deleted in this slice.

Rollback before activation is code rollback with the additive tables left
intact. No legacy producer was changed, so rollback must not enable one. If a
future deployment needs to disable these RPCs, use a separately authorized
forward permission migration; never modify an applied migration, rewrite
frozen frames or erase provenance. M3-3 creates no feature flag to turn on.

## Rehearsal and remaining gates

Rehearsal files:

- `tests/integration/mlc3_assignment_prerequisites.sql` (synthetic dependency
  schema, not an application migration);
- `tests/test_mlc3_dark_assignments_postgres.py` (actual PostgreSQL RPC,
  adversarial, transaction and two-connection tests);
- `tests/test_mlc3_dark_assignment_contract.py` (CI-fast isolation/permissions/
  provenance/deletion classification checks).

The database suite refuses anything except a local Unix socket and a database
named `willab_m33_*`. It uses no R2, OpenAI or real user data. Apply prerequisites,
0313 and 0314; reapply 0314; then run the suite with `MLC3_REHEARSAL_DSN` set to
that disposable database. Normal CI skips these database tests and separately
runs its full established unit/compatibility suite.

Verification completed on 2026-08-30:

- PostgreSQL 16 clean apply and reapply of 0314: passed.
- Accepted M3-2 SQL rejection rehearsal after 0314: passed.
- M3-3 executable PostgreSQL suite: **57 passed** on both the corrective
  rehearsal database and final clean database (including the 19 new adversarial
  cases above and actual principal-selector purge-inventory verification).
- Negative control: **19 new rejection cases fail against `a417f3b`** in a
  separate disposable database, and pass against the correction.
- Focused foundation/deletion/contract compatibility suite: **36 passed**.
- `bash scripts/local_ci.sh --no-setup`: **GREEN**; **4,851 passed, 162
  skipped**, 113 subtests. The 162 skips include the 57 PostgreSQL tests run
  separately above. Ruff, mypy (338 source files), 314-entry manifest and
  66 migration-runner checks passed. Live model evaluations were not run.
- Accepted migrations 0309, 0311 and 0313 remain byte-for-byte unchanged.
- Final migration SHA-256:
  `9d935327a3cf8349e1ad9c6b99ee1d7339215db0e1edafbdf1595c228fb72320`.

These checks verify the local source tree, not production or a merge. The
review commit is supplied in the task handoff. The script's historical
GitHub-quota note was not reverified; no remote CI was triggered. These tests
do not replace an eventual deployment rehearsal against the target Supabase
schema or an actual authorized R2 verification adapter.

Next gates: ML/data and Engineering implementation review, followed by
separate authorization for the next slice or founder-only dark comparison.
Actual need contracts, serving copy, exercise purpose activation, outcome
labels, 80/20 exposure, datasets, training, evaluation, promotion and production
deployment remain separately blocked. **Nothing here authorizes M3-4.**
