# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D34

Status: proposed final deterministic due-row, worker-identity and halt-receipt
closure; executable work remains blocked pending independent Product, ML/data
and Engineering acceptance.

## 1. Parent and narrow supersession

D34 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D33.md
SHA-256 b0fe70ec3b7f5a46c9a56a00bde6c97976783b7005d76ef7dd5dd26a24962c8a
```

D33 and all accepted parents remain authoritative except where D34 pins the
exact two-step due-row acquisition, exact process identity and exact stalled-
scan halt receipt/monitor call graph. No product, evidence, dataset, learning,
authorization, deletion or gate meaning changes.

## 2. Exact one-row due acquisition

### 2.1 Named index

Create exactly:

```sql
CREATE INDEX feedback_language_delivery_due_pending_idx
ON public.feedback_language_delivery_job_due_heads(next_probe_at,job_id)
WHERE scheduling_state='pending';
```

The migration/readiness registry pins this name, predicate, key order, table
OID lineage and valid/ready state. A renamed, invalid, differently ordered or
predicate-drifted index blocks closure.

### 2.2 Two-step selection; never walk around contention

For each D32 one-candidate scan, PostgreSQL performs exactly:

1. one index-only candidate-ID probe, without a row lock:

   ```sql
   SELECT job_id
   FROM public.feedback_language_delivery_job_due_heads
   WHERE scheduling_state='pending'
     AND next_probe_at <= clock_timestamp()
   ORDER BY next_probe_at,job_id
   LIMIT 1;
   ```

2. one exact primary-key current-row lock:

   ```sql
   SELECT *
   FROM public.feedback_language_delivery_job_due_heads
   WHERE job_id=:derived_job_id
     AND scheduling_state='pending'
     AND next_probe_at <= :exact_probe_cutoff
   FOR UPDATE NOWAIT;
   ```

The first statement projects only the indexed `job_id`; production-shaped
`EXPLAIN (ANALYZE,BUFFERS)` must show
`feedback_language_delivery_due_pending_idx` as the candidate access and no
explicit sort/sequential scan. MVCC visibility may cause a bounded heap
visibility check; it may not broaden the row set.

If the row disappeared/changed after step 1, return committed
`skipped_contention`. If the exact PK lock raises `lock_not_available`, catch
only that SQLSTATE, make no due/claim/event mutation, close the exact scan run
as `skipped_contention`, and return. The scanner must not use `SKIP LOCKED` to
walk later rows, repeat the index probe, increase a limit, or choose a second
candidate in the same turn.

After the row lock, all D31 try-locks/currentness rules and D33's exact
no-target/claim/terminal due-head transitions apply. A later scheduled sweep
turn retries whichever row is then first.

### 2.3 Contention observability and starvation safety

Every committed `skipped_contention` scan run is durable aggregate operational
telemetry. The v2 monitor reports its count in the last 60 seconds without run
or job identities. Exact circuit-breaker rule:

```text
>= 5 skipped_contention scan runs in a rolling 60 seconds
```

is a hard stop and uses section 4's reviewed halt path. This prevents persistent
first-row contention from silently starving the queue. Fewer than five defers
to later turns; the scanner still never skips ahead because doing so would make
ordering and starvation behavior data-dependent. Contention count is not a
product outcome, quality fact or ML label.

## 3. Exact per-process worker identity

### 3.1 Generation and fork behavior

`services.confident_moment_delivery_worker` owns one private PID-aware helper:

```text
_worker_process_identity_v1() -> (raw_uuid, worker_id_sha256)
```

On first use in each OS process it creates a cryptographically random UUIDv4
using `uuid.uuid4()`, canonicalizes it to lowercase hyphenated text, and caches
the tuple with the current `os.getpid()`. After a fork, PID mismatch discards
the inherited tuple and generates a new UUIDv4 before any scan-run begin.
Worker parent boot, each RQ workhorse and each replacement process therefore
have distinct identities.

The exact digest is:

```text
SHA256(UTF-8("confident-moment-worker-v1:" + canonical_uuid))
```

There is no salt, secret, hostname, account, principal, deployment, timestamp
or environment dependency. The raw UUID exists only in process memory. It is
never passed to SQL/Redis/RQ, persisted, logged, placed in Sentry/metrics or
returned. Only the 64-character lowercase digest is passed as
`p_worker_id_sha256` to begin/scanner calls.

### 3.2 Run/replay binding

Each sweep turn creates a fresh random canonical UUIDv4 `run_id`. The begin RPC
binds that run immutably to the exact process digest and contract. Exact begin
replay requires the same run ID, worker digest and idempotency identity. The
scanner requires the same pair. A different process digest, run ID, malformed
UUID/version or changed replay fails before due selection and cannot close or
claim another run.

The raw process UUID is not an authentication credential; service-role
execution and deployment identity remain authoritative. Its digest supplies
collision-resistant operational attribution without content or user identity.

### 3.3 Scanner-start marker and benign abandonment

Add nullable `scanner_started_at timestamptz` to D33's scan-run table. A begun-
only row has null scanner start/finish/result. Immediately before scanner I/O,
the worker commits
`mark_feedback_language_delivery_scan_started_v1(uuid,text,text)` for exact
run ID, worker hash and idempotency key; the scanner requires that marker. A
scanner-bound unfinished row has non-null start and null finish/result.

If begin committed but scanning will not start, the worker may call bounded
`abandon_feedback_language_delivery_scan_run_v1(uuid,text,text)`, which can
close only a begun-only row as `abandoned_before_scan`. Exact replay is
idempotent. The monitor also benignly closes begun-only rows older than five
seconds without halt. Only
`scanner_started_at IS NOT NULL AND finished_at IS NULL` older than five
seconds is stalled and may trigger halt. Thus scanner rollback leaves durable
stall evidence, while a crash between begin and scanner does not falsely halt.

## 4. Exact stalled-scan halt receipt and monitor path

### 4.1 Receipt table

Add forced-RLS, RPC-only, append-only:

```text
public.feedback_language_delivery_stalled_scan_halt_receipts
```

with exactly:

```text
receipt_id                 uuid primary key default gen_random_uuid()
receipt_contract_version   text not null
  check = 'feedback-language-stalled-scan-halt-receipt-v1'
monitor_run_id             uuid not null
observation_cutoff         timestamptz not null
unfinished_count           integer not null check (unfinished_count > 0)
unfinished_set_sha256      text not null check lowercase SHA-256
oldest_started_at          timestamptz not null
source_rollout_revision_id uuid not null
  FK public.mlc3_service_rollout_revisions(id) ON DELETE RESTRICT
halt_operation_id          uuid not null
  FK public.mlc3_service_rollout_revisions(id) ON DELETE RESTRICT
disabled_state_sha256      text not null check lowercase SHA-256
receipt_sha256             text not null unique check lowercase SHA-256
created_at                 timestamptz not null default clock_timestamp()
serves_user                boolean not null default false check (not serves_user)
dataset_eligible           boolean not null default false check (not dataset_eligible)
```

Additional constraints require `oldest_started_at < observation_cutoff`, both
rollout revisions to belong to the same exact rollout chain, and
`halt_operation_id` to equal the exact row returned by
`halt_mlc3_service_rollout_v1`. That returned row must be disabled/halted/
retired under the existing halt contract and be the current head when the
receipt commits.

The convergence key is:

```text
UNIQUE(source_rollout_revision_id,unfinished_set_sha256)
```

It intentionally excludes caller-generated `monitor_run_id`. Two monitors
observing the same exact sorted unfinished-run set under the same source
rollout revision converge on one halt/receipt; the loser revalidates and returns
the original exact receipt even with a different monitor UUID. Changed set or
source revision is a different operation. `receipt_sha256` hashes every exact
stored field: contract version, preallocated receipt UUID, first monitor UUID,
cutoff, count, set hash, oldest start, source/halt rollout IDs, disabled-state
hash, one preallocated `clock_timestamp()`, and both false flags. The same UUID
and timestamp are inserted. No field is excluded; convergence replay returns
the first stored receipt byte-for-byte even for a new monitor UUID.

### 4.2 Aggregate health RPC

Replace the monitor read with:

```text
get_mlc3_general_service_monitor_v2() -> jsonb
```

It returns the complete existing v1 health object unchanged plus one exact
closed `confident_moment_delivery_scanner` object:

```json
{
  "unfinished_over_5s_count": 1,
  "unfinished_set_sha256": "64-lowercase-hex-or-null",
  "oldest_started_at": "canonical-UTC-or-null",
  "skipped_contention_60s_count": 0,
  "hard_stop": true
}
```

Zero unfinished rows requires null set hash/oldest time. Positive count
requires exact sorted-set hash and oldest time. `hard_stop` is true on any
unfinished run older than five seconds or at least five skipped-contention runs
in 60 seconds. It exposes no run/job/worker/Project/principal/Take/content ID.

Exact caller:

```text
scripts/monitor_mlc3_general_service.py::_health
  -> get_mlc3_general_service_monitor_v2()
```

The released v1 RPC remains available to its frozen other callers.

### 4.3 Conditional `_halt` behavior

Exact wrapper:

```text
halt_mlc3_for_stalled_delivery_scan_v1(
  p_monitor_run_id uuid,
  p_observation_cutoff timestamptz,
  p_expected_unfinished_set_sha256 text,
  p_idempotency_key text
) -> jsonb
```

It rederives the set/count/hash and source rollout under the existing rollout
serializer. For the stalled-delivery hard-stop signal it calls the existing
`halt_mlc3_service_rollout_v1`, uses its returned row ID as
`halt_operation_id`, verifies disabled state, closes still-unfinished runs and
creates/replays the exact receipt atomically. Hash/set drift fails typed retry;
it never halts a caller-asserted set.

Exact conditional callers:

```text
scripts/monitor_mlc3_general_service.py::_halt
  -> halt_mlc3_for_stalled_delivery_scan_v1
     only when the reviewed report contains
     confident_moment_delivery_scanner.hard_stop=true

scripts/monitor_mlc3_general_service.py::_halt
  -> halt_mlc3_service_rollout_v1
     for every unrelated preexisting hard-stop reason
```

Thus D34 does not route unrelated integrity failures through the new receipt or
change their existing halt behavior. The AST/caller test freezes both branches
and rejects a fabricated class-qualified `_halt`.

Sentry/operations receives only receipt ID/hash, aggregate counts and signal
code. Exact replay, including a new monitor UUID, returns the existing receipt
through the convergence key and creates no second rollout revision.

### 4.4 Event-arm and no-target backoff

D34 supersedes D33's fixed no-target delay. A committed no-target probe changes
only `last_probe_at`, `probe_count`, `updated_at` and `next_probe_at`, with:

```text
delay = min(24 hours, 15 minutes * 2^least(probe_count_before_increment, 7))
next_probe_at = exact_probe_time + delay
```

It creates no claim attempt and cannot affect exhaustion. The canonical
post-commit Take seam calls:

```text
arm_feedback_language_delivery_jobs_for_take_v1(
  p_take_id uuid,
  p_idempotency_key text
) -> jsonb
```

PostgreSQL derives the Take, Project and acquisition principal. For every
affected pending due head it sets only
`next_probe_at=least(next_probe_at,clock_timestamp())` and `updated_at`; terminal
heads are untouched. The aggregate response contains count and set hash only,
never job or user/content identities. Exact replay is idempotent.

The exact caller is:

```text
routes/v2/lab_recording.py::v2_lab_create_recording
  -> services.confident_moment_delivery_worker::
     arm_confident_moment_deliveries_for_take
  -> arm_feedback_language_delivery_jobs_for_take_v1
```

It runs only after `_persist_lab_take` has committed the canonical Take and its
Project/principal lineage. Failed, duplicate-without-new-Take, ownerless or
internal Takes do not arm. Arm failure is operationally reported and does not
roll back or reinterpret the Take; the exponential due probe remains the
missed-wake backstop.

## 5. Migration, deletion and registries

Create/validate the named due index before scanner replacement. Create the
receipt table and monitor v2/wrapper before changing `_health`/`_halt`. All
objects are included in forced-RLS, direct-grant, function-signature, exact
caller, deletion and readiness registries. Apply/reapply changes no prior due,
run, rollout or event record and creates no receipt/halt.

Receipt FKs are `ON DELETE RESTRICT`. Scan runs and receipts follow aggregate
operations retention; subject deletion contains no direct identifying edge and
does not erase operational evidence. Job deletion remains restricted by due
heads/claim lineage as D33 requires.

Freeze application callers:

```text
worker.py::main / RQ sweep workhorse
  -> _worker_process_identity_v1 (raw UUID never leaves module)

services/confident_moment_delivery_worker.py::
  sweep_due_confident_moment_deliveries
  -> begin RPC with worker_id_sha256 only
  -> mark_feedback_language_delivery_scan_started_v1
  -> scanner RPC with same worker_id_sha256 only
  -> abandon_feedback_language_delivery_scan_run_v1 only before scanner start

routes/v2/lab_recording.py::v2_lab_create_recording
  -> services.confident_moment_delivery_worker::
     arm_confident_moment_deliveries_for_take
  -> arm_feedback_language_delivery_jobs_for_take_v1

scripts/monitor_mlc3_general_service.py::_health -> monitor v2
scripts/monitor_mlc3_general_service.py::_halt -> conditional new/existing halt
```

## 6. Required executable regressions

Retain every D20–D33 regression and add:

1. exact named partial index definition and index-only first-ID plan with no
   sort/sequence scan;
2. lock first due head in connection A; B performs one index probe and one PK
   `NOWAIT`, closes `skipped_contention`, never reads/locks/claims the second
   due row and returns within budget;
3. after A releases, a later turn processes the same first row; normal no-target
   deferral then rotates it and exposes the next due row;
4. five persistent contention runs/60s produce aggregate hard stop; four do
   not; halt prevents silent indefinite starvation and creates no ML fact;
5. per-process helper produces canonical UUIDv4 and exact unsalted namespace
   hash; repeated calls in one PID match, simulated/real fork PID change yields
   a distinct identity before scanning;
6. raw UUID is absent from every SQL argument, database row, Redis/RQ payload,
   log, Sentry context, metric and HTTP response;
7. begin exact replay with same run/hash succeeds; changed worker hash/run/key
   rejects; scanner cannot bind another process's run;
8. receipt table exact columns/types/FKs/checks/partial permissions and
   structural false enforcement; direct mutation rejects;
9. two monitor UUIDs with same source rollout + unfinished-set hash converge on
   one halt revision and exact receipt; changed set/source revision does not
   cross-replay;
10. `halt_operation_id` is the exact existing halt function result/current
    disabled head; foreign/non-chain/active rows fail atomically;
11. monitor v2 zero/nonzero/null rules, exact sorted-set hash, five-second and
    contention thresholds and no identifying fields;
12. `_health` calls only monitor v2 for this surface; `_halt` uses new wrapper
    only for stalled-delivery signal and preserves direct existing halt for an
    unrelated hard stop;
13. monitor/scanner races rederive the set: scanner winner closes normally,
    monitor winner halts/closes/receipts, never duplicate interpretations;
14. apply/reapply and forced failure leave no partial index/receipt/function/
    caller changes and preserve all historical data; and
15. all new state remains non-serving/dataset-ineligible and creates no product
    response, exposure, judgment, adequacy or learning-surface record.
16. begun-only runs can close exactly as `abandoned_before_scan`, never trigger
    halt, and cannot be abandoned after `scanner_started_at`; scanner-bound
    unfinished runs older than five seconds do trigger the reviewed halt;
17. exact no-target delays are 15m, 30m, 1h, 2h, 4h, 8h, 16h, then 24h capped,
    without claim/attempt/exhaustion mutation;
18. a committed genuine next Take arms all and only affected pending heads to
    now; terminal, foreign, duplicate, failed, ownerless and internal Takes do
    not; exact arm replay is inert and arm failure cannot fail the Take;
19. with N no-target jobs, backoff rotates bounded probes; a later canonical
    Take event-arms every affected pending head and repeated one-row sweep turns
    drain them in deterministic due order without starvation; and
20. `receipt_sha256` recomputes from every stored field using the exact frozen
    preimage, while convergence replay returns the original receipt unchanged.

## 7. Permissions, gates and stop conditions

Due/run/receipt objects remain forced-RLS and RPC-only; receipts are immutable.
Read/halt wrappers are fixed-search-path and service-role/operations-only.
Worker UUID is operational memory, never user identity.

All Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gates retain literal disabled defaults. The monitor can only
disable through the reviewed halt path and cannot auto-resume.

Stop and request review if implementation would:

- use `SKIP LOCKED` to walk beyond the exact first due ID or retry selection in
  one turn;
- rename/drift the due index or use unindexed/sorted selection;
- derive worker identity from a host/user/deployment/secret, persist/log the raw
  UUID, or reuse a pre-fork identity in a child;
- leave receipt schema, FKs, exact convergence key or halt-result identity
  implicit;
- use caller monitor UUID as replay identity or create two receipts for the
  same rollout/set;
- route unrelated `_halt` reasons through the stalled-scan wrapper or continue
  using monitor v1 in `_health`;
- halt a begun-only scan run, start a scanner without its durable start marker,
  or abandon a scanner-bound run;
- retain the fixed 60-second no-target delay, omit canonical Take event-arming,
  or let arming mutate probe counts, claims, attempts or terminal state;
- weaken D33 fairness/run durability, D32 Option-B cutoff, D31 non-waiting
  graph, D30 client alarm, authority, blindness, RLS or non-learning rules;
- change an activation/learning gate except the authorized automatic disable;
  or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D34 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
