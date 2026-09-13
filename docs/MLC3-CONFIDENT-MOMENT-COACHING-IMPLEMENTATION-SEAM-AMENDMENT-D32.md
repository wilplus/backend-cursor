# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D32

Status: proposed final Option-B bounded-scanner contract; executable work
remains blocked pending independent Product, ML/data and Engineering acceptance.

## 1. Parent, explicit choice and scope

D32 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D31.md
SHA-256 4028a4cebbfb3c56844cc688338d2e361ded31842955aa0ac1bc7096cb7b159c
```

D32 explicitly chooses **Engineering Option B**:

- the client/worker sweep has a hard return bound of at most two seconds;
- the PostgreSQL scanner has no lock-wait path and may not commit after its
  server cutoff;
- a currently executing bounded SQL phase is not claimed to be preemptible;
  it may briefly outlive both the client cancellation and cooperative cutoff,
  retaining locks it already acquired until that phase returns and the
  transaction performs its mandatory cutoff rollback; and
- the scanner handles at most one candidate per call to minimize that bounded
  residual exposure.

D31 and all accepted parents remain authoritative except where D32 narrows the
batch to one and corrects any claim that cooperative checks guarantee immediate
server return/lock release. This changes no product, evidence, authorization,
dataset or learning meaning.

## 2. Exact two-bound contract

### 2.1 Client hard bound

D30's `monotonic_deadline_scope` continues to wrap the complete client sweep:
bounded database transport, claim RPC, validation, enqueue, cleanup and return.
It begins at function entry, uses the accepted prior-`SIGALRM` arbitration, has
an adapter deadline of 1.900 seconds and must return/yield before 2.000 seconds.

Transport cancellation at that deadline is sufficient for the client hard
bound. The worker never waits for PostgreSQL cancellation acknowledgement,
polls a backend PID, sleeps or retries inline. It returns to the one existing
leased sweep chain.

### 2.2 Server non-waiting and no-post-cutoff-commit bound

The scanner retains D31's `p_server_budget_ms` (`1..1500`) and first-statement
transaction-local `lock_timeout`, now bounded by:

```text
1ms <= lock_timeout <= 100ms
lock_timeout <= p_server_budget_ms
```

All advisory serializers remain `pg_try_advisory_xact_lock`; all contended job
and validity rows remain exact `SKIP LOCKED`/`NOWAIT`; no helper may introduce a
blocking lock, sleep, network call or retry loop.

The scanner checks `clock_timestamp()` against its frozen cutoff before and
after every bounded SQL phase. Most importantly, it performs one **final cutoff
check after every read/write phase and immediately before constructing the
success response/allowing transaction commit**. If the cutoff is reached or
passed, it raises
`CONFIDENT_MOMENT_DELIVERY_SCAN_SERVER_BUDGET_EXCEEDED`; all attempt/head/event
changes roll back. There is no exception handler that converts this into a
committable partial response.

Therefore a scanner transaction may not commit after its own cutoff. It may,
however, remain active after cutoff while a bounded non-lock SQL statement that
started before cutoff finishes. During that interval it may retain advisory or
row locks it successfully acquired earlier. D32 does not misrepresent a
cooperative deadline as statement preemption. When the phase returns, the next
cutoff check forces rollback and releases all locks.

An uncertain client timeout after a transaction that committed **before** the
server cutoff remains D28's idempotent lease case. A transaction not committed
before cutoff can never commit later.

## 3. One candidate, indexed O(1) work

### 3.1 Scanner limit

The exact scanner retains its four-argument signature, but validates:

```text
p_limit = 1
```

The application always supplies `1`. Any other value fails before relation
access. The closed response has zero or one `jobs` item. `has_more=true` means
only that another eligible indexed candidate may remain; it never causes a
second candidate pass in the current call.

### 3.2 Closed SQL phases

Every scanner phase is checksum-pinned and bounded to indexed point/single-row
work:

1. one due-candidate index probe in exact `(eligible_due_at,job_id)` order with
   `LIMIT 1 FOR UPDATE SKIP LOCKED`;
2. exact primary/unique/FK index lookups for that job's attachment, revision,
   claim head, latest attempt, terminal event, source Take and one earliest
   eligible later Take;
3. complete server-derived advisory identity arrays whose cardinality is
   bounded by the one candidate's closed lineage, then try-lock acquisition in
   D11/D25 order;
4. exact-key current authority/deletion/revision/target checks;
5. at most one attempt insert and one claim-head insert/update; and
6. one final exact revalidation and cutoff check.

No phase performs a scan, aggregate, window, sort or recursive traversal over
an unbounded set. Required ordering is satisfied by the pinned indexes; an
explicit unbounded `Sort` plan blocks implementation. There is no volatile
external/extension call. `clock_timestamp`, UUID/hash construction and the
closed local claim mutations are the only accepted volatile operations.

The complete transitive SQL call-graph audit from D31 remains mandatory and
adds per-phase maximum row/cardinality and index identity. A missing index,
sequential scan over a non-constant-size relation, dynamic SQL, user-defined
volatile helper outside the registry, content aggregation or plan drift blocks
migration closure.

## 4. Worker continuation across sweep turns

After a zero/one-item result, one enqueue attempt, `has_more=true`, timeout or
failure, the function returns/yields. It does not call the scanner again in the
same `run_sweep_loop` turn. The existing leased recurring sweep invokes it on a
later scheduled turn, so backlog drains one eligible job per turn without
extending a workhorse invocation.

The immediate post-publish enqueue remains unchanged. Deterministic RQ job ID,
lease expiry and idempotent materialization preserve correctness under slow
drain or uncertain cancellation. Capacity/backlog is operational health, not a
quality/effectiveness label.

## 5. Duration monitoring and automatic disable

The dedicated scanner transport sets exact, content-free application name:

```text
mlc3-confident-moment-delivery-scanner-v1
```

The existing aggregate-only general-service monitor adds:

- count and maximum duration of scanner transactions from `pg_stat_activity`;
- count of client sweep hard-deadline cancellations;
- count of typed server-budget rollbacks; and
- pending/leased/exhausted job counts and oldest age.

No Project, principal, Take, candidate, wording, transcript, audio, media or job
UUID appears in metrics, logs, alerts or Sentry tags.

The versioned automatic stop rule is:

```text
policy: confident-moment-delivery-scanner-circuit-breaker-v1
halt when either:
  - any scanner transaction remains active for > 5 seconds; or
  - >= 3 client hard-deadline cancellations occur in any rolling 5 minutes.
action:
  invoke the already-reviewed halt_mlc3_service_rollout_v1 path once,
  verify rollout/service gates disabled, alert Sentry + operations,
  and do not auto-resume.
```

The monitor uses exact deployment-bound configuration and its existing
authorized operations caller. Duplicate observations exactly replay one halt.
Re-enablement requires a separate reviewed founder decision; the monitor cannot
activate a rollout.

A server budget rollback that completes after client cancellation increments
only an aggregate late-rollback counter. Failure to observe its completion by
five seconds satisfies the first halt condition. This monitoring does not
authorize killing a PostgreSQL backend, deleting a job or treating duration as
product/ML evidence.

## 6. Required executable regressions

Retain every D20–D31 regression except any assertion of immediate server
preemption, and add:

1. `p_limit` values 0, 2, 25 and null fail before table access; exact 1 returns
   zero/one opaque job and truthful `has_more`;
2. production-shaped `EXPLAIN` proves one index candidate probe plus only
   indexed O(1) point lookups, with no unbounded scan/aggregate/sort/recursion;
3. every advisory conflict returns immediately through try-lock and every row
   conflict skips/nowaits within the <=100ms relation-lock bound;
4. a deliberately slow **non-lock** SQL phase begins before server cutoff,
   outlives client cancellation and cutoff, then reaches the final check,
   rolls back and never commits an attempt/head/event;
5. during that slow phase, a previously acquired lock may remain observable;
   after rollback/return it is released and a fresh scanner can claim;
6. poll past the slow phase and prove no late commit appears at any later time;
7. a transaction completing all phases before cutoff commits exactly once even
   if the client loses the response; lease/idempotent replay remains exact;
8. final cutoff is textually/executably after the last mutation and before
   success response; removing it causes a negative test to fail closure;
9. worker processes no second scanner call in one turn when `has_more=true`,
   yields under two seconds, and a later sweep turn claims the next job;
10. a multi-job backlog drains one per turn in indexed due/UUID order without
    duplicate leases or workhorse starvation;
11. monitor detects one >5-second active scanner and three cancellations/5min,
    invokes one exact halt, verifies disabled state and never auto-resumes;
12. sub-threshold duration/cancellation does not halt; aggregate receipts contain
    no identifying/content data; and
13. apply/reapply/static call-graph negative controls retain D29 schemas,
    D31 non-waiting locks and all structural non-learning gates.

The slow-phase test uses a test-only checksum-pinned helper/fixture unreachable
to runtime roles; production SQL remains free of sleep/external calls.

## 7. Permissions, gates and stop conditions

D31 permissions remain. The circuit breaker can only disable through the
already-reviewed operations path and cannot enable anything. All Bundle,
rooting, PAM, serving, collection, dataset, training, evaluation and promotion
gates remain literally disabled in this preparation scope.

Stop and request review if implementation would:

- promise immediate server cancellation/lock release at the cooperative cutoff;
- permit commit without the final post-mutation cutoff check;
- process more than one candidate/scanner call or loop again in one sweep turn;
- use an unindexed/unbounded scan, aggregate, sort, recursive query, blocking
  lock/helper, sleep/retry or volatile external call;
- set lock timeout above 100 ms or use it as the only client bound;
- omit aggregate late-duration monitoring or automatic rollout halt at the
  frozen threshold;
- kill a backend/delete history or auto-resume after the circuit breaker;
- weaken D31 SQL closure, D30 client alarm, D29 schemas, D28 lifecycle, D27
  public stripping, D25 locks, authority, blindness, RLS or non-learning rules;
- change an activation/learning gate except the authorized automatic disable;
  or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D32 OPTION B PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
