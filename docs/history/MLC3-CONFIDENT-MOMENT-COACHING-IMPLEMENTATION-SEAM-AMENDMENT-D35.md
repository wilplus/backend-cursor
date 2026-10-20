# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D35

Status: proposed narrow scanner-progression and Take-arm correction; executable
work remains blocked pending independent Product, ML/data and Engineering
acceptance.

## 1. Parent and exact supersession

D35 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D34.md
SHA-256 45a58dbab48ee4f764f34b9cce3fff3077b36b1d0656ecccdef06c83442c7ec5
```

All D34 and inherited D20–D33 clauses remain authoritative except the two
mechanisms replaced below. Product, evidence, authorization, deletion,
dataset, learning and disabled-gate semantics do not change.

## 2. Bounded due-row progression

### 2.1 Exact scanner contract

The scanner RPC retains D34's exact named partial index
`feedback_language_delivery_due_pending_idx`, but replaces first-row `NOWAIT`
selection with one bounded ordered query:

```sql
SELECT job_id
FROM public.feedback_language_delivery_job_due_heads
WHERE scheduling_state='pending'
  AND next_probe_at <= :exact_probe_cutoff
ORDER BY next_probe_at,job_id
FOR UPDATE SKIP LOCKED
LIMIT 3;
```

The public/internal signature has exact `p_limit integer`; only literal `3` is
valid. Null, boolean-equivalent, zero, negative, two, four or any other value
fails before selection. The response contains zero through three item results
in the exact locked index order. There is one query, no re-probe, no pagination,
no loop that discovers a fourth due row and no second scanner call within the
same sweep turn.

Each returned row then follows the inherited D31–D34 non-waiting advisory-lock,
currentness, no-target, claim and terminal transitions. A contended row skipped
by PostgreSQL is neither read nor mutated. A later scheduled turn retries it.
The query plan must use `feedback_language_delivery_due_pending_idx`, with no
explicit sort or sequential scan.

### 2.2 Contention is alert-only

D35 removes D34's `skipped_contention` circuit breaker and its impossible
stalled-scan halt-receipt path. Lock contention, skip counts and oldest pending
age are aggregate operations telemetry and may alert Sentry/operations, but
they never call either halt RPC by themselves.

The sole Confident Moment delivery-scanner automatic-halt predicate remains:

```text
scanner_started_at IS NOT NULL
AND finished_at IS NULL
AND scanner_started_at < observation_cutoff - interval '5 seconds'
```

`get_mlc3_general_service_monitor_v2` therefore returns contention telemetry
separately from `hard_stop`; contention cannot make `hard_stop=true`.
`halt_mlc3_for_stalled_delivery_scan_v1` accepts/rederives only the exact sorted
set of scanner-bound unfinished runs older than five seconds. Its convergence
key and receipt never encode contention-only observations. Begun-only and
`abandoned_before_scan` runs remain non-halting as D34 requires.

## 3. Canonical post-promotion Take arm

### 3.1 One authoritative success seam

Remove D34's unconditional arm from
`routes/v2/lab_recording.py::_persist_lab_take`: on the frozen base that
function durably stores/finalizes a recording attempt but does not create the
canonical successful Take. Arming there would wake jobs for failed or still-
processing attempts.

The exact arm occurs as post-commit best effort only after
`DatabaseService.promote_recording_attempt_to_take` receives and validates a
successful `promote_recording_attempt_to_take_v1` response containing the exact
`take_id`. It calls:

```text
services.confident_moment_delivery_worker::
  arm_confident_moment_deliveries_for_take(take_id, promotion_idempotency_key)
  -> arm_feedback_language_delivery_jobs_for_take_v1(uuid,text)
```

The arm idempotency preimage is the fixed contract namespace, exact returned
Take UUID and exact promotion idempotency key. The browser, worker payload and
route cannot choose or substitute a Take ID. Failure is captured as aggregate
operational error and cannot roll back, fail, duplicate or reinterpret the
already committed Take; D34's exponential due probe remains the missed-wake
backstop.

### 3.2 Closed current call graph

The frozen production callers reaching this DatabaseService promotion seam are:

```text
services/lab_analysis_dispatch.py::dispatch_recording_analysis
  -> local record_completion
  -> services.take_lifecycle::complete_attempt
  -> services.take_lifecycle::promote_attempt
  -> DatabaseService.promote_recording_attempt_to_take

services/pipeline_jobs.py::_complete_job_attempt
  -> services.take_lifecycle::complete_attempt
  -> services.take_lifecycle::promote_attempt
  -> DatabaseService.promote_recording_attempt_to_take
```

The first graph covers the synchronous Explore/Lab analysis path; the second
covers canonical pipeline-job completion. Exact promotion replay may repeat
the post-success arm, but the arm RPC exactly replays and changes no probe
count, claim or terminal state.

`routes/v2/lab_recording.py::_persist_lab_take` has no arm on this frozen base.
An additional arm there is permitted only after a static and executable proof
that a separately registered branch creates a canonical successful Take
without either promotion graph; no such branch is currently classified.

`promote_recording_attempt_with_confidence_outbox` is not silently treated as
equivalent. It remains unreachable while its existing cutover gate is disabled.
Before that path can become reachable, it must receive a separately reviewed
post-commit Take-arm seam and exact caller registration.

## 4. Registry and response corrections

Replace D34's scanner registry row with:

```text
services/confident_moment_delivery_worker.py::
  sweep_due_confident_moment_deliveries
  -> begin_feedback_language_delivery_scan_run_v1
  -> mark_feedback_language_delivery_scan_started_v1
  -> scan_due_feedback_language_delivery_jobs_v1(p_limit=3)
  -> abandon_feedback_language_delivery_scan_run_v1 only before scanner start
```

Add the two exact promotion caller graphs from section 3.2 and the
`DatabaseService.promote_recording_attempt_to_take -> arm helper -> arm RPC`
edge. Remove the D34 `_persist_lab_take` arm tuple.

The public monitor object may retain an aggregate contention count for alerts,
but `hard_stop` is derived only from the stalled-run predicate. No
contention-only set is accepted by the halt wrapper or stored in
`feedback_language_delivery_stalled_scan_halt_receipts`.

## 5. Required executable regressions

Retain all applicable D20–D34 regressions, replace contradicted D34 contention
tests, and add:

1. zero, one, two and three due rows return zero through three exact ordered
   item results; four or more still process only the first three unlocked rows;
2. only literal `p_limit=3` passes; the scanner performs one indexed
   `FOR UPDATE SKIP LOCKED LIMIT 3` query and no re-probe or fourth-row read;
3. with row 1 locked, rows 2–4 can progress in exact index order in that turn;
   a later turn processes row 1 after release;
4. prolonged contention emits aggregate alert telemetry but never changes a
   rollout revision, calls a halt RPC or creates a stalled-scan halt receipt;
5. only a scanner-started unfinished run older than five seconds produces
   `hard_stop=true` and the exact halt receipt; begun-only, abandoned, completed
   and contention-only states do not;
6. synchronous analysis promotion arms exactly once after committed success;
   failed/noncanonical/unpromoted attempts and `_persist_lab_take` do not arm;
7. `services.pipeline_jobs::_complete_job_attempt` successful promotion arms
   the exact returned Take; promotion failure does not arm; exact processing-job
   replay converges on the same arm operation;
8. force the post-commit arm to fail: the canonical Take remains successful,
   no partial arm mutation exists, operational failure is reported and a later
   due probe/arm replay recovers;
9. AST/static caller closure proves both current promotion graphs, the one
   DatabaseService post-success arm seam, absence from `_persist_lab_take`, and
   no reachable unarmed alternate Take creator; and
10. apply/reapply and forced rollback preserve all prior data, exact index,
    RLS/RPC-only permissions and disabled/non-learning boundaries.

## 6. Stop conditions

Stop and request review if implementation would:

- process or discover more than three due rows per scan, accept a caller-chosen
  limit, re-probe, paginate or invoke the scanner twice in one sweep;
- restore first-row `NOWAIT`, convert contention into automatic halt, or create
  a halt receipt without a scanner-started unfinished run older than five
  seconds;
- arm before canonical Take promotion commits, arm from `_persist_lab_take` on
  the current base, or use browser/payload identity instead of returned Take;
- make post-commit arm failure alter successful Take state;
- activate the confidence-outbox promotion path without an accepted arm seam;
- weaken any inherited authorization, deletion, lock, RLS, blindness,
  dataset/non-learning or literal disabled-gate boundary; or
- number, commit, push, merge, deploy, activate or collect without separate
  authorization.

`VERDICT: D35 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
