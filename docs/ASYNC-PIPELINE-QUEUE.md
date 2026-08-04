# The durable pipeline queue — architecture, Railway rollout, FE handoff

Status: **BE SHIPPED (default OFF).** Everything below is live on this branch
behind `PIPELINE_QUEUE_ENABLED=0`. Nothing changes in production until the
Railway steps in §3 are done and the flag is flipped.

The debt this retires: the full analysis pipeline (ffmpeg → Whisper →
librosa → up to ~20 LLM calls → DB writes) ran inside one HTTP request on 2
sync gunicorn workers under a 30-min timeout. Two concurrent long uploads
saturated the backend; one hung OpenAI call (no client timeout → SDK default
600s) parked half the capacity. The `ASYNC_ANALYSIS_ENABLED` daemon thread
had an accepted gap: a redeploy mid-job stranded the session in
"processing" forever.

---

## 1. Architecture

```
POST /v2/lab/recordings
  │  (validate → store audio in object storage → session + recording rows
  │   — all unchanged, still in-request, all cheap)
  ├─ PIPELINE_QUEUE_ENABLED + Redis reachable?
  │    YES → processing_jobs row (Postgres, state of record)
  │          → RQ enqueue (Redis carries ONLY the job id, never bytes)
  │          → analysis_state='processing'
  │          → 202 { job_id, job_status_url, session_id, … }
  │    NO  → fall through: ASYNC_ANALYSIS_ENABLED daemon (202, no job_id)
  │          → else legacy sync (201 with readout)   ← today's behaviour
  │
worker service (bin/railway-worker.sh → worker.py → rq Worker)
  │  claim (attempts-CAS) → heartbeat thread → re-download audio from
  │  storage → services/analysis_worker.run_full_analysis(...) →
  │  completed + analysis_state='ready'  (or retry w/ backoff → failed +
  │  analysis_state='failed' at the attempts cap)
  │
recovery (all CAS-guarded, safe to overlap)
     · worker boot sweep          · web boot sweep (app.py)
     · queue-borne sweep loop     · POST /v2/internal/jobs/sweep (cron/manual)
```

Load-bearing decisions:

- **One pipeline implementation, three execution modes.** The route's
  `_run_analysis_pipeline` closure moved verbatim to
  `services/analysis_worker.py::run_full_analysis`; sync, daemon and worker
  all call it. Pipeline OUTPUTS are identical in every mode (live loop).
- **Postgres is the source of truth; Redis only delivers.** A wiped Redis
  loses latency, not jobs — the sweeper re-enqueues from `processing_jobs`.
- **RQ over Celery/Dramatiq.** Fork-per-job returns librosa/numpy memory
  after every take and inherits the parent's warmed numba JIT (worker.py
  warms once per deploy, same contract as gunicorn_conf.py); Postgres owns
  retries/recovery, so Celery's broker-level ack machinery buys nothing
  here; smallest operational surface for a stack whose current "workers"
  are curl-in-a-Dockerfile crons.
- **Idempotent re-runs.** Retry deletes the recording's lab snippets first
  (`v2_delete_lab_snippets_for_recording`); candidate windows UPSERT; the
  token charge already dedups on `recording_id` (ledger unique index);
  cadence / arc cards / ideal-text are idempotent per arc/version by
  construction. A crashed run re-executes without duplicating user data.
- **A session can never strand in "processing".** Terminal failure (attempt
  cap) flips `analysis_state='failed'`; the worker stamps `'processing'` on
  claim; heartbeat + sweeper recover orphans. The daemon's accepted
  redeploy gap is retired *in queue mode*.
- **Strict OpenAI timeouts everywhere** (web + worker): client-wide
  `OPENAI_TIMEOUT_SECONDS=120`, transcription `with_options` override
  `OPENAI_TRANSCRIBE_TIMEOUT_SECONDS=600`, `OPENAI_MAX_RETRIES=2`.

## 2. What's in the diff

| Piece | Where |
|---|---|
| Job table migration | `migrations/add_processing_jobs.sql` (idempotent) |
| DB helpers (CAS claim, sweep list, …) | `services/db.py` (after the copilot job methods) |
| Broker glue (lazy, degrade-graceful) | `services/job_queue.py` |
| Job lifecycle + sweeper | `services/pipeline_jobs.py` |
| Extracted pipeline | `services/analysis_worker.py` |
| Queue branch + flag | `routes/v2_routes.py` (`_pipeline_queue_enabled`) |
| Poll + sweep endpoints | `routes/jobs.py` (registered in `app.py`) |
| Worker service | `worker.py`, `bin/railway-worker.sh`, `Procfile` |
| OpenAI timeouts | `config.py`, `services/openai_service.py`, `services/life_engine.py` |
| Tests | `test_processing_jobs.py`, `test_jobs_status_route.py`, `test_openai_client_timeouts.py`, `test_analysis_worker.py` |

## 3. Railway rollout — zero downtime, in this order

Each step is independently safe; stop at any point and production behaves
exactly as before.

1. **Merge + deploy the web service.** Flag off ⇒ byte-identical upload
   behaviour. (The OpenAI timeouts DO take effect immediately — that is
   intended and web-safe; see §6 risk notes.)
2. **Run the migration** (`migrations/add_processing_jobs.sql`) via
   Supabase SQL Editor or `run_migration.py` with `DATABASE_URL`.
   Standing rule applies: "on main" ≠ "run in prod" — this is the call-out.
   Additive `CREATE TABLE IF NOT EXISTS`; re-runnable.
3. **Add Redis**: Railway → project → New → Database → **Redis**. Note the
   `REDIS_URL` it provisions.
4. **Create the worker service**: New service → connect this same repo →
   Settings → Start Command: `sh bin/railway-worker.sh`.

   **Variables — the step that actually bites.** The worker is NOT a thin
   shim: it re-downloads the take from object storage, writes through
   `services.db`, calls Whisper + the analysis LLMs, and emails the coach.
   It needs the web service's WHOLE config, not a subset. `services/db.py`
   builds its Supabase client at import time, so a missing `SUPABASE_URL`
   kills the process before it can log anything useful and Railway
   restarts it forever. `worker.py` preflights the four hard requirements
   and names what is missing, but the fix is always the same: copy the
   variables over.

   Fastest: web service → Variables → **Raw Editor** → copy all → paste
   into the worker's Raw Editor. Better long-term: a project-level
   **Shared Variable group** both services reference, so they cannot
   drift. At minimum:

   | Group | Vars | Why the worker needs it |
   |---|---|---|
   | Supabase | `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | every DB read/write (import-time hard requirement) |
   | OpenAI | `OPENAI_API_KEY` (+ any `OPENAI_*_MODEL`) | Whisper + the analysis LLM calls |
   | Storage | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `COACH_FEEDBACK_VIDEO_BUCKET`, any `R2_*` bucket / base-URL vars | **fetching the audio** — the queue carries an id, not bytes |
   | Email | `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `ADMIN_EMAIL`, `FRONTEND_URL` | auto-send to the coach queue |
   | Ops | `SENTRY_DSN`, `ENV` | worker exceptions reach Sentry |
   | Queue | `REDIS_URL`, `PIPELINE_QUEUE_ENABLED=1` | the broker + the flag |
   | Feature flags | whatever web has on (`MOMENT_SUGGESTIONS_ENABLED`, `MASTER_DOCUMENT_*`, …) | the pipeline branches on these — a mismatch silently changes what a take produces |

   Do NOT set `PORT`: the worker serves no HTTP, and Railway will fail
   healthchecks against a service it thinks is a web target.

   It then boots, warms librosa, sweeps, and idles (queue is empty — web
   isn't enqueueing yet). Healthy log, in order:
   ```
   [startup] ffmpeg located at ...
   librosa numba JIT warmed (pid=...)
   boot sweep: {'requeued': 0, 'failed': 0}
   worker starting on queue 'pipeline' (job timeout 3600s)
   ```

   **Builder note — ffmpeg.** Railway's default builder is now
   **Railpack**, which does NOT read `nixpacks.toml` or `apt.txt` (its
   only config file is `railpack.json`). A service built with it has no
   system ffmpeg and logs `no system ffmpeg — using the imageio-ffmpeg
   bundled binary`. That fallback is a real ffmpeg and the pipeline runs,
   but it diverges from web.

   The fix is committed as **`railpack.json`** at the repo root:

   ```json
   { "$schema": "https://schema.railpack.com",
     "deploy": { "aptPackages": ["...", "ffmpeg"] } }
   ```

   Three things about that file, each of which silently breaks it:
   - `deploy.aptPackages` is the RUNTIME list. Root-level
     `buildAptPackages` exists but only lives in the builder stage — put
     ffmpeg there and the final image still won't have it.
   - The `"..."` entry extends Railpack's generated package list. Without
     it the list REPLACES what the Python provider adds (`libpq5` etc.),
     so it is not cosmetic.
   - A root `Dockerfile` would override all of this (there is none — the
     `Dockerfile.*-cron` files are per-service paths, not the default).

   Equivalent without a file, as a service variable:
   `RAILPACK_DEPLOY_APT_PACKAGES="... ffmpeg"`.

   Nixpacks is NOT a fallback plan: Railway removed its documentation and
   dropped it from the documented builder enum (`RAILPACK` | `DOCKERFILE`)
   in March 2026. Services still on it keep working, which is why
   `nixpacks.toml` stays in the repo and must list the same packages as
   `railpack.json` — but don't design around switching back to it.

   Check the WEB service after any rebuild too: if it silently moved to
   Railpack it lost ffmpeg the same way, and there it degrades the live
   loop. Verify from its deploy log's `[startup] ffmpeg located at …`
   line, or in a build log look for the `packages:apt:runtime` step
   installing ffmpeg.
5. **Canary**: flip `PIPELINE_QUEUE_ENABLED=1` + set `REDIS_URL` on the
   **web** service. Record one take; confirm 202 with `job_id`, worker log
   shows the job, poll reaches `ready`, readout renders. (Do this before
   the FE ships job_id handling — the FE's existing `analysis_state`
   polling keeps working throughout, see §5.)
6. **Optional hardening**: set `PIPELINE_JOBS_SWEEP_SECRET` on web and add
   a cron service (house pattern: curl image, e.g. hourly) POSTing
   `/v2/internal/jobs/sweep` with `X-Internal-Secret`. Belt-and-braces —
   the worker's own sweep chain already covers this.
7. **Roll back any time**: unset `PIPELINE_QUEUE_ENABLED` on web → uploads
   fall back to daemon/sync instantly. In-flight jobs still finish on the
   worker (harmless either way).

Env reference (all optional beyond the two marked):

| Var | Where | Default | Meaning |
|---|---|---|---|
| `PIPELINE_QUEUE_ENABLED` | web + worker | `0` | **required=1 to enable** |
| `REDIS_URL` | web + worker | — | **required** broker address |
| `PIPELINE_QUEUE_NAME` | both | `pipeline` | RQ queue name |
| `PIPELINE_JOB_TIMEOUT_SECONDS` | worker | `3600` | RQ kills the work horse after this |
| `PIPELINE_JOB_MAX_ATTEMPTS` | web | `3` | lifetime runs per job |
| `PIPELINE_JOB_STALE_MINUTES` | both | `15` | silent heartbeat ⇒ worker presumed dead |
| `PIPELINE_JOB_HEARTBEAT_SECONDS` | worker | `60` | heartbeat stamp interval |
| `PIPELINE_SWEEP_INTERVAL_SECONDS` | worker | `300` | sweep-chain cadence |
| `PIPELINE_JOBS_SWEEP_SECRET` | web | unset | unset ⇒ sweep endpoint 503s |
| `OPENAI_TIMEOUT_SECONDS` | both | `120` | client-wide LLM timeout |
| `OPENAI_TRANSCRIBE_TIMEOUT_SECONDS` | both | `600` | Whisper per-call timeout |
| `OPENAI_MAX_RETRIES` | both | `2` | SDK retry count |

Scaling later: worker concurrency = add replicas of the worker service
(each is one RQ worker; the claim CAS + dedup index keep replicas safe).
Web `--workers 2` can stay as-is — with the pipeline off-loaded, web
requests are all fast again.

## 4. FE handoff — the async contract

**The FE keeps working with zero changes** (§5). This section is the
*better* UX the new contract enables.

### 4.1 Upload response

`POST /v2/lab/recordings` in queue mode returns **202**:

```json
{
  "status": "processing",
  "state": "processing",
  "job_id": "…uuid…",
  "job_status_url": "/v2/jobs/<job_id>/status",
  "session_id": "…", "recording_id": "…",
  "duration_minutes": 4.2, "audits_needed": 1,
  "session_context": { … }, "readout": null,
  "arc_id": "…", "take_index": 2, "take_count": 2, "audit_paid": false
}
```

Identical to the existing daemon-mode 202 **plus `job_id` +
`job_status_url`**. Branch on `state === "processing"` (or HTTP 202), not
on the presence of `job_id` — daemon-mode 202s have no `job_id` and must
keep working (it's the queue's fallback).

### 4.2 The poll

`GET /v2/jobs/{job_id}/status` — no auth needed for guest uploads; authed
uploads need the same user's token (foreign/unknown ⇒ 404, identical on
purpose). `Cache-Control: no-store`.

```json
{
  "job_id": "…", "status": "processing", "state": "processing",
  "stage": "analysis", "percent": 40, "message": "Transcribing and analyzing your take…",
  "session_id": "…", "created_at": "…", "finished_at": null
}
```

- `state` uses the readout GETs' vocabulary — `processing | ready |
  failed` — so one FE state machine serves both polls.
- `stage`/`percent`/`message` are coarse mechanical progress for the UI
  (5 → 15 → 70 → 90 → 100). Optional to render; `message` strings are
  copy-safe placeholders — **any user-facing wording change needs founder
  sign-off** (standing copy rule).
- Terminal: `state:"ready"` (then fetch the readout as today) or
  `state:"failed"` with a short `error` string → offer re-record.
- Suggested cadence: 2s for the first ~30s, then 5s. Stop on terminal.
- The body never carries scores/verdicts (AC-9) — results come only from
  the readout GETs.

### 4.3 The UX this unlocks

- Don't lock the user on a spinner: on 202, free navigation immediately —
  the job survives tab close, phone lock, AND backend redeploys now.
- Kill the ~3-minute client-side timeout the daemon mode needed. A queued
  job always terminates: `ready` or `failed`, enforced server-side
  (attempts cap + sweeper). Poll until terminal.
- On revisit, the session list can show per-take state from the readout
  GET's `state` field exactly as today; `job_id` is only a nicety for the
  richer in-flight progress.

## 5. Compatibility — why nothing breaks mid-rollout

- Queue mode reuses the daemon-mode FE contract: `analysis_state` flips
  `processing → ready|failed` on `v2_sessions`, and both readout GETs
  (`/v2/user/sessions/<sid>/readout`, `/v2/lab/recordings/<sid>/readout`)
  already serve it. An FE that knows nothing about `job_id` behaves
  exactly as in daemon mode.
- Deploy order is therefore free: BE flag can flip before the FE ships
  `job_id` polling (current FE polls readout), or after (202-shape already
  handled if `ASYNC_ANALYSIS_ENABLED` was ever on; if the FE only ever saw
  sync 201s, ship FE 202-handling first, then flip — same order the daemon
  flag documented).
- Rollback is a web env-var unset; no migration reversal, no FE change.

## 6. Risk notes (reviewed)

- **OpenAI timeouts apply from step 1** (before the queue). 120s LLM /
  600s Whisper are ceilings well above healthy latencies; the previous
  effective ceiling was 600s for everything. If a legit >600s Whisper
  call exists (≈1h audio at the reference-video cap), raise
  `OPENAI_TRANSCRIBE_TIMEOUT_SECONDS` — env, no deploy.
- **Two runners on one job** requires: claim CAS lost AND stale-heartbeat
  misread. Heartbeats stamp every 60s; staleness is 15 min. Even then,
  re-run cleanup + upserts + the charge ledger keep data correct.
- **Redis wiped**: pending rows re-enqueue via sweep (web boot, worker
  boot, chain, endpoint). Worst case latency = sweep interval.
- **Worker dead / crash-looping**: jobs stay `pending` in Postgres; FE
  polls `processing`. Alarm signal: `processing_jobs` rows with
  `status='pending'` older than ~10 min. (No auto-fallback to sync here —
  by design, the web must not silently re-absorb the load spike.)
  Operational answer: fix/restart the worker or unset the web flag.
