# Ops runbook — the recording pipeline queue

**Audience: the backlog-manager agent, and whoever is on call.** How to
decide when the take-processing pipeline needs more capacity, what to do
when it breaks, and — just as important — when to do *nothing*.

Architecture and rollout: [ASYNC-PIPELINE-QUEUE.md](ASYNC-PIPELINE-QUEUE.md).

---

## 0. The one idea

A take's total time is **wait + run**.

- **wait** = `enqueued_at → started_at`. Time sitting in the queue because
  every worker slot was busy. **Workers fix this. Only this.**
- **run** = `started_at → finished_at`. ffmpeg → Whisper → librosa → ~20
  LLM calls. **Workers cannot touch this.** It is the pipeline's own cost.

Scaling on run time is the standard mistake: you pay for containers and
every take stays exactly as slow. Before any capacity decision, separate
the two numbers. If wait ≈ 0, the answer is always "change nothing" — no
matter how slow takes feel.

**Measured baseline (2026-08-06, first production take):** wait 1s, run
31s. One worker slot, nobody waiting.

## 1. The signal

```
GET /v2/internal/jobs/health
Header: X-Internal-Secret: $PIPELINE_JOBS_SWEEP_SECRET
```

```json
{
  "queue":   {"pending": 0, "processing": 1, "oldest_pending_seconds": null},
  "latency": {"sample": 12, "wait_p50_s": 1, "wait_p95_s": 3,
              "run_p50_s": 31, "run_p95_s": 74},
  "failures":{"recent": 0, "last_error": null},
  "saturation": "healthy",
  "recommendation": "nothing queued — every take starts immediately..."
}
```

`saturation` is the verdict, and it is deliberately **relative**:

| Verdict | Meaning | Action |
|---|---|---|
| `healthy` | nothing pending | **none.** Adding workers changes nothing |
| `busy` | queued, but waits are short beside a take's own time | none — it is working through |
| `saturated` | oldest wait ≥ `run_p50` — people wait as long as the work takes | raise `WORKER_COUNT`, or add a replica |
| `unknown` | the queue could not be read | check Supabase/worker health first |

A 30s wait is nothing beside a 10-minute take and painful beside a 30s
one, which is why the threshold is `run_p50` rather than a fixed number.

The worker also logs this every ~5 minutes during its sweep, so
`pipeline queue SATURATED: …` appears in Railway logs without anyone
running SQL. **That log line is the trigger to act.**

## 2. Capacity decisions

### The dial
`WORKER_COUNT` on the worker service (default **2**). Each slot is a
process holding its own copy of the analysis stack (~0.5–1 GB, plus the
decoded PCM of its current take — a 60-minute take is ~230 MB).

### The ladder, in order
1. **`WORKER_COUNT` 2 → 4.** Cheapest. Watch container memory.
2. **Worker replicas.** Past ~4 slots RAM is the binding constraint.
   Replicas are safe — the claim CAS and the dedup index prevent double
   processing — and they fail independently.
3. **Autoscale on queue depth**, if bursts are spiky and predictable.
4. **Per-job containers** (Modal / Cloud Run) if the load is genuinely
   spiky and idle capacity dominates the bill. `processing_jobs` and the
   status contract survive that migration; only `services/job_queue.py`
   and the worker entrypoint get replaced.

### When to scale DOWN
`healthy` for weeks with `pending` never above 0 → `WORKER_COUNT=1` and
pocket the RAM. Idle slots cost real money and buy nothing.

### Cost
Roughly **$10–15/month per always-on slot**, mostly RAM (verify against
Railway's current rates). Note: **workers do not change the OpenAI bill** —
the same takes get processed either way, just sooner. Extra capacity buys
latency, not throughput of spend, which makes it a cheap and reversible
decision.

## 3. Triage

Always start here:
```sql
SELECT status, stage, percent, attempts, error, enqueued_at, started_at
FROM public.processing_jobs ORDER BY created_at DESC LIMIT 10;
```

| Symptom | Cause | Fix |
|---|---|---|
| `pending`, `started_at` null, worker idle | enqueue not reaching the worker | check `REDIS_URL` + `PIPELINE_QUEUE_ENABLED` on **both** services |
| No job row at all | web fell back to sync/daemon | `PIPELINE_QUEUE_ENABLED` missing on **web** |
| `failed` at `fetch_audio` | worker can't read storage | R2 credentials on the worker (see §4) |
| `failed`, `attempts=3`, varied errors | a real pipeline bug | read `error`; check Sentry |
| Stuck `processing`, heartbeat frozen | worker died mid-job | sweeper requeues at 15 min; or poke `POST /v2/internal/jobs/sweep` |
| Session shows "Working on your take" forever, no job row | orphan | sweeper fails it at 30 min; check `analysis_state` on `v2_sessions` |

Manual recovery poke:
```bash
curl -X POST https://<backend>/v2/internal/jobs/sweep \
  -H "X-Internal-Secret: $PIPELINE_JOBS_SWEEP_SECRET"
```

## 4. The config trap that caused four outages

**The worker service needs the SAME variables as web.** It is not a thin
shim: it downloads from R2, writes through Supabase, calls Whisper, and
emails the coach.

**Railway sealed variables cannot be copied between services** — they
arrive *empty*, silently. Every secret must be re-entered by hand on the
worker. This alone caused three of the four failures during rollout.

Especially: **R2 is gated on three secrets**
(`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`). A worker
missing them resolves to Supabase Storage and hunts for an object web put
in R2. The job now fails immediately with a named `ConfigMismatchError`
rather than burning three retries — if you see it, the message says which
variables to set where.

**Rule: the worker's variable list must MATCH web's.** Not a superset, not
a subset. Adding a variable web doesn't have causes the same class of
divergence in reverse.

Two more, both Railway-specific:
- **Railpack ignores `nixpacks.toml` / `apt.txt`.** ffmpeg comes from
  `railpack.json` (`deploy.aptPackages`, and the `"..."` spread is
  load-bearing). Keep both files in sync while any service is on Nixpacks.
- **Don't prepend a system bin dir to `PATH`** in an entrypoint — it
  shadows the venv's `python3`. `bin/railway-worker.sh` pins the
  interpreter by absolute path; keep it that way.

## 5. Rules for the backlog manager

1. **Never scale on intuition or a complaint.** Read `saturation` first.
   "It feels slow" is usually run time, which workers cannot fix.
2. **`healthy` means do nothing**, however slow takes feel. Route that
   complaint to pipeline latency work (fewer/cheaper LLM calls, smaller
   Whisper payloads), not to capacity.
3. **Escalate on the log line**, not on anecdote: `pipeline queue
   SATURATED` in the worker logs is the trigger.
4. **Failures ≠ saturation.** A rising `failures.recent` is a bug or a
   config drift. Adding workers multiplies the failures.
5. **A user-facing "high traffic" message is product copy** and needs
   founder sign-off (CLAUDE.md). The ops signal here is internal and
   carries no such constraint — do not surface it to users on your own
   initiative. Note also that the queue's promise is unchanged under load:
   the upload always returns instantly and the job always terminates
   (`ready` or `failed`), so a busy queue means waiting longer, never
   breaking.
6. **The job status endpoint stays mechanical** (`stage`, `percent`) and
   must never carry scores or verdicts — AC-9. The readout GETs own
   results.
7. **When in doubt, measure for a week before spending.** The data is free
   and already in `processing_jobs`.

## 6. Standing queries

```sql
-- The capacity question. wait ≈ 0 ⇒ do not add workers.
SELECT count(*) AS takes,
       round(avg(extract(epoch FROM started_at  - enqueued_at))) AS avg_wait_s,
       max(round(extract(epoch FROM started_at  - enqueued_at))) AS worst_wait_s,
       round(avg(extract(epoch FROM finished_at - started_at ))) AS avg_run_s
FROM public.processing_jobs
WHERE status = 'completed' AND finished_at > now() - interval '7 days';

-- Right now.
SELECT status, count(*), max(now() - enqueued_at) AS oldest
FROM public.processing_jobs
WHERE status IN ('pending','processing') GROUP BY status;

-- Failure modes this week.
SELECT stage, left(error, 80) AS err, count(*)
FROM public.processing_jobs
WHERE status = 'failed' AND created_at > now() - interval '7 days'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- Stranded sessions (should stay empty once the sweeper runs).
SELECT count(*) FROM public.v2_sessions WHERE analysis_state = 'processing';
```
