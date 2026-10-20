# MLC-3 Confident Moment Coaching Bundle — Implementation Seam Amendment D36

Status: proposed minimal frozen-window scanner correction; executable work
remains blocked pending independent Product, ML/data and Engineering acceptance.

## 1. Parent and sole supersession

D36 binds and narrowly supersedes:

```text
MLC3-CONFIDENT-MOMENT-COACHING-IMPLEMENTATION-SEAM-AMENDMENT-D35.md
SHA-256 fbe4f935cc23290de7491f89c8e50a7b3af8cdfeb41433026eef160f31b7c2aa
```

Everything in D35 and its accepted parents remains authoritative except D35
§2.1's `FOR UPDATE SKIP LOCKED LIMIT 3` selection and the regressions that
depended on it. D36 changes no other operation, schema, gate or meaning.

## 2. Exact immutable three-ID window

Each scanner call accepts only literal `p_limit=3` and executes exactly one
unlocked, index-only identity probe:

```sql
SELECT job_id
FROM public.feedback_language_delivery_job_due_heads
WHERE scheduling_state='pending'
  AND next_probe_at <= :exact_probe_cutoff
ORDER BY next_probe_at,job_id
LIMIT 3;
```

The result freezes an ordered immutable window of zero through three exact job
IDs for that scanner call. The query uses
`feedback_language_delivery_due_pending_idx`; production-shaped plan evidence
must show no explicit sort or sequential scan. MVCC visibility may require a
bounded heap visibility check but may not broaden the window.

The scanner then makes at most one exact primary-key lock attempt for each
frozen ID, in frozen order:

```sql
SELECT *
FROM public.feedback_language_delivery_job_due_heads
WHERE job_id=:frozen_job_id
  AND scheduling_state='pending'
  AND next_probe_at <= :exact_probe_cutoff
FOR UPDATE NOWAIT;
```

Only SQLSTATE `lock_not_available` is a contention miss. A missing or no-longer
due row is a currentness miss. Either is recorded for this scan and the scanner
continues to the next already-frozen ID. Every acquired row follows D31–D35's
non-waiting advisory locks, validity, no-target, claim and terminal rules. The
response contains zero through three item results in frozen order plus the
aggregate counts below.

The scanner never re-runs the identity probe, expands the window, uses
`SKIP LOCKED`, follows a replacement row, inspects row 4 or makes more than
three PK lock attempts. Thus a locked first ID permits only frozen IDs 2 and 3
to progress; it never promotes ID 4 into the turn. A later sweep retries rows
still due.

## 3. Exact aggregate contention telemetry

For each scan result:

```text
frozen_window_count       integer 0..3
acquired_count            integer 0..frozen_window_count
contention_nowait_count   integer 0..frozen_window_count
currentness_miss_count    integer 0..frozen_window_count
```

`contention_nowait_count` is exactly the number of frozen IDs whose one PK
`NOWAIT` attempt returned `lock_not_available`; it excludes missing/no-longer-
due rows, advisory try-lock misses and all other failures. Counts must reconcile
with the per-ID operational result classes without exposing job, user or
content identity through monitor/HTTP output.

Contention remains alert-only under D35. No count or duration of NOWAIT misses
can set `hard_stop`, call a halt RPC or create a stalled-scan halt receipt. The
sole delivery-scanner automatic halt remains a scanner-started unfinished run
older than five seconds.

## 4. Registry and required regressions

The D35 scanner caller tuple remains unchanged, with the SQL/static registry
pinning this exact two-stage protocol: one `LIMIT 3` unlocked identity probe,
then zero through three ordered exact-PK `NOWAIT` attempts.

Retain every non-contradicted D20–D35 regression and replace D35 scanner tests
with:

1. zero, one, two and three due rows freeze exactly zero through three IDs and
   attempt no more than that many PK locks;
2. four or more due rows freeze only IDs 1–3; row 4 is never read, locked,
   returned or used in a mutation;
3. row 1 locked yields one NOWAIT contention miss and permits rows 2–3 only to
   progress; row 4 remains untouched even when unlocked;
4. rows 1 and 3 locked permit only row 2 to progress, with exact
   `contention_nowait_count=2`; a later call after release retries due rows in
   current index order;
5. a frozen row changed to terminal/not-due before its PK attempt is a
   currentness miss, not contention, and no replacement ID enters the window;
6. plan/static checks prove the named partial index, one unlocked `LIMIT 3`
   probe, exact-PK `NOWAIT`, no `SKIP LOCKED`, no fourth attempt and no re-probe;
7. only literal `p_limit=3` is accepted and the four aggregate counts are
   bounded and internally consistent; and
8. sustained NOWAIT misses emit only aggregate alert telemetry and create zero
   rollout halt revisions or stalled-scan halt receipts.

## 5. Stop conditions

Stop and request review if implementation would use `SKIP LOCKED`, replenish a
missed frozen ID, inspect row 4, re-probe, accept a caller-chosen limit, wait on
a row lock, conflate NOWAIT contention with currentness/advisory misses, or use
contention to halt. All D35 authorization, deletion, RLS, worker, run receipt,
Take-arm, disabled-gate and non-learning stop conditions remain unchanged.

`VERDICT: D36 PROPOSED FOR PRODUCT, ML/DATA AND ENGINEERING REVIEW; EXECUTABLE WORK BLOCKED`
