# Ops runbook — secrets, staging, storage split, Sentry

P0/P2 technical-debt sweep, 2026-08-03. Everything here is the operator
half of a change that already landed in code. The code is inert until the
steps below are run — deliberately, so merging could never break the live
loop.

Four sections, in the order they should be done:

1. [Sentry sampling](#1-sentry-sampling) — done on merge, nothing to run
2. [Secrets management](#2-secrets-management) — a decision + a rotation
3. [Lab audio bucket split](#3-lab-audio-bucket-split) — provision + 2 vars
4. [Staging environment](#4-staging-environment) — provision + 8 vars

---

## 1. Sentry sampling

**Was:** `traces_sample_rate=1.0` hardcoded in `app.py` and `worker.py` — a
performance transaction for every request and every job, health checks
included. That burns the quota on noise, and a burned quota costs us
*error* visibility on the live loop, which is the thing we actually need.

**Now:** `Config.SENTRY_TRACES_SAMPLE_RATE`, defaulting to **0.05 in
production** and **0 everywhere else**. Error capture is never sampled by
this and is unchanged.

| Variable | Default | Notes |
|---|---|---|
| `SENTRY_TRACES_SAMPLE_RATE` | `0.05` prod / `0.0` else | Raise temporarily when chasing a latency regression |
| `SENTRY_PROFILES_SAMPLE_RATE` | `0.0` | Multiplies on top of tracing; only for a CPU question |
| `RELEASE_SHA` | `$RAILWAY_GIT_COMMIT_SHA` | Tags events with the deploy |

Also set on both inits: `send_default_pii=False` and
`max_request_body_size="never"`, so Sentry can't become the leak §2 of the
audit was closing.

**Nothing to run.** Optionally set `SENTRY_TRACES_SAMPLE_RATE=0.02` if 5%
is still noisy at current volume — check the quota graph after a week.

---

## 2. Secrets management

### What landed

`services/secrets.py` — a resolution seam, not a manager:

- **`resolve(NAME)`** reads `<NAME>_FILE` (a path) before `<NAME>` (an env
  var). The file form is the idiom every managed store speaks — Docker
  secrets, Kubernetes projected volumes, Vault Agent, the AWS Secrets
  Manager CSI driver. A file also never lands in `/proc/<pid>/environ` or
  a crash dump, and never leaks into a subprocess that inherits the
  environment. If `<NAME>_FILE` is set but unreadable we return `None`
  rather than falling back to the env var — silently using a *stale*
  credential is worse than failing.
- **`audit()`** reports missing, placeholder, and truncated secrets. It
  names variables, never values, so the result is safe to log and to paste
  into a ticket.
- **`enforce_at_boot()`** runs at the top of `app.py` and in
  `worker.py::main`. In **production and staging** an error finding raises
  and the deploy rolls back to the last good release. In development it
  only logs.

`config.py` routes these through the resolver:
`SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`,
`OPENAI_API_KEY`, `RESEND_API_KEY`, `STRIPE_SECRET_KEY`,
`STRIPE_WEBHOOK_SECRET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`.
Every other setting still uses `os.getenv` directly — the seam lives
where the sensitive values are, not across all ~200 call sites.

### The decision that is still yours

Picking a store is an ops + billing call. The honest comparison:

| Option | Cost | Effort | What it buys over today |
|---|---|---|---|
| **Stay on Railway variables** | £0 | none | Nothing new — but they *are* encrypted at rest and access-controlled. The real gaps are no rotation history and no audit log. |
| **Doppler** | ~$8/user/mo | ~1h | Rotation, versioning, audit log, per-environment sync. Railway integration is native. Lowest-friction upgrade. |
| **Infisical (cloud)** | free tier, then ~$6/user/mo | ~2h | Same feature set, open-source, self-hostable later. |
| **AWS Secrets Manager** | ~$0.40/secret/mo | ~4h | Strongest audit story; heaviest setup (IAM, a sidecar or startup fetch). Overkill unless AWS is already in the stack. |

**Recommendation: Doppler.** The gap worth closing is *rotation and audit*,
not encryption-at-rest, and Doppler closes it in an afternoon with a native
Railway integration. Whichever is chosen, the code doesn't change — the
store writes either env vars (works today) or files plus `<NAME>_FILE`
(works today).

### Rotation — do this regardless of the choice

Independent of any tool, these are worth rotating once because they have
been in plain-text env for a long time and were readable in error
responses before the sanitization work in this same sweep:

```
OPENAI_API_KEY
SUPABASE_SERVICE_ROLE_KEY
R2_SECRET_ACCESS_KEY
STRIPE_SECRET_KEY          # restricted key if not already
RESEND_API_KEY
```

Rotate one at a time, redeploy, confirm `/health` is green before the
next. `git log -p -- .env` is clean and `.gitignore` covers `.env` — no
secret is in the repo history; this is precautionary, not a breach
response.

### Verifying

```bash
ENV=production python3 -c "from services.secrets import audit; print(audit())"
```

Prints `{'env': 'production', 'errors': [], 'warnings': [], 'checked': N}`
when the environment is sound. Never prints a value.

---

## 3. Lab audio bucket split

### The finding

Lab takes were written to `coach_feedback_videos` — the coach's curated,
effectively-public media bucket. Two different sensitivity classes, one
access policy, one lifecycle rule.

And the separation was already fictional in production:
`coach_video_storage.put_coach_object_bytes(bucket, ...)` **ignores its
`bucket` argument whenever R2 is configured** and always writes
`r2_bucket_name()`. Every take, coach video, extracted PDF and learning
artifact was landing in one bucket regardless of what the call site asked
for.

### What landed

`services/lab_audio_storage.py`. Writes go to the lab bucket **only when
both** `R2_LAB_AUDIO_BUCKET` **and** `R2_LAB_AUDIO_PUBLIC_BASE_URL` are
set — the URL half is load-bearing, because writing to a new bucket while
still minting URLs against the old public domain gives every new take an
`audio_url` that 404s.

Reads never assume: `get_lab_audio_bytes` tries the recorded bucket, then
the lab bucket, then the coach bucket, then the interview-audio bucket. So
**there is no migration to run** — objects written before the flip stay
where they are and keep reading — and the flip is reversible by unsetting
the vars.

Call sites moved: `POST /v2/lab/recordings`,
`POST /v2/coach/annotation-uploads`, the recut route, `services/
pipeline_jobs.py` (the durable worker), and the snippet recompute
fallback.

### Cutover

1. Create the R2 bucket, e.g. `willab-lab-audio`, on the **same R2
   account** — the existing `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` /
   `R2_SECRET_ACCESS_KEY` are reused, no new credentials.
2. Attach a public domain (or enable the r2.dev subdomain) →
   that URL is `R2_LAB_AUDIO_PUBLIC_BASE_URL`.
3. Set a lifecycle rule to match the retention promise in the privacy
   policy. This is the point of the split — the coach bucket's rule was
   never right for user voice.
4. Set both variables on **the web service and the worker service** (they
   both write and read):

   ```
   R2_LAB_AUDIO_BUCKET=willab-lab-audio
   R2_LAB_AUDIO_PUBLIC_BASE_URL=https://lab-audio.willpowerlab.com
   ```

5. Redeploy. Record one take, confirm it plays back in the readout, then
   confirm the object appears in the new bucket and a **pre-cutover** take
   still plays (that exercises the read fallback).

### Rollback

Unset both variables and redeploy. New writes return to the coach bucket;
everything written to the lab bucket meanwhile still reads, because the
fallback chain is unconditional.

### Still outstanding (not in this sweep)

Coach videos, extracted deck PDFs and learning artifacts still share one
R2 bucket for the same `put_coach_object_bytes` reason. Lower priority —
none of them is user voice — but the same pattern applies when it comes up.

---

## 4. Staging environment

### What landed in code

Staging can't be safe by being a copy of production; it has to be a copy
that is *prevented* from touching the real world. Three guards, all
enforced at boot by `services.secrets.audit()`:

| Check | Failure |
|---|---|
| `SUPABASE_URL == PRODUCTION_SUPABASE_URL` | staging is pointed at the production database |
| `STRIPE_SECRET_KEY` starts `sk_live_` | staging would bill real cards |
| `SEND_EMAILS=true` with no `EMAIL_REDIRECT_TO` | staging would email real students |

Plus `Config.EMAIL_REDIRECT_TO`: in any non-production environment,
`send_email_resend` sends **every** message to that one address, subject
tagged `[staging → real.user@example.com] ...`. Mail stays testable; real
users are unreachable.

`Config.is_staging` exists and is deliberately **not** folded into
`is_production` — staging must exercise the production code paths while
every production-only safety stays off.

### Provisioning

**Supabase** — a second project (`willab-staging`). Apply `migrations/`
in filename order; they are idempotent (`IF NOT EXISTS`). Seed with
synthetic data, **not** a production dump: a dump brings real voice
recordings and real emails into a lower-trust environment, which is a
GDPR problem, not just a testing one.

**R2** — `willab-staging-lab-audio` + `willab-staging-coach-media`.
Separate buckets, not separate prefixes: a prefix shares the lifecycle
rule and one bad delete script reaches production objects.

**Railway** — a second project, or a `staging` environment inside the
existing one. Two services, mirroring production: `web`
(`sh bin/railway-web.sh`) and `worker` (`sh bin/railway-worker.sh`), plus
its own Redis. Deploy from a `staging` branch, or from `main` with
auto-deploy off so a promotion is explicit.

**Vercel** — the FE's preview environment already exists; point its
`NEXT_PUBLIC_API_URL` (and BFF origin) at the staging backend, and add
that origin to staging's `CORS_ORIGINS`.

### Staging environment variables

```bash
ENV=staging

# Its own database — never production's
SUPABASE_URL=https://<staging-project>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<staging service role>
SUPABASE_JWT_SECRET=<staging jwt secret>

# The tripwire: set this to the PRODUCTION url so the boot audit can
# catch a mis-paste. It is not a credential — just a string to compare.
PRODUCTION_SUPABASE_URL=https://<production-project>.supabase.co

# Email goes to ONE inbox, never to users
SEND_EMAILS=true
EMAIL_REDIRECT_TO=qa@willpowerlab.com

# Test-mode payments only — a live key refuses to boot
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...        # staging endpoint's own secret

# Its own buckets
R2_BUCKET_NAME=willab-staging-coach-media
R2_LAB_AUDIO_BUCKET=willab-staging-lab-audio
R2_LAB_AUDIO_PUBLIC_BASE_URL=https://staging-lab-audio.willpowerlab.com

# Observability: separate env tag, no tracing (quota belongs to prod)
SENTRY_TRACES_SAMPLE_RATE=0
EXPOSE_ERROR_DETAILS=0                 # rehearse the production envelope

CORS_ORIGINS=https://staging.willpowerlab.com
```

`EXPOSE_ERROR_DETAILS=0` matters: it makes staging return the same generic
error envelope production does, so an FE error boundary that only works
against verbose dev errors fails in staging rather than in front of a user.

### Smoke test after provisioning

1. `GET /health` → 200.
2. `GET /health/jwks` → `jwks_accessible: true` (proves the staging
   Supabase keys resolve).
3. Record a take end-to-end → readout renders.
4. Trigger any email → it arrives at `EMAIL_REDIRECT_TO` with the
   `[staging → ...]` subject tag.
5. Deliberately set `STRIPE_SECRET_KEY=sk_live_...` → the service must
   **refuse to boot**. That confirms the guard is live rather than
   theoretically configured.

### Cost

Roughly $25–40/mo: Railway web + worker + Redis (~$15–25), Supabase Pro if
the free tier's limits bite (~$25, though free is usually fine for
staging), R2 negligible at staging volume.
