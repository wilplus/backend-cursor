# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D28

Status: proposed exact core-envelope and durable claim-lifecycle closure;
executable work remains blocked pending independent Product, ML/data and
Engineering acceptance.

## 1. Parent and narrow supersession

D28 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D27.md
SHA-256 07f88177aed3dcbfe21ffc6157f318445071305ca9c85f9fec14bebb4112b025
```

D27, D26, D25 and all accepted parents remain authoritative except where D28:

1. replaces D27's illustrative snapshot deferral with the exact released
   fourteen-field snapshot object;
2. assigns the v2 read to a dedicated application method so existing v1
   consumers remain untouched; and
3. replaces the underspecified mutable delivery lease with an immutable claim-
   attempt history plus one RPC-owned operational claim head.

D27's internal publish-job extraction, post-commit wake-up, public D14 response
denylist, opaque job arguments and all disabled/non-learning boundaries remain.

## 2. Exact Ideal Text core v2

### 2.1 Exact snapshot object

`read_ideal_text_document_core_v2(TEXT,TEXT)` returns D27's closed envelope.
Its `snapshot` value has **exactly** these fourteen keys and types:

```json
{
  "id": "uuid",
  "arc_id": "text",
  "actor_id": "text",
  "acquisition_principal_id": "uuid",
  "project_id": "uuid",
  "source_take_session_id": "uuid",
  "version": 1,
  "source_generation": "9223372036854775806",
  "source_fingerprint_sha256": "64-lowercase-hex",
  "payload_sha256": "64-lowercase-hex",
  "payload": {},
  "enrichment_seed": {},
  "supersedes_id": null,
  "created_at": "2026-09-12T12:34:56.123456Z"
}
```

The closed rules are:

- `id`, `acquisition_principal_id`, `project_id` and
  `source_take_session_id` are canonical lowercase-hyphen UUID strings;
- `arc_id` and `actor_id` are non-empty exact text;
- `version` is a positive JSON integer within PostgreSQL `INTEGER` range;
- `source_generation` is a canonical non-negative base-10 PostgreSQL `BIGINT`
  encoded as a JSON string—never a JSON number;
- both SHA-256 values are exact lowercase hexadecimal;
- `payload` and `enrichment_seed` are JSON objects;
- `supersedes_id` is canonical UUID string or null; and
- `created_at` is the exact canonical UTC RFC3339 string with `Z`, derived by
  PostgreSQL from the stored `timestamptz`; offsets and locale formats are not
  accepted on the application wire.

There are no additional snapshot keys and no implementation-time `to_jsonb(*)`
expansion. The function constructs the object explicitly. `payload` is the
unchanged immutable stored payload and `payload_sha256` continues to cover only
it. D27's `dynamic_overlay.owner_edit`, Bundle summary/status and `read_sha256`
remain outside that immutable payload and retain their exact closed schemas.

### 2.2 Dedicated application caller

Add the exact current-core caller:

```text
services/db.py::DatabaseService.get_ideal_text_document_core_v2
  -> read_ideal_text_document_core_v2
```

Only `GET /v2/explore/arc/{arc_id}/ideal-text/core` uses this method. It makes
one database call and follows D27's exact HTTP merge without supplemental
notes/parts/principal/Bundle reads.

The released method and RPC remain unchanged:

```text
services/db.py::DatabaseService.get_ideal_text_document_core
  -> read_ideal_text_document_core_v1(text,text)
```

Existing recording-roots, enrichment and every other v1 caller continue using
that historical contract until separately migrated. D28 does not silently
change their result shape. Static caller tests require the core GET to use v2
and reject v2 use by an unregistered route, while preserving the exact existing
v1 caller set.

## 3. Durable delivery claim model

### 3.1 Immutable claim attempts

Add forced-RLS, RPC-only, append-only:

```text
feedback_language_delivery_job_claim_attempts
```

with exact columns:

```text
id                uuid primary key
job_id            uuid not null FK materialization_jobs(id) ON DELETE RESTRICT
attempt_number     integer not null check 1..12
worker_id          text not null, validated bounded opaque worker identity
claimed_at         timestamptz not null
lease_expires_at   timestamptz not null and > claimed_at
claim_sha256       lowercase SHA-256 not null
serves_user        boolean not null false check
dataset_eligible   boolean not null false check
```

Constraints include `UNIQUE(job_id,attempt_number)` and
`UNIQUE(id,job_id,attempt_number)`. `claim_sha256` binds exact job, attempt,
worker, claim time, expiry, claim policy version and the eligible target-Take
identity verified at claim cutoff. It contains no raw content.

Rows are immutable. A lease expiry is not an update to an attempt; a later
valid claim appends attempt `N+1`.

### 3.2 One mutable operational claim head

Add forced-RLS, RPC-only:

```text
feedback_language_delivery_job_claim_heads
```

with exact columns:

```text
job_id                    uuid primary key FK jobs(id) ON DELETE RESTRICT
current_claim_attempt_id  uuid not null
attempt_count             integer not null check 1..12
lease_expires_at           timestamptz not null
updated_at                 timestamptz not null
```

The composite FK `(current_claim_attempt_id,job_id,attempt_count)` references
the exact immutable attempt tuple. There is exactly zero head before the first
real claim and exactly one current head afterward. Only the claim/materializer
RPCs may insert/update it. It is mutable operational coordination, never
product evidence or an ML label.

The job identity row remains immutable routing provenance. Its historical
`attempt_count`/`job_state`, if retained for compatibility, are not independent
authority: guarded RPC writes must keep them equal to the claim head/terminal
event projection, and direct changes are rejected. The migration extends the
closed state vocabulary with `exhausted` only if the compatibility column
remains.

### 3.3 Claim eligibility and exact RPC

The D27 scanner signature remains:

```text
claim_due_feedback_language_delivery_jobs_v1(
  p_worker_id text,
  p_limit integer,
  p_lease_seconds integer
) -> jsonb
```

For each durable job, PostgreSQL derives the exact current revision,
attachment, recipient, source Take and **an actually existing eligible later
Take** under the accepted D14 routing rule. If no eligible target Take exists,
the job is not due, no attempt/head/event is written and no exhaustion count
advances. Its age/count may be reported only by aggregate monitoring.

A job is claimable only when it has no terminal event and either no claim head
or an expired current lease. Under D11 locks it acquires delivery subject 120,
revision head 130, then exact current job/claim/validity rows at 140. Across
jobs it uses deterministic oldest eligible due time then job UUID and
`FOR UPDATE SKIP LOCKED`. It appends exact next attempt and atomically
inserts/advances the claim head. Concurrent scanners cannot issue the same
attempt or hold simultaneous valid leases.

Only real claims count. At most twelve claim attempts are permitted. When an
expired twelfth real claim remains unresolved, the next scanner/materializer
decision appends exactly one terminal `exhausted` event rather than attempt 13;
it returns no claimed job. Age alone never exhausts a job.

The scanner response remains exactly D27's opaque contract:

```json
{
  "delivery_job_claim_contract_version": "feedback-language-delivery-claim-v1",
  "jobs": [{"job_id": "uuid"}],
  "has_more": false,
  "dataset_eligible": false
}
```

Worker/lease/attempt/target identities never leave PostgreSQL through this
response. The worker does not need or receive a claim token; the materializer
derives the exact current live claim by job ID and its deterministic operation
key.

### 3.4 Terminal and retry lifecycle

Amend `feedback_language_delivery_materialization_job_events` without rewriting
history. Its closed event kinds are:

```text
completed
closed_stale
failed_retryable
exhausted
```

Replace the unsafe broad `UNIQUE(job_id,event_kind)` with exact constraints:

- one terminal event per job via partial unique job identity for
  `completed|closed_stale|exhausted`;
- `UNIQUE(job_id,attempt_number,event_kind)` for retryable failure history;
- `attempt_number` must reference an existing exact claim attempt for every
  newly created event;
- `completed` requires one exact delivery ID and current valid delivery;
- `closed_stale` and `exhausted` require null delivery ID;
- `exhausted` requires attempt number 12 and an expired/unresolved twelfth
  claim;
- `failed_retryable` requires null delivery, the exact live/expired attempt as
  applicable, and cannot coexist with a terminal event created earlier; and
- event hash binds job, attempt, event kind, delivery/null, policy and exact
  terminal/retry cause code without raw content.

Historical events remain immutable. Apply/reapply validates them and adds
constraints/partial indexes without deleting, renumbering or fabricating an
attempt. Where a historical event predates the claim model, its existing row is
grandfathered by an explicit legacy contract version/null claim FK and may not
be used as a new claim result. New events always use the v2 claim linkage.

`materialize_feedback_language_delivery_job_v1(uuid,text)` remains idempotent.
Under 120→130→140 it rederives the current claim, target Take, revision,
authority and absence/current delivery. Exact replay of a terminal event returns
the same result. A live valid claim creates at most one delivery and completed
event. Invalid current provenance creates at most one `closed_stale`. A typed
retryable operational failure may append one failure for that attempt and lets
its lease expire; it cannot consume another attempt itself.

## 4. Bounded worker sweep

The exact D27 caller and start chain remain. The boot and recurring sweep call:

```text
services.confident_moment_delivery_worker.
  sweep_due_confident_moment_deliveries(
    worker_id=<stable process/run identity>, limit=25, lease_seconds=60
  )
```

Each invocation has a hard two-second monotonic wall-time budget, including
claim response validation and enqueue calls. It claims at most one bounded
batch. After each individual deterministic-RQ enqueue, control returns to the
loop so the deadline is rechecked; it performs no sleep or blocking retry.
When the deadline is reached or `has_more=true`, it yields by returning to
`services.pipeline_jobs.run_sweep_loop`, which schedules the next normal sweep
turn. It never monopolizes an RQ worker or starts an unleased loop/thread.

An enqueue failure leaves the immutable attempt and claim head intact; after
lease expiry a successor real claim is allowed. Deterministic RQ ID
`confident-moment-delivery-<job_uuid>` collapses immediate publish wake-up,
sweep and restart duplicates. The materializer's idempotent terminal check is
still authoritative.

## 5. Deletion and retention edges

Extend the canonical deletion/retention registry with:

```text
materialization job
  -> immutable claim attempts
  -> mutable current claim head
  -> immutable lifecycle events
  -> exact delivery when completed
```

All FKs are `ON DELETE RESTRICT`. Subject deletion/purge invalidates or closes
work through the reviewed RPC traversal; it never hard-deletes provenance out
of order. A concurrently claimed job revalidates deletion after 120→130→140;
deletion winning first yields no attempt/delivery, while claim/materialization
winning first returns only its fully validated prior operation before deletion
proceeds. No resurrection is possible after deletion or terminal closure.

## 6. Required registries and tests

Freeze the D27 registry with these clarifications:

```text
core-v2 caller only:
services/db.py::DatabaseService.get_ideal_text_document_core_v2
  -> read_ideal_text_document_core_v2(text,text)

historical core-v1 caller retained:
services/db.py::DatabaseService.get_ideal_text_document_core
  -> read_ideal_text_document_core_v1(text,text)

scanner/materializer callers and worker start chain:
unchanged from D27
```

Implementation review retains every D20–D27 regression and adds:

1. exact equality of the fourteen snapshot keys and all UUID/text/int/bigint-
   string/object/null/UTC types; extra/missing keys and numeric generation fail;
2. immutable payload/hash remain exact while dynamic owner state changes only
   the read hash;
3. only the core GET calls the dedicated v2 method once; recording-roots,
   enrichment and all frozen legacy callers still use v1 unchanged;
4. publish transaction still returns/strips only the internal job ID and the
   public D14 body remains byte-for-byte unchanged;
5. a job with no eligible later Take can age and be scanned repeatedly while
   producing zero attempt/head/event and never exhausting;
6. first real claim creates attempt 1/head 1; expiry creates immutable attempt
   2 and advances one head; old attempt remains byte-identical;
7. two workers claim the same job concurrently: one opaque job result, one
   active lease, one attempt number and no duplicate enqueue authority;
8. two workers claim several jobs with `SKIP LOCKED` in exact due/UUID order
   without blocking or duplicate ownership;
9. attempts 1–12 are exact; no attempt 13; only one exhausted terminal event;
   age alone and absent target do not advance attempts;
10. completed requires delivery; stale/exhausted forbid it; retry events are
    unique per attempt; only one terminal kind can exist;
11. materializer exact replay, concurrent duplicate execution, expired-lease
    successor and already-terminal replay create at most one delivery/event;
12. boot and recurring sweeps stop within two seconds under a slow enqueue,
    check deadline between jobs, return/yield with `has_more`, never sleep and
    do not kill the general sweep chain;
13. only opaque job UUIDs reach scanner response/RQ/log/metrics/Sentry;
14. deletion in both claim/materialize commit orders closes or preserves one
    fully valid operation and never resurrects; complete traversal includes
    attempts, head, events and delivery;
15. apply/reapply preserves legacy job/events, adds no synthetic attempts,
    creates exact partial uniqueness safely and rolls back all new schema on a
    negative control; and
16. direct runtime writes to attempts/heads/events remain impossible and no
    exposure, response, confidence, adequacy, dataset or learning record is
    fabricated.

## 7. Permissions, gates and stop conditions

New tables are forced-RLS and RPC-only. Scanner/materializer/read v2 are fixed-
search-path and service-role-only; internal helpers remain runtime-inaccessible.
Every Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gate retains its literal disabled default. Attempts, heads, jobs
and events remain `serves_user=false` and `dataset_eligible=false`.

Stop and request review if implementation would:

- use an illustrative or wildcard snapshot projection instead of the exact
  fourteen keys;
- replace the existing v1 method or migrate its unrelated callers;
- count age/no-target polling as a claim attempt or exhaustion;
- mutate/delete an attempt instead of appending its successor;
- expose worker, lease, attempt, principal, Take or raw content in scanner/RQ;
- permit simultaneous live leases, attempt 13, multiple terminal events or a
  completed event without a delivery;
- sweep longer than two seconds, sleep/retry inline or create a second loop;
- drop deletion edges or rewrite historical lifecycle evidence;
- leak the internal publish job ID into D14's public response;
- weaken D27 post-commit dispatch, D25 locks, D24 heads, authority, deletion,
  blindness, RLS or non-learning boundaries;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D28 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
