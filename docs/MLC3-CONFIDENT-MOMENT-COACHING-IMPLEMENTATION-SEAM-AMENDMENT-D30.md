# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D30

Status: proposed final whole-sweep deadline and signal-arbitration closure;
executable work remains blocked pending independent Product, ML/data and
Engineering acceptance.

## 1. Parent and narrow supersession

D30 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D29.md
SHA-256 dec474c2d52d9d6f6c30ceb1889bdf97a41577460ef70792bdb3f248dccf44c6
```

D29 and all accepted parents remain authoritative except where D30 replaces
the enqueue-only alarm with one whole-sweep deadline covering claim, validation,
every enqueue and return, and pins exact arbitration with any pre-existing
`SIGALRM`. D29's exact schemas, timestamp, legacy boundary, public stripping,
permissions, deletion graph and disabled/non-learning rules remain unchanged.

## 2. One whole-sweep deadline

### 2.1 Scope

At the first executable line of
`sweep_due_confident_moment_deliveries`, before a database or Redis call:

```text
sweep_started = time.monotonic()
adapter_deadline = sweep_started + 1.900
hard_return_deadline = sweep_started + 2.000
```

One D30 alarm scope covers, in order:

1. construction of the bounded database transport;
2. `claim_due_feedback_language_delivery_jobs_v1` execution;
3. response read and recursively closed validation;
4. each bounded Redis/RQ enqueue;
5. cleanup/disconnection; and
6. return to `services.pipeline_jobs.run_sweep_loop` or the worker boot caller.

The function makes at most one claim RPC and claims at most 25 jobs. Before
every potentially blocking operation it recomputes exact remaining monotonic
budget. At/after `adapter_deadline` it begins no I/O. The reserved 100 ms is
only for deterministic cancellation cleanup and Python return. Exceeding
`hard_return_deadline` is a failed regression, never an acceptable retry.

The exact reusable scope is:

```text
services/confident_moment_delivery_worker.py::
  monotonic_deadline_scope(deadline_monotonic)
```

`sweep_due_confident_moment_deliveries` enters this scope once around the full
claim→validate→enqueue→cleanup→return body. It never enters a nested deadline
scope per database or Redis operation.

### 2.2 Bounded claim RPC

D30 extends the exact scanner signature to:

```text
claim_due_feedback_language_delivery_jobs_v1(
  p_worker_id text,
  p_limit integer,
  p_lease_seconds integer,
  p_statement_timeout_ms integer
) -> jsonb
```

Immediately on entry, before discovery, row/advisory locks or scans,
PostgreSQL validates `p_statement_timeout_ms` in `1..1500` and calls:

```sql
PERFORM set_config(
  'statement_timeout',
  p_statement_timeout_ms::text || 'ms',
  true
);
```

The application derives it as:

```text
floor(min(1500ms, max(1ms, remaining_adapter_budget_ms - 100ms)))
```

The setting is transaction-local and callers cannot disable it. A statement
timeout rolls back any attempted claim/head/attempt changes atomically and is
reported only as bounded scanner failure.

The sweep creates a dedicated, non-cached PostgREST/Supabase transport using
the already-reviewed service endpoint and service-role credential provider.
Connect, pool, write and read timeouts are each set to the exact remaining
adapter budget at the moment the transport/request is created; library retries
are disabled. The transport is disconnected in `finally`, never stored in the
global `DatabaseService`/Supabase client and never shared with the worker's
normal DB session. The outer signal scope remains the hard bound if DNS,
transport or library cleanup ignores its configured timeout.

The scanner response remains D29's opaque job-ID-only schema. Timeout/error
returns no application-visible partial claim result; any database transaction
that committed before an uncertain transport timeout remains safe because the
lease expires and deterministic RQ/materializer identity is idempotent.

### 2.3 Bounded enqueue inside the same scope

D29's `enqueue_with_monotonic_deadline` keeps the dedicated non-cached Redis
connection, disabled retries, exact deterministic RQ ID and remaining-budget
socket/connect timeouts, but **does not install its own signal handler**. It
receives the already-active absolute `adapter_deadline`; the D30 outer scope is
the sole alarm owner for claim plus all enqueues.

It recomputes remaining time before connection and enqueue, returns false
without I/O when exhausted, and disconnects in `finally`. A failed/uncertain
enqueue leaves the durable claim recoverable. No ordinary cached
`job_queue.enqueue` call occurs inside the sweep.

## 3. Exact `SIGALRM` arbitration

### 3.1 Eligibility and workhorse context

Before I/O, the outer deadline helper requires:

- `os.name == 'posix'`;
- `signal.SIGALRM`, `signal.ITIMER_REAL`, `signal.getitimer` and
  `signal.setitimer` are available;
- `threading.current_thread() is threading.main_thread()`; and
- one exact registered execution context:
  - recurring: `rq.get_current_job()` is locally available, has exact function
    name `services.pipeline_jobs.run_sweep_loop`, and its ID matches RQ's
    current workhorse execution context; or
  - boot: `worker.py::main` supplies the private in-process singleton
    `_CONFIDENT_MOMENT_BOOT_SWEEP_TOKEN` imported from the delivery-worker
    module, while no RQ current job exists. Equality is object identity, the
    token is never serialized/configured/exported, and the AST caller registry
    permits this argument only at the exact worker boot call.

Any other process, function, thread, platform or caller returns bounded
`unsupported_deadline_context` before database/Redis I/O. It never falls back
to an unbounded sweep. `rq.get_current_job` must use already-established local
workhorse context and may not perform network I/O for this check.

### 3.2 Prior-timer census

The helper snapshots:

```text
prior_handler = signal.getsignal(SIGALRM)
(prior_remaining, prior_interval) = signal.getitimer(ITIMER_REAL)
snapshot_monotonic = time.monotonic()
```

A non-zero `prior_interval` is periodic and unpreservable; the sweep returns
`unsupported_periodic_alarm` before I/O and changes no handler/timer.
`SIG_IGN`, an unknown/non-callable non-default handler, negative/non-finite
timer values, or a prior timer without a preservable handler is likewise
rejected before I/O. No integer `signal.alarm()` call is allowed; all durations
use floating-point `getitimer/setitimer` with subsecond fidelity.

No prior timer means the adapter deadline owns the alarm. A positive one-shot
timer defines:

```text
prior_deadline = snapshot_monotonic + prior_remaining
armed_deadline = min(adapter_deadline, prior_deadline)
```

Exact equality is won by the prior timer, not the adapter.

### 3.3 Dispatch rule

Install one private arbitration handler and arm `ITIMER_REAL` for the
non-negative floating-point duration to `armed_deadline`.

When it fires, it compares the frozen deadlines and current monotonic time:

- **adapter wins strictly earlier:** raise the private
  `ConfidentMomentSweepDeadline` sentinel;
- **prior wins earlier or equal:** dispatch the frozen prior handler with the
  original `SIGALRM` number and current frame, unchanged.

For a callable prior handler, call that exact object. If it raises, its exact
exception propagates untouched; no D30 `except` catches, wraps, logs as a
scanner failure or translates it. If it returns, raise private
`PriorAlarmReturned` after the call; that sentinel also propagates outside the
sweep rather than being translated.

For `SIG_DFL`, restore `SIG_DFL` and immediately re-deliver `SIGALRM` to the
current PID so the operating-system default behavior occurs. `SIG_IGN` was
already rejected. Thus D30 never swallows or changes prior alarm ownership.

Only `ConfidentMomentSweepDeadline` from the exact installed D30 handler is
caught by the sweep, causing bounded false/timeout result and cleanup. Broad
`Exception`/`BaseException` handlers may not encompass prior dispatch.
`ConfidentMomentSweepDeadline` is a private direct `BaseException` subclass,
not an `Exception`, so ordinary HTTP/Redis/database library error handlers
cannot swallow the whole-sweep cancellation. The owning sweep catches it by
exact class outside all transport calls; no other `BaseException` is caught.

### 3.4 Restoration and cleanup overrun

In `finally`, first disarm D30 with `setitimer(ITIMER_REAL, 0.0, 0.0)`, then
restore the exact prior handler. If there was a prior one-shot timer, compute:

```text
restored_remaining = prior_deadline - time.monotonic()
```

- when positive, restore it with
  `setitimer(ITIMER_REAL, restored_remaining, 0.0)`;
- when zero/negative because operation or cleanup crossed its deadline,
  dispatch the prior handler immediately under section 3.3 instead of
  cancelling, resetting or rounding the alarm.

The prior duration is never restored to its original unadjusted value and
therefore is never extended. The prior interval remains exactly zero. Cleanup
tracks whether prior dispatch already occurred and never delivers it twice.
Handler/timer restoration is attempted even after the D30 sentinel; a failure
to restore is fatal to the RQ workhorse and cannot be reported as ordinary
enqueue failure.

After cleanup, the sweep checks `time.monotonic()`. It must return before the
two-second hard deadline. Any cleanup path that could block uses only local
pool/socket close and must be demonstrably bounded/nonblocking; it does not
wait for remote acknowledgement.

## 4. Pre-implementation production-shape census

Before executable edits are frozen, run read-only census queries against the
exact disposable production-shaped schema and record counts plus a canonical
result hash for:

1. `ideal_text_document_snapshots` with empty `arc_id`;
2. snapshots with empty `actor_id`;
3. every existing delivery materialization event kind/nullable extension
   shape; and
4. jobs with contradictory terminal histories under D29's new partial unique
   rule.

The census is evidence, not an activation or migration mutation. Empty
identifier rows remain typed fail-closed and unchanged. Existing events remain
grandfathered exactly as D29 requires whether the frozen local base count is
zero or non-zero. Migration apply/reapply tests must include both a zero-row
fixture and a populated valid-legacy fixture; absence in a pending/unreleased
local migration is not evidence that production can never contain rows.

An invalid populated shape aborts migration preparation and requires explicit
review; code may not delete or normalize it silently.

## 5. Registry changes

Freeze the scanner identity as:

```text
claim_due_feedback_language_delivery_jobs_v1(text,integer,integer,integer)
```

and retain the exact caller:

```text
services/confident_moment_delivery_worker.py::
  sweep_due_confident_moment_deliveries
  -> claim_due_feedback_language_delivery_jobs_v1
```

Add exact internal call edges for the outer deadline context and the bounded
DB/Redis adapters. Static checks reject the prior three-argument scanner, a
shared/default DB transport, ordinary queue enqueue, nested signal owner,
integer alarm, periodic timer mutation, broad catch around prior dispatch, or
any caller/context outside the two registered worker seams.

The exact outer call edge is:

```text
services.confident_moment_delivery_worker.py::
  sweep_due_confident_moment_deliveries
  -> monotonic_deadline_scope
```

All scanner claim decisions still acquire D28's exact 120→130→140 order and
D25 locks where applicable. Timeouts never weaken database serialization.

## 6. Required executable regressions

Retain every D20–D29 regression and add:

1. blocking claim-RPC transport is interrupted and the complete sweep returns
   under two seconds with no application-visible partial response;
2. PostgreSQL statement timeout fires before its supplied bound, rolls back a
   forced partially attempted claim, and accepts only `1..1500`;
3. dedicated DB connect/read/write/pool timeouts derive from remaining budget,
   retries are disabled and shared DB clients are untouched;
4. slow closed-response validation plus slow enqueue remain inside the one
   whole-sweep deadline; no second I/O starts after 1.9 seconds;
5. no prior timer: adapter deadline fires, only its exact sentinel is caught,
   handler/timer are cleared and the sweep returns under two seconds;
6. prior timer sooner than adapter: exact prior callable fires at its original
   deadline; its exact custom exception escapes unchanged;
7. prior timer later than adapter: adapter times out first, then prior timer is
   restored with elapsed-adjusted subsecond remaining and fires at the original
   absolute deadline;
8. exactly equal prior/adapter deadlines choose and dispatch the prior handler;
9. a callable prior handler that returns causes `PriorAlarmReturned` to escape;
   one that raises an arbitrary `BaseException` is not caught/translated;
10. prior `SIG_DFL` is re-delivered with default semantics in an isolated child
    test; `SIG_IGN`, periodic timer and malformed/unpreservable timer states
    reject before DB/Redis calls;
11. cleanup crossing the prior deadline dispatches it immediately once; cleanup
    before it restores exact float remaining; no path extends, rounds, cancels
    or double-delivers the prior timer;
12. non-main-thread, non-POSIX, wrong RQ function/job context and invalid boot
    token each perform zero I/O; exact recurring and boot contexts pass;
13. bounded Redis adapter installs no nested alarm and uncertain timeout still
    converges on deterministic RQ ID;
14. zero-event and populated-valid-legacy apply/reapply fixtures both preserve
    history; invalid terminal census blocks atomically; and
15. empty historical arc/actor census produces no mutation and v2 read remains
    typed `CONFIDENT_MOMENT_PROJECTION_INVALID`.

Signal tests use isolated processes where default delivery or RQ alarm behavior
could terminate the runner. Wall-time assertions include platform tolerance
strictly below the two-second contract, not a five-second socket fallback.

## 7. Permissions, gates and stop conditions

D29 permissions remain unchanged. The statement-timeout argument is bounded
operational control, not browser input; the route never supplies it. Dedicated
transports use existing secret providers and never log credentials or content.

All Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gates retain literal disabled defaults.

Stop and request review if implementation would:

- start the deadline after the claim call or exclude validation/return;
- rely on PostgreSQL timeout, HTTP timeout or Redis timeout without the whole-
  scope outer cancellation boundary;
- arm only the adapter deadline when a prior alarm is earlier/equal;
- catch, wrap or translate an exception from the prior handler;
- restore an unadjusted/rounded timer, accept a periodic timer, swallow
  `SIG_DFL`, or use process-wide signals from a non-main thread;
- use an unregistered web/worker context or shared DB/Redis connection;
- assume zero legacy rows without the production-shape census and both fixture
  families;
- weaken D29 event/head constraints, D28 claim/deletion semantics, D27 public
  stripping, D25 locks, authority, blindness, RLS or non-learning boundaries;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D30 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
