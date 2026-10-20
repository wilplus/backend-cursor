# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D29

Status: proposed final claim-schema and bounded-enqueue closure; executable
work remains blocked pending independent Product, ML/data and Engineering
acceptance.

## 1. Parent and narrow supersession

D29 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D28.md
SHA-256 8744c45bcd7f08841a3e9afaafb3d1c443d1bfb32880bd6604c2a07ec2769d0d
```

D28 and all accepted parents remain authoritative except where D29:

1. adds structural non-serving/non-dataset columns to the mutable claim head;
2. pins the complete amended lifecycle-event schema and legacy boundary;
3. makes the two-second sweep guarantee executable through a dedicated
   deadline-enforced enqueue adapter; and
4. fixes the exact canonical snapshot timestamp representation.

No public response, product meaning, lock, authorization, deletion, dataset,
learning-surface or disabled-gate contract changes.

## 2. Canonical core timestamp precision

D28's fourteen-key snapshot object is unchanged. Its `created_at` value is
rendered by PostgreSQL in UTC with **exactly six fractional digits**:

```text
YYYY-MM-DDTHH24:MI:SS.USZ
example: 2026-09-12T12:34:56.123456Z
```

The database constructs this string from the stored `timestamptz` after
conversion to UTC. A missing fraction, fewer/more than six digits, numeric
epoch, named zone, offset other than literal `Z`, locale-dependent form or
application-side reformat is invalid. This formatting is part of
`read_sha256`; the immutable stored timestamp and snapshot are not changed.

The released snapshot schema declares `arc_id` and `actor_id` `NOT NULL` but
does not exclude empty text. D29 chooses fail-closed read semantics: if either
stored identifier is empty after exact empty-string testing, v2 returns typed
`CONFIDENT_MOMENT_PROJECTION_INVALID` and no snapshot/overlay payload. It does
not trim, repair, substitute request input, mutate the historical row or change
the released table constraint. Non-empty identifiers are passed through as
their exact stored text.

## 3. Complete claim-head schema

`feedback_language_delivery_job_claim_heads` has exactly:

```text
job_id                    uuid primary key
  FK feedback_language_delivery_materialization_jobs(id) ON DELETE RESTRICT
current_claim_attempt_id  uuid not null
attempt_count             integer not null check (attempt_count between 1 and 12)
lease_expires_at           timestamptz not null
updated_at                 timestamptz not null
serves_user                boolean not null default false check (not serves_user)
dataset_eligible           boolean not null default false check (not dataset_eligible)
```

The existing D28 composite FK remains exact:

```text
(current_claim_attempt_id, job_id, attempt_count)
  -> feedback_language_delivery_job_claim_attempts(id,job_id,attempt_number)
  ON DELETE RESTRICT
```

There is one row per ever-claimed job and none before a real claim. Only the
claim/materializer RPC-owned private capability may insert/update the four
operational fields. The two structural false fields can never change. The head
is operational coordination and never serving evidence, a dataset member or a
learning label.

## 4. Complete lifecycle-event schema

### 4.1 Exact amended table

`feedback_language_delivery_materialization_job_events` has exactly:

```text
id                  uuid primary key default gen_random_uuid()
job_id              uuid not null
  FK feedback_language_delivery_materialization_jobs(id) ON DELETE RESTRICT
event_kind          text not null
  check event_kind in
    ('completed','closed_stale','failed_retryable','exhausted')
delivery_id         uuid null
  FK feedback_language_revision_deliveries(id) ON DELETE RESTRICT
attempt_number      integer not null check (attempt_number between 1 and 12)
claim_attempt_id    uuid null
contract_version    text null
cause_code          text null
event_sha256        text not null check lowercase SHA-256
idempotency_key     text not null unique
created_at          timestamptz not null default clock_timestamp()
serves_user         boolean not null default false check (not serves_user)
dataset_eligible    boolean not null default false check (not dataset_eligible)
```

For D29/v2 rows the exact composite FK is:

```text
(claim_attempt_id,job_id,attempt_number)
  -> feedback_language_delivery_job_claim_attempts(id,job_id,attempt_number)
  ON DELETE RESTRICT
```

The referenced attempt table retains
`UNIQUE(id,job_id,attempt_number)`. `claim_attempt_id` is nullable only for the
explicit legacy rows in section 4.3; every newly inserted event requires the
composite FK.

### 4.2 Exact v2 event constraints

Every newly created row requires:

```text
contract_version = 'feedback-language-delivery-job-event-v2'
claim_attempt_id is not null
```

The closed conditional matrix is:

| Event | Delivery | Cause code | Additional requirement |
| --- | --- | --- | --- |
| `completed` | exact non-null current delivery | `delivery_materialized` | delivery is for the exact job revision/recipient/target Take |
| `closed_stale` | null | one of the closed stale codes below | current provenance is permanently unusable |
| `failed_retryable` | null | one of the closed retry codes below | no terminal event; failure belongs to this exact attempt |
| `exhausted` | null | `claim_attempt_limit_reached` | exact expired/unresolved attempt 12; no delivery |

Closed stale cause codes:

```text
revision_superseded
authority_withdrawn
source_deleted_or_purged
attachment_invalidated
recipient_or_project_invalid
delivery_already_resolved_elsewhere
```

Closed retryable cause codes:

```text
lock_timeout
target_take_changed
temporary_database_failure
enqueue_lease_expired
```

No exception message, content, principal, transcript, audio or media identity
may be copied into `cause_code`.

Replace the released broad `UNIQUE(job_id,event_kind)` constraint with:

```text
UNIQUE(job_id) WHERE event_kind IN ('completed','closed_stale','exhausted')
UNIQUE(job_id,attempt_number,event_kind)
  WHERE event_kind = 'failed_retryable'
```

The first is a partial unique index that permits exactly one terminal kind in
total. A v2 `idempotency_key` is server-derived from exact job, claim attempt,
event kind, delivery/null and policy version. `event_sha256` binds all exact
row facts including cause and structural false values.

### 4.3 Exact legacy grandfathering

Rows that existed before D29 are not rewritten or assigned synthetic claim
attempts. They are recognized only by:

```text
contract_version is null
claim_attempt_id is null
cause_code is null
event_kind in ('completed','closed_stale','failed_retryable')
```

Their existing non-null columns, immutable trigger and historical hashes remain
byte-identical. No new insert may use this null contract after migration; a
table `CHECK` permits only the exact legacy triple or the exact v2 matrix, and
a private `BEFORE INSERT` guard rejects every new row whose
`contract_version` is not exactly
`feedback-language-delivery-job-event-v2`. Existing rows satisfy the `CHECK`
without being rewritten; the immutable UPDATE/DELETE guard prevents converting
between branches. No timestamp, sequence cutoff, GUC, role or caller assertion
is used to identify legacy history.

Before replacing the released uniqueness constraint, migration validation must
prove the historical rows satisfy it and that no job has conflicting terminal
history. The new terminal partial index includes legacy completed/closed-stale
rows, so a v2 terminal cannot fork them. A legacy `failed_retryable` row remains
history but cannot act as a v2 claim, increment an attempt or authorize
materialization. Reapply performs no legacy mutation.

## 5. Executable two-second enqueue boundary

### 5.1 Why the existing enqueue cannot prove the budget

`services.job_queue.enqueue` uses the cached client profile with
`socket_connect_timeout=2` and `socket_timeout=5`. Calling it directly cannot
prove D28's two-second wall-time bound. D29 therefore does not use that helper
inside the delivery sweep.

### 5.2 Dedicated bounded adapter

Add:

```text
services/job_queue.py::enqueue_with_monotonic_deadline(
  func_path: str,
  *args,
  rq_job_id: str,
  deadline_monotonic: float
) -> bool
```

This adapter is for the delivery sweep only. Its executable contract is:

1. it runs only in the POSIX RQ workhorse main thread;
2. it computes `remaining = deadline_monotonic - time.monotonic()` before
   connection construction and before enqueue; non-positive remaining returns
   false without I/O;
3. it creates a dedicated, non-cached Redis connection/queue whose
   `socket_connect_timeout` and `socket_timeout` are each
   `max(0.001, remaining)` seconds, with Redis/RQ automatic retries disabled;
4. it snapshots the existing signal handler and `getitimer(ITIMER_REAL)` value,
   accounts for elapsed monotonic time, and refuses I/O if an earlier timer
   cannot be preserved; otherwise it arms a process-local
   `signal.setitimer(ITIMER_REAL, remaining)` with a private handler that raises
   the adapter's typed timeout before any network operation, then restores the
   prior handler and the prior timer's **elapsed-adjusted remaining duration**
   and interval in `finally`—it may never extend or swallow an RQ death timer;
5. timeout/error disconnects this dedicated connection pool and returns false;
6. success uses the existing queue name, job timeout, zero result TTL,
   seven-day failure TTL and exact caller-supplied deterministic RQ job ID; and
7. the dedicated connection is disconnected in `finally` and never enters
   `_redis_conns`, so it cannot change or interrupt the worker's blocking Redis
   connection.

The signal is the hard whole-call cancellation boundary; socket timeouts are
defense in depth. This helper must reject use outside the main thread or on a
platform without `SIGALRM/ITIMER_REAL`, returning false before I/O. It must not
fall back to the unbounded cached enqueue. An uncertain network timeout may
have reached Redis; deterministic RQ job identity makes the later retry safe.

### 5.3 Sweep budget and yielding

At sweep entry:

```text
hard_deadline = time.monotonic() + 1.900 seconds
```

The reserved 100 ms is for Python unwinding/return. Before each job, the sweep
checks the deadline, then calls `enqueue_with_monotonic_deadline` with that same
absolute deadline and RQ ID
`confident-moment-delivery-<job_uuid>`. It checks again immediately after the
call. It performs no other blocking I/O after the deadline.

At deadline, enqueue failure or `has_more=true`, it returns/yields to the
existing `services.pipeline_jobs.run_sweep_loop`. It never sleeps, retries
inline, spawns a thread/process, leaves an armed timer, or uses the ordinary
five-second enqueue. The durable claim lease is later recoverable exactly as
D28 specifies.

The immediate post-publish wake-up may continue using the existing best-effort
enqueue because it is outside the bounded sweep; it remains after database
commit and cannot change the public D14 result.

## 6. Deletion, registry and apply/reapply

D28's deletion graph is retained and now includes the two claim-head structural
false fields and the event composite claim FK. All job→attempt→head/event and
event→delivery edges remain `ON DELETE RESTRICT`; reviewed invalidation closes
work without deleting immutable evidence.

Add to the closed application registry:

```text
services/confident_moment_delivery_worker.py::
  sweep_due_confident_moment_deliveries
  -> services.job_queue.enqueue_with_monotonic_deadline
```

Static checks reject an ordinary `job_queue.enqueue` call inside that sweep,
any different RQ ID, cached connection use or thread/process timeout wrapper.

Migration order is:

1. create/validate immutable claim attempts;
2. create claim heads including `serves_user` and `dataset_eligible` false
   constraints;
3. add nullable event extension columns;
4. validate/freeze the legacy cutoff and historical terminal consistency;
5. drop the old broad uniqueness and add exact partial/composite constraints;
6. replace scanner/materializer helpers and guards;
7. force RLS/revoke direct writes/run registry and deletion closure; and
8. reload PostgREST/commit.

Apply/reapply changes no historical row, creates no attempt/head/event, and
does not recreate or drop constraints in a way that exposes a direct-write
window. Any invalid legacy history or negative control rolls back all D29
schema changes.

## 7. Required executable regressions

Retain every D20–D28 regression and add:

1. exact six-digit UTC `created_at` output including `.000000Z`; every offset,
   missing/excess digit and application-side datetime object fails parsing;
2. historical snapshots with empty `arc_id` or empty `actor_id` each return
   `CONFIDENT_MOMENT_PROJECTION_INVALID` with no payload and no row mutation;
   non-empty stored text remains byte-identical;
3. claim head has both structural false fields, rejects true/null/direct update,
   and its composite attempt FK cannot mismatch job or number;
4. every v2 event column is present and its exact conditional matrix/FKs/hash
   hold; malformed delivery/cause/attempt/contract combinations roll back;
5. completed, stale and exhausted are mutually exclusive per job across legacy
   and v2 rows; retryable failures can occur once per distinct attempt only;
6. legacy event rows remain byte-identical with three null extension fields;
   a post-migration caller cannot fabricate a grandfathered row;
7. migration rejects preexisting contradictory terminal history atomically and
   reapply creates no synthetic attempt/event or duplicate index;
8. bounded adapter receives a fake connection that blocks beyond deadline and
   returns before the exact deadline tolerance, disconnects it and restores
   the previous signal handler/timer;
9. connect, Redis write and RQ enqueue timeout/error paths all return false,
   use no cached worker/client connection and never retry automatically;
10. adapter rejects non-main-thread/non-POSIX use before network I/O;
11. successful bounded enqueue uses exact queue/RQ/job TTL values and duplicate
    uncertain retry converges by deterministic job ID;
12. a multi-job sweep with the first enqueue consuming its budget makes no
    second network call and returns within two seconds;
13. `has_more`, failure and deadline paths yield to the one existing sweep
    chain without sleep/thread/process or lost lease recovery;
14. static caller audit proves bounded sweep cannot call ordinary enqueue;
    immediate post-publish enqueue remains permitted and post-commit; and
15. no claim/head/event/queue path exposes raw content, serves a user, becomes
    dataset-eligible or creates a learning-surface fact.

## 8. Permissions, gates and stop conditions

Attempts/events remain append-only forced-RLS; heads are forced-RLS/RPC-only;
all structural flags are false by check. Scanner/materializer/read RPCs remain
fixed-search-path and service-role-only. Private helpers and legacy-cutoff
guards are inaccessible to every runtime role.

All Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gates retain literal disabled defaults.

Stop and request review if implementation would:

- omit structural false checks from claim heads;
- leave any lifecycle-event column, conditional invariant, composite FK or
  legacy insertion boundary implicit;
- rewrite history or let legacy retry rows authorize a v2 claim;
- call ordinary cached enqueue from the bounded sweep;
- claim a two-second guarantee using only the released five-second socket
  timeout, a non-cancellable thread, sleep or inline retry;
- leave a signal handler/timer armed or interfere with the worker connection;
- format core timestamps anywhere except PostgreSQL's exact six-digit UTC `Z`
  form;
- pass through, repair or reinterpret an empty historical `arc_id`/`actor_id`
  instead of returning typed projection invalidity;
- weaken D28 claim/terminal/deletion rules, D27 public stripping, D25 locks,
  authority, blindness, RLS or non-learning boundaries;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D29 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
