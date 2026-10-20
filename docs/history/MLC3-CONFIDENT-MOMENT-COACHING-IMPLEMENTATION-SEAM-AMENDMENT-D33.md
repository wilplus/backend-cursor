# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D33

Status: proposed final due-rotation and durable scan-observability closure;
executable work remains blocked pending independent Product, ML/data and
Engineering acceptance.

## 1. Parent and narrow supersession

D33 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D32.md
SHA-256 8717774e811ef1077c5ad37a7f64808f81c9cf77394164ff39a81db5699b19b2
```

D32 and all accepted parents remain authoritative except where D33 replaces
the implicit due ordering with one durable due head per job and replaces
`pg_stat_activity` as the authoritative stalled-scan signal with an immutable
scan-run start plus exact completion/monitor receipt. D32's explicit Option-B
risk, one-candidate scanner, whole-client two-second bound, cooperative server
cutoff, non-waiting locks, permissions and non-learning rules remain.

D33 also narrowly supersedes D32's rule that target-Take existence is part of
the initial due-candidate index predicate. The scanner first selects one due
head, then performs one indexed target lookup. This is necessary to durably
defer a no-target job and rotate the queue; target absence still creates no
claim/attempt/exhaustion.

## 2. Durable due-head rotation

### 2.1 Exact table

Add forced-RLS, RPC-only mutable operational table:

```text
feedback_language_delivery_job_due_heads
```

with exactly:

```text
job_id            uuid primary key
  FK feedback_language_delivery_materialization_jobs(id) ON DELETE RESTRICT
scheduling_state  text not null check in ('pending','terminal')
next_probe_at      timestamptz null
last_probe_at      timestamptz null
probe_count        bigint not null default 0 check (probe_count >= 0)
updated_at         timestamptz not null
serves_user        boolean not null default false check (not serves_user)
dataset_eligible   boolean not null default false check (not dataset_eligible)
```

Closed state constraints are:

- `pending` requires non-null `next_probe_at`;
- `terminal` requires null `next_probe_at`;
- `probe_count=0` requires `last_probe_at is null`;
- `probe_count>0` requires non-null `last_probe_at`;
- `last_probe_at`, when present, is not after `updated_at`; and
- structural false values never change.

There is exactly one row for every materialization job. The coach publish
transaction creates the job and due head atomically with:

```text
scheduling_state = pending
next_probe_at = job.created_at
last_probe_at = null
probe_count = 0
```

Direct inserts/updates/deletes are denied. Only the publish, scanner and
materializer terminal-transition RPCs may mutate the exact permitted fields
under a private capability. The due head is scheduling coordination only—not a
delivery, exposure, response, confidence, quality fact or ML label.

### 2.2 Exact pending index and selection

Create the exact partial index:

```sql
CREATE INDEX ...
ON feedback_language_delivery_job_due_heads(next_probe_at,job_id)
WHERE scheduling_state='pending';
```

The D32 one-candidate scanner selects through this index:

```text
scheduling_state = pending
next_probe_at <= clock_timestamp()
ORDER BY next_probe_at, job_id
LIMIT 1
FOR UPDATE SKIP LOCKED
```

It then locks/validates the exact job and D28 claim state through the accepted
try-lock/skip-locked graph. It never searches jobs by an unindexed event
anti-join or lets one oldest no-target job remain first indefinitely.

### 2.3 No-target and claim transitions

If the selected job has no currently eligible later Take, the same bounded
scanner transaction updates only its due head:

```text
last_probe_at = exact probe time
next_probe_at = exact probe time + interval '60 seconds'
probe_count = probe_count + 1
updated_at = exact probe time
scheduling_state remains pending
```

This is a probe, not a claim. It creates no claim attempt/head/event, does not
advance attempt count or exhaustion, and returns zero jobs. Exact retry of the
same committed probe observes `next_probe_at` in the future and cannot increment
again. If cutoff/conflict occurs, the update rolls back.

When an actual eligible target exists and claim attempt N commits, the scanner
atomically advances:

```text
last_probe_at = claim time
next_probe_at = exact claim lease_expires_at
probe_count = probe_count + 1
updated_at = claim time
scheduling_state remains pending
```

Thus a failed enqueue/materializer becomes due only after its exact lease. A
successful `completed`, permanent `closed_stale` or `exhausted` transition
atomically sets `scheduling_state=terminal`, `next_probe_at=null`, and preserves
last probe/count. A terminal due head can never return to pending. Retryable
failure leaves the head pending at the current lease expiry.

The fixed 60-second no-target deferral plus `(next_probe_at,job_id)` ordering
makes the one-candidate scanner starvation-free: other due jobs rotate ahead on
later sweep turns. `probe_count` has no exhaustion or quality meaning.

## 3. Durable scan-run boundary

### 3.1 Exact table

Add forced-RLS, RPC-only mutable operational table:

```text
feedback_language_delivery_scan_runs
```

with exactly:

```text
run_id                 uuid primary key
worker_id_sha256       text not null check lowercase SHA-256
run_contract_version   text not null
  check = 'feedback-language-delivery-scan-run-v1'
started_at             timestamptz not null
finished_at            timestamptz null
result_code            text null
result_sha256          text null check null or lowercase SHA-256
serves_user             boolean not null default false check (not serves_user)
dataset_eligible        boolean not null default false check (not dataset_eligible)
```

Closed states:

- unfinished: all of `finished_at/result_code/result_sha256` are null;
- finished: all three are non-null and `finished_at>=started_at`;
- exact result code is one of
  `claimed`, `no_due_job`, `deferred_no_target`, `skipped_contention`,
  `stalled_scan_halted`;
- a finished row is immutable; and
- an unfinished row may be closed only by the scanner transaction for that
  exact run or the reviewed monitor terminalization wrapper after revalidation.

Worker identity is salted/hashed by the backend's reviewed operations identity
contract. No raw worker, job, Project, principal, Take or content identity is
stored.

### 3.2 Tiny committed begin RPC

Before the scanner call, inside D30's already-active whole-client deadline, the
worker generates one UUID and calls:

```text
begin_feedback_language_delivery_scan_run_v1(
  p_run_id uuid,
  p_worker_id_sha256 text,
  p_idempotency_key text
) -> jsonb
```

It is service-role-only, fixed-search-path, exact-key O(1), uses D31 non-waiting
lock rules and commits one unfinished row in its own tiny transaction. Exact
replay returns the same start only for the same run/worker/contract/key.
Changed identity fails. Its response contains only contract version, run ID,
canonical start time and structural false value.

The begin call is included in the client's 1.900/2.000-second scope. If it does
not commit/return in time, the worker makes no scanner or Redis call. An
uncertain begin may leave one unfinished run, which is deliberately visible to
the monitor rather than silently lost.

### 3.3 Scanner binding and close

The exact scanner signature becomes:

```text
claim_due_feedback_language_delivery_jobs_v1(
  p_run_id uuid,
  p_worker_id_sha256 text,
  p_limit integer,
  p_lease_seconds integer,
  p_server_budget_ms integer
) -> jsonb
```

It requires the exact unfinished run/worker/contract and locks it with
`FOR UPDATE SKIP LOCKED` before candidate mutation. It retains D32
`p_limit=1`, non-waiting locks, O(1) index operations and final cutoff.

On any normal committed outcome—including no due job, no-target deferral or
contention skip—the scanner atomically sets `finished_at`, exact result code and
`result_sha256` binding run, worker hash, timings, due-head before/result state
and claim job count without exposing IDs/content. `claimed` requires exactly
one committed attempt/head and opaque returned job. Other committed outcomes
return zero jobs.

The scanner itself may write only `claimed`, `no_due_job`,
`deferred_no_target` or `skipped_contention`. `stalled_scan_halted` is reserved
to the exact monitor wrapper in section 4.

An SQL exception, cooperative cutoff rollback, client cancellation or backend
termination rolls back scanner close together with all scanner mutations. The
separately committed begin row remains unfinished. The scanner may not catch a
budget/lock error and mark success in another transaction.

## 4. Durable stalled-run monitor and halt receipt

### 4.1 Source of truth

`pg_stat_activity` may remain supplementary diagnostics but is not readiness or
halt authority. The aggregate monitor selects indexed unfinished scan runs with:

```text
finished_at is null
started_at < clock_timestamp() - interval '5 seconds'
```

Any one such run satisfies D32's automatic halt threshold. Client cancellation
counts may remain aggregate telemetry, but the durable unfinished-row rule is
the exact fail-closed mechanism.

### 4.2 Atomic monitor wrapper and receipt

Add service-role operations RPC:

```text
halt_mlc3_for_stalled_delivery_scan_v1(
  p_monitor_run_id uuid,
  p_observation_cutoff timestamptz,
  p_idempotency_key text
) -> jsonb
```

It rederives the complete unfinished-over-five-seconds set under the reviewed
rollout/monitor serializers, hashes the sorted run IDs internally, invokes the
existing `halt_mlc3_service_rollout_v1` path, verifies disabled state, closes
each observed run with `result_code='stalled_scan_halted'` only after
proving it has no committed scanner result, and atomically appends one immutable
forced-RLS/RPC-only aggregate receipt:

```text
receipt_id
monitor_run_id
observation_cutoff
unfinished_count
unfinished_set_sha256
oldest_started_at
halt_operation_id
disabled_state_sha256
receipt_sha256
created_at
serves_user=false
dataset_eligible=false
```

No individual run/job/principal/content ID is returned or logged. Exact replay
returns the same receipt/halt. A concurrent scanner close winning first removes
that run from the observed set; monitor wrapper rederives before action. A
monitor winning first prevents that run from later claiming because rollout is
halted and its scan run is closed.

The existing aggregate monitor caller is the only operations caller. The RPC
can disable but never enable/resume. Sentry/operations notification references
only receipt ID/hash and aggregate count.

## 5. Whole-client workflow

The one D30 scope now covers exactly:

```text
begin scan-run RPC commit
  -> scanner RPC + closed validation
  -> zero/one deterministic enqueue
  -> local transport cleanup
  -> return/yield
```

It never begins the scanner without a committed run. It never retries begin or
scan in the same turn. If `has_more`, no-target deferral, contention, timeout or
enqueue failure occurs, it yields to the existing leased sweep chain. Due-head
ordering supplies the next fair candidate on a later turn.

D32's server Option-B risk remains explicit: a cancelled scanner may retain
successfully acquired locks while its current bounded phase completes, but it
cannot commit after cutoff. Its unfinished durable run triggers halt if it has
not closed within five seconds.

## 6. Deletion, migration and registries

Extend exact deletion lineage:

```text
materialization job -> due head ON DELETE RESTRICT
scan run -> aggregate monitor receipt by internal set-hash provenance
```

Deletion/purge terminalizes the due head through the same transaction that
closes the job; it never deletes scheduling/claim/event history. Scan-run and
monitor receipts are operations evidence with retention/deletion rules from the
existing aggregate monitor contract and no subject content.

For existing jobs at migration apply:

- a job with a valid terminal event gets one terminal/null due head;
- every non-terminal job gets one pending due head with
  `next_probe_at=job.created_at`, null last probe and zero count;
- contradictory/missing lineage aborts migration; and
- reapply creates no duplicate or timestamp/count change.

Create indexes/constraints/tables, populate/validate due heads, install private
guards, add begin/scanner/monitor wrappers, then run RLS/grant/caller/deletion/
call-graph closure before PostgREST reload and commit. Negative failure rolls
all D33 objects/data back.

Freeze exact callers:

```text
services/confident_moment_delivery_worker.py::
  sweep_due_confident_moment_deliveries
  -> begin_feedback_language_delivery_scan_run_v1

services/confident_moment_delivery_worker.py::
  sweep_due_confident_moment_deliveries
  -> claim_due_feedback_language_delivery_jobs_v1

scripts/monitor_mlc3_general_service.py::_halt
  -> halt_mlc3_for_stalled_delivery_scan_v1
```

The monitor symbol is the mechanically verified module-level `_halt`, not a
fabricated class method. The caller-registry AST test rejects class-qualified or
other module symbols.

## 7. Required executable regressions

Retain every D20–D32 regression and add:

1. publish creates job+pending due head atomically; either-side failure creates
   neither partial object;
2. scanner selects exact earliest `(next_probe_at,job_id)` through the partial
   index with `LIMIT 1 FOR UPDATE SKIP LOCKED`;
3. no-target probe advances only due-head time/count by exactly 60 seconds and
   creates no claim/attempt/exhaustion; exact replay cannot double-increment;
4. many no-target jobs plus one eligible job rotate fairly across bounded sweep
   turns and the eligible job is eventually claimed without a scan loop;
5. actual claim advances due head to exact lease expiry; retryable failure stays
   pending; completed/stale/exhausted terminalizes it atomically and terminal
   cannot reopen;
6. concurrent scanners cannot double-probe/claim one due head and can progress
   on different due heads through `SKIP LOCKED`;
7. migration populates pending/terminal heads exactly for zero, mixed and
   populated fixtures; apply/reapply is byte-identical; contradictory terminal
   lineage rolls back all D33 schema;
8. begin RPC creates one exact unfinished run; changed replay rejects; client
   timeout after uncertain begin leaves at most one durable unfinished row;
9. scanner requires exact run+worker, closes it atomically for each committed
   result, and cannot close while its claim/due mutation rolls back;
10. cancel/kill scanner in every phase: begun run remains unfinished, no late
    post-cutoff claim commits, and monitor observes it after five seconds;
11. normal run closes before five seconds and never triggers halt;
12. monitor/scanner race in both orders yields either exact normal close or one
    atomic halt+closed-run receipt, never both interpretations or later claim;
13. stalled monitor wrapper calls the exact existing halt path once, verifies
    disabled state, creates one replayable receipt and cannot auto-resume;
14. due heads, scan runs and receipts reject direct writes/true structural
    flags and contain no raw worker/job/subject/content values in public output,
    logs, Sentry or alerts;
15. one whole-client alarm demonstrably includes begin+scan+validation+enqueue,
    returns under two seconds and never starts scan when begin did not commit;
    and
16. RLS, deletion traversal, call registry and non-learning zero-state remain
    closed for all new objects.

## 8. Permissions, gates and stop conditions

Due heads and scan runs are forced-RLS/RPC-only; receipts are forced-RLS,
append-only and RPC-only. Public RPCs are fixed-search-path/service-role-only;
private helpers are inaccessible to runtime roles. All structural fields remain
false.

All Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gates retain literal disabled defaults. The automatic monitor may
only disable through the already-reviewed halt path.

Stop and request review if implementation would:

- scan jobs without the exact due-head partial index or let a no-target job stay
  first indefinitely;
- count a no-target probe as a claim/attempt/exhaustion or vary the 60-second
  deferral;
- create a job without its due head or terminal event without terminalizing it;
- call scanner before a separately committed durable begin row;
- treat `pg_stat_activity` or ephemeral logs as the authoritative stalled-run
  evidence;
- let an unfinished >5-second run avoid the exact halt/receipt or permit
  automatic resume;
- expose raw worker/job/subject/content identity through run/receipt output;
- weaken D32 Option-B/no-post-cutoff contract, D31 non-waiting graph, D30 client
  alarm, D29 schemas, D28 lifecycle, D25 locks, authority, blindness, RLS or
  non-learning boundaries;
- change an activation/learning gate except the authorized automatic disable;
  or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D33 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
