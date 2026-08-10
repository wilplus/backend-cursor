# SPEC — Pipeline queue admin panel (Task IV)

**Status:** DESIGN, awaiting founder review. Nothing here is built.
**Spans both repos:** backend routes + services here, BFF and UI in
`frontend-cursor`.

---

## 0 · The one-paragraph version

The queue already knows everything the panel needs to show — `queue_health()`
computes depth, wait/run percentiles, failures and a saturation verdict, and
`sweep_stale_jobs()` already recovers lost work. Both are reachable today only
through `X-Internal-Secret`-gated endpoints built for cron. This spec adds an
**admin-authenticated** way to reach the same two services, plus a job list,
and a thin UI over it. **No new capability; a new door for a human instead of
a robot.**

---

## 1 · The constraint, and a way to make it structural

> "`PIPELINE_JOBS_SWEEP_SECRET` must NEVER reach the browser under any
> circumstances. Route it strictly through a BFF endpoint server-side."

Agreed on the requirement. On the mechanism, there are two ways to satisfy it,
and they are not equally safe.

### Option A — BFF holds the secret (the literal reading)

The Next.js route reads `PIPELINE_JOBS_SWEEP_SECRET` from server-side env and
attaches `X-Internal-Secret` when calling `/v2/internal/jobs/*`.

This does keep the secret out of the browser. What it also does is make the
BFF a **secret-laundering proxy**: the route's own admin check becomes the only
thing standing between any caller and a machine credential that bypasses all
user authorization. Get that check wrong — a missing `await`, a truthy
non-admin object, a future refactor that reorders the guard — and the secret is
effectively public, while every log line still looks fine.

It also splits the trust model: the backend believes it is talking to cron
(a machine that possesses a shared secret), when it is really talking to a
human whose identity the backend never sees. Nothing upstream can attribute a
sweep to a person.

### Option B — admin-gated twins, no secret anywhere (RECOMMENDED)

Add `@require_admin` routes on the backend that call the **same services**:

```
GET  /v2/admin/pipeline/health   -> services.pipeline_health.queue_health()
GET  /v2/admin/pipeline/jobs     -> new: a bounded, filtered job list
POST /v2/admin/pipeline/sweep    -> services.pipeline_jobs.sweep_stale_jobs()
```

The BFF becomes a plain JWT passthrough — the exact shape
`src/app/api/v2/admin/learning/proxy.ts` already uses, where **the backend is
the gate** and the proxy forwards the Supabase JWT verbatim. There is no
secret in the BFF, so there is no secret to leak: the requirement is satisfied
*structurally* rather than by careful handling.

`/v2/internal/jobs/*` stays exactly as it is, secret-gated, for cron. The two
callers keep two different credentials because they are two different kinds of
caller.

**Recommendation: Option B.** Same result for the fence, one fewer way to be
wrong, and it reuses a pattern already proven in this codebase. Option A is
implementable if the founder prefers it; it is the sequencing that differs, not
the amount of work.

---

## 2 · What the panel shows

Everything below already exists in `queue_health()` except the job list.

| block | fields | source |
|---|---|---|
| **Saturation** | `healthy` / `busy` / `saturated` / `unknown` + `recommendation` | `queue_health()` |
| **Depth** | `pending`, `processing`, `oldest_pending_seconds` | `queue_health()` |
| **Latency** | `wait_p50/p95`, `run_p50/p95`, sample size | `queue_health()` |
| **Failures** | count in window, `last_error`, window hours | `queue_health()` |
| **Jobs** | id, kind, status, stage, percent, attempts/max, session_id, enqueued/started/finished, error | **new** `list_jobs_for_admin()` |

The saturation verdict is the panel's headline because it answers the only
question worth acting on: more workers shrink the WAIT, never the RUN. That
distinction is already written down in `services/pipeline_health.py` and the UI
should not re-explain it differently.

### `list_jobs_for_admin()` — the one new backend service

```python
def list_jobs_for_admin(*, status=None, limit=50, before=None) -> list[dict]
```

* **Bounded by construction.** `limit` capped hard (100); default 50. The
  existing reader caps at 500 rows for the same reason — an ops surface must
  never be able to table-scan production.
* **Keyset pagination on `enqueued_at`,** not OFFSET: the queue mutates while
  you page, and OFFSET silently skips rows when it does.
* **Never returns `payload`.** It holds storage paths and upload flags; the
  panel needs none of it, and the smallest safe projection is the one that
  cannot leak a field nobody reviewed. `result` is likewise omitted from the
  list and available only on a single-job read, if we ever add one.

---

## 3 · What the panel can DO

Two tiers, deliberately separated.

### Tier 1 — ship now

**Sweep.** `POST /v2/admin/pipeline/sweep`, calling the existing
`sweep_stale_jobs()`. Already CAS-guarded and safe to call at any time; a quiet
sweep is a cheap SELECT. This is the single action that resolves the actual
operational incident (a job stuck because a worker died), and it exists.

### Tier 2 — needs a founder decision before it is built

**Retry a failed job** and **cancel a pending job** both write to the live
record→transcribe path. They are not hard, but they are LIVE LOOP surface:

* retry must respect `max_attempts` or it becomes an infinite-cost button, and
  it must not create a second active job for a `dedup_key` that already has one
  — the partial unique index will reject it, and a UI that reports success on a
  swallowed exception is worse than no button;
* cancel needs a defined meaning for a job the worker has already picked up.
  "Mark it failed" and "stop the work" are different promises, and only the
  first is achievable without worker cooperation.

**Not in scope either way:** deleting jobs, editing payloads, or re-running a
completed job. Each destroys or fabricates pipeline history.

---

## 4 · Fences

**AC-9 is not in tension here, and it is worth saying why rather than
assuming.** The fence forbids surfacing scores/verdicts/numbers **to users**;
these are plumbing counters about jobs, not reads on a speaker.
`services/pipeline_health.py` states exactly that in its own docstring. The
panel is admin-only and shows no speaker-level anything.

Two things that would break it, listed so they stay banned:

* rendering any per-user quality signal in the job list (a score, a rank, a
  power_score) — the list carries plumbing state only, which is also why
  `payload` and `result` are excluded;
* leaking queue state into a user-facing surface ("we're busy, 4 ahead of
  you"). That is product copy and needs founder sign-off (LIVE LOOP), quite
  apart from the fence.

**Not user-facing copy:** the panel's own strings are internal ops language,
the same category as the existing learning admin page.

---

## 5 · Files

### backend-cursor

| file | change |
|---|---|
| `routes/v2/admin_pipeline.py` | **new** — three `@require_admin` routes |
| `services/pipeline_admin.py` | **new** — `list_jobs_for_admin()` |
| `services/db.py` | **new** `list_processing_jobs()` (bounded, keyset, no `payload`) |
| `app.py` | register the blueprint |
| `test_pipeline_admin.py` | **new** — authz, bounds, projection, AC-9 |

`services/pipeline_health.py` and `services/pipeline_jobs.py` are **not
modified**. The panel is a caller, not a rewrite.

### frontend-cursor

| file | change |
|---|---|
| `src/app/api/v2/admin/pipeline/proxy.ts` | **new** — JWT passthrough (mirrors the learning proxy) |
| `src/app/api/v2/admin/pipeline/{health,jobs}/route.ts` | **new** — GET |
| `src/app/api/v2/admin/pipeline/sweep/route.ts` | **new** — POST |
| `src/app/admin/pipeline/page.tsx` | **new** — the panel |
| `src/services/api/pipelineAdmin.ts` | **new** — typed client |

---

## 6 · Tests that must exist

Authorization is the whole risk surface, so it is tested as behaviour, not
inspected by eye:

1. **a non-admin gets 403** on each of the three routes;
2. **an unauthenticated caller gets 401**, and the two look different from the
   404 the *user-facing* job poll returns (that one hides existence on
   purpose; these do not, because the caller is already an admin);
3. **the list is bounded** — a `limit` above the cap is clamped, not honoured;
4. **the projection excludes `payload`**, asserted on the returned keys rather
   than the query string, so a future `select("*")` fails the test;
5. **no secret in the FE bundle** — a build-time assertion that
   `PIPELINE_JOBS_SWEEP_SECRET` appears nowhere in client output. Under
   Option B this should be trivially true, which is the point: the test proves
   the structural claim instead of trusting it.

---

## 7 · Build order

1. `list_processing_jobs()` + `list_jobs_for_admin()` + tests — pure, no routes
2. the three backend routes + authz tests
3. the BFF passthroughs + the no-secret-in-bundle test
4. the page
5. Tier 2 (retry/cancel) only after a founder decision on §3

Steps 1–3 are independently useful: they make the queue inspectable by a human
with credentials, which today requires a shell and a curl.
