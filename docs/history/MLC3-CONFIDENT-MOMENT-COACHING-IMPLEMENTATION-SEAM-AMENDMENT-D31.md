# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D31

Status: proposed final non-waiting server scanner closure; executable work
remains blocked pending independent Product, ML/data and Engineering acceptance.

## 1. Parent and sole supersession

D31 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D30.md
SHA-256 e24d81ce5bc2b2683f4826c95b47d1b7d6dbb4dd86db66f669b5784b9d8aae8f
```

D30 and all accepted parents remain authoritative except that D31 removes the
ineffective in-function `statement_timeout` contract and replaces the scanner
server path with a structurally non-waiting, cooperatively budgeted transaction.
D30's client whole-sweep alarm, exact prior-timer arbitration, dedicated
bounded transports, schemas, census, public stripping, permissions and gates
remain unchanged.

## 2. Exact scanner signature and server budget

The exact scanner signature becomes:

```text
claim_due_feedback_language_delivery_jobs_v1(
  p_worker_id text,
  p_limit integer,
  p_lease_seconds integer,
  p_server_budget_ms integer
) -> jsonb
```

`p_server_budget_ms` is server-owned operational input derived from D30's
remaining client budget and must be in `1..1500`. The browser never supplies
it. `p_limit` is bounded to `1..25`; the scanner can return fewer.

At the first PL/pgSQL statements, before any table read, relation/row lock,
helper or advisory lock, the function validates scalar arguments and sets:

```sql
PERFORM set_config(
  'lock_timeout',
  LEAST(25, GREATEST(1, p_server_budget_ms / 10))::text || 'ms',
  true
);
```

This transaction-local `lock_timeout` bounds relation/table/row lock waits. It
does not claim to bound computation and is not a substitute for the D30 client
alarm. D31 sets no in-function `statement_timeout`: PostgreSQL fixes statement
timeout when a statement begins, so changing it inside that same function is
not accepted evidence.

The function freezes:

```text
server_started_at = clock_timestamp()
server_cutoff_at = server_started_at
  + make_interval(secs => p_server_budget_ms::double precision / 1000.0)
```

Before and after every candidate query, candidate, serializer phase, helper,
row-lock phase, eligibility revalidation, attempt insert, head mutation and
response build, it checks `clock_timestamp() < server_cutoff_at`. On expiry it
raises exact typed
`CONFIDENT_MOMENT_DELIVERY_SCAN_SERVER_BUDGET_EXCEEDED`; the transaction and
all claim attempts/heads/events roll back. It never returns a partial list.

## 3. Structurally non-waiting candidate path

### 3.1 Indexed bounded discovery

The due-candidate query is served by checksum-pinned indexes covering the exact
non-terminal/pending job state and deterministic `(eligible_due_at, job_id)`
order, plus existing/source-Take Project/principal indexes needed to prove one
eligible later Take. The query:

- considers no more than 25 rows;
- orders exact oldest eligible due time then UUID bytes;
- requires an actually existing eligible later Take before a row is a claim
  candidate;
- uses `FOR UPDATE OF job SKIP LOCKED`; and
- never performs an unindexed open-ended scan, recursive search or content
  query.

Absence of an eligible later Take remains no claim/attempt/exhaustion. The
query plan is captured in a production-shaped `EXPLAIN` regression and the
registry pins the expected index identities. A missing/drifted index blocks
migration closure.

### 3.2 Advisory serializers are try-locks only

For the scanner call graph only, every applicable D11/D25 advisory serializer,
including delivery-subject position 120 and revision-head position 130, uses:

```sql
pg_try_advisory_xact_lock(hashtextextended(exact_lock_string, 0))
```

The complete server-derived lock sets retain D11/D25 ordering. Failure to
obtain any exact lock skips that candidate with no attempt/head/event mutation;
it does not wait, spin, sleep, retry inline, acquire later locks for that
candidate, or reorder around the conflict. Acquired transaction locks remain
held only until the bounded scanner transaction returns/rolls back.

Existing blocking writer locks remain authoritative. The scanner's try-lock
uses the same exact hash/string, so a live writer makes the scanner skip rather
than observe unstable state. A scanner-only helper may wrap try-lock behavior,
but it must be internal, boolean-returning, free of mutation before complete
lock success and runtime-inaccessible.

### 3.3 Row/currentness locks

At position 140 every job/head/attempt/revision/delivery validity row that may
be contended is selected through one of:

- the already claimed candidate row from `FOR UPDATE SKIP LOCKED`;
- an exact-key `FOR UPDATE ... SKIP LOCKED`; or
- an immutable/plain snapshot read performed only after its shared advisory
  serializer is held.

No scanner query uses `FOR UPDATE`, `FOR SHARE`, `FOR NO KEY UPDATE` or
`FOR KEY SHARE` without `NOWAIT`/`SKIP LOCKED` as semantically applicable.
A missing/skipped current row skips the candidate before mutation. After all
locks, the scanner rederives exact target Take, revision, authority, deletion,
terminal event, lease state and attempt number before appending one claim.

Constraint/index/FK enforcement remains subject to the transaction-local
`lock_timeout`; a lock timeout yields the canonical typed scan failure and
atomic rollback, not a partial claim.

## 4. Closed scanner SQL call graph

Before implementation, freeze an exhaustive transitive SQL call graph rooted
at
`claim_due_feedback_language_delivery_jobs_v1(text,integer,integer,integer)`.
Each row records exact `to_regprocedure` identity, volatility, tables/indexes,
locks and disposition.

Every reachable helper must be one of:

1. immutable/STABLE exact-key or indexed bounded read with no lock acquisition;
2. D31 scanner-only `pg_try_advisory_xact_lock` helper;
3. exact `NOWAIT`/`SKIP LOCKED` row-currentness helper; or
4. bounded claim mutation reached only after the complete lock set and final
   budget check.

The scanner may not transitively call the released blocking
`require_mlc3_service_access_v2` or any other helper containing
`pg_advisory_xact_lock`. Its needed dual-purpose/current-authority predicate is
provided by an audited scanner-only read validator executed after the exact
rollout/principal try-locks. The validator must reproduce—not weaken—the
canonical authority, purpose, receipt/policy, enrollment, deletion and rollout
predicate.

Closure fails if any reachable SQL body contains or can dynamically execute:

- blocking `pg_advisory_xact_lock`;
- row lock without exact `NOWAIT`/`SKIP LOCKED` handling;
- `LOCK TABLE` or explicit heavyweight lock;
- `pg_sleep` or busy/retry loop;
- dynamic SQL not matched to a closed constant template;
- `dblink`, HTTP/network/file/program extension call;
- unbounded recursive/aggregate/content scan;
- a helper absent from the exact registry; or
- an exception handler that swallows lock/budget failure and commits partial
  mutation.

Static `pg_get_functiondef` inspection, dependency extraction and executable
negative-control functions prove this transitive closure. Proname-only matching
is insufficient.

## 5. Client cancellation and bounded server lifetime

D30's one `monotonic_deadline_scope` still wraps bounded DB transport, claim
response validation, all enqueues, cleanup and return. The transport sends
`p_server_budget_ms` no greater than the exact remaining adapter budget minus
the reserved cleanup margin and retains connect/read/write/pool timeouts.

If the client alarm cancels or loses the HTTP request, the PostgreSQL backend
may briefly outlive the client only until its earlier `server_cutoff_at` check
or transaction-local lock timeout. It holds no **waited-for** advisory/row lock:
all advisory acquisition was try-only and row candidates were skip/nowait.
It may temporarily hold locks it successfully acquired, but releases all of
them when its transaction returns or raises the typed budget error.

The backend may not commit later after the caller has timed out unless its full
claim transaction had already committed before transport cancellation. That
uncertain-success case is safe and bounded by the immutable attempt/lease plus
deterministic RQ/materializer replay. Cancellation during any uncommitted phase
must roll back and release every acquired lock; a later scanner may then claim
normally.

The application does not retry the claim RPC inside the same sweep. It yields
to the existing leased sweep chain.

## 6. Registry and migration changes

Replace D30's scanner registry identity with:

```text
claim_due_feedback_language_delivery_jobs_v1(text,integer,integer,integer)
```

where the fourth parameter is named and semantically
`p_server_budget_ms`, not statement timeout. Register every scanner-only
try-lock/current-authority helper and every exact index. The AST caller remains
`sweep_due_confident_moment_deliveries` and must pass the derived server budget;
no other production caller is allowed.

Migration apply/reapply order adds indexes and scanner-only helpers before the
public scanner replacement, runs the complete SQL call-graph/plan/permission
audit, and removes no accepted writer lock. Any closure failure rolls the
scanner/index/helper changes back atomically. All new helpers have EXECUTE
revoked from `PUBLIC`, `anon`, `authenticated` and `service_role`; only the
service-role scanner is public to the application.

## 7. Required executable regressions

Retain every D20–D30 regression and add:

1. hold each exact advisory serializer in connection A; connection B scanner
   returns/skips within budget with zero attempt/head/event and no wait;
2. hold candidate job/head/revision/delivery row locks in A; B uses skip/nowait,
   returns within budget and creates no partial claim;
3. hold a relation-level lock that conflicts with scanner access; exact
   transaction-local `lock_timeout` fires in at most the frozen bound and rolls
   back every scanner mutation;
4. prove `lock_timeout` is set before the first relation read/lock through body
   audit and a real first-relation lock-wait test;
5. force cooperative cutoff before discovery, between every serializer phase,
   after final validity and after an attempted insert; each raises the exact
   budget code and leaves zero committed attempt/head/event;
6. production-shaped `EXPLAIN` uses every pinned candidate/eligibility index,
   reads at most 25 candidates and preserves due/UUID order;
7. exhaustive transitive call-graph audit contains no blocking advisory lock,
   unqualified row lock, sleep/network/dynamic/unbounded operation or unknown
   helper;
8. negative helper with blocking `pg_advisory_xact_lock`, `FOR UPDATE` without
   skip/nowait, `pg_sleep` or hidden dynamic call independently fails closure;
9. scanner-only authority validator matches canonical dual-purpose results for
   active, revoked, deleted, stale policy/receipt, wrong enrollment and halted
   rollout fixtures without calling a blocking helper;
10. cancel the client during discovery, try-lock phases, row phase and after a
    staged attempt insert; wait beyond server budget and prove zero later
    uncommitted claim appears and every advisory/row lock is released;
11. uncertain cancellation after an already committed claim yields exactly one
    durable attempt/head, later deterministic enqueue/materialization remains
    idempotent, and no second claim exists before lease expiry;
12. client blocking-claim regression plus server cutoff completes the whole
    sweep under two seconds without a late database commit;
13. two scanners under forced mixed contention skip locked work, claim distinct
    eligible jobs in exact order, never deadlock/spin and later recover skipped
    jobs; and
14. apply/reapply and negative rollback preserve D29 legacy event/head schemas,
    all gates and structural non-learning constraints.

Tests must observe real PostgreSQL locks through two connections; mocks alone
cannot satisfy the server non-waiting claim.

## 8. Permissions, gates and stop conditions

D30 permissions remain. The server-budget parameter and scanner helpers are
operations-only and never browser-visible. No job content or principal data is
returned or logged.

All Bundle, rooting, PAM, serving, collection, dataset, training, evaluation
and promotion gates retain literal disabled defaults.

Stop and request review if implementation would:

- set `statement_timeout` from inside the already-running scanner statement;
- use blocking advisory locks or blocking row locks anywhere in the transitive
  scanner call graph;
- call the released blocking authority resolver rather than the audited
  equivalent scanner validator after exact try-locks;
- scan more than 25/unindexed candidates, retry/spin/sleep inline, or ignore a
  cooperative server cutoff;
- let a cancelled uncommitted transaction commit later or retain locks beyond
  its server budget;
- weaken D30 client alarm/prior-timer rules, D29 schemas, D28 claim lifecycle,
  D27 public stripping, D25 ordering, authority, blindness, RLS or non-learning
  boundaries;
- change a disabled gate; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D31 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
