# Rate limits + the JSON error contract

Status: **BE SHIPPED, rate limiting ON by default.** It becomes a *global*
cap the moment `REDIS_URL` is set on the web service (§3) — until then it
still caps, but per-worker. The error contract needs no config at all.

The debt this retires, in two halves:

1. **Every authenticated Whisper/LLM endpoint was uncapped.** One client
   retry loop could run the OpenAI bill up with nothing on the backend
   saying no. The only limiter anywhere was an in-process dict on the guest
   funnel — per gunicorn worker, so the *real* cap was `stated cap x
   workers`, and it reset on every restart. (A second such dict guarded the
   icebreaker regenerate endpoint with the same flaw.)
2. **429 had no place in the JSON error contract.** The app-wide net that
   landed in #329 (`utils/errors.py`) turns every other failure into
   `{code, error, ref}`, but a throttled caller needs two things it can't
   supply: how long to wait, and the guest funnel's own copy. See §4 —
   including why this branch's own error module was deleted rather than
   shipped alongside it.

---

## 1. Rate limits

`services/rate_limits.py` owns every cap. Counters live in the **same Redis
the pipeline queue already needs**, namespaced by `RATELIMIT_KEY_PREFIX`
(`willab-rl`), so one number holds across every worker and every instance.

### Keys

Buckets are keyed on the **authenticated subject** when a Bearer token is
present, else the client IP (`X-Forwarded-For` first, like the rest of the
codebase).

The subject is read **without verifying the signature**, on purpose: the
limiter runs before `@require_auth`, verifying would mean a JWKS round-trip
on every request, and a forged `sub` only buys a fresh bucket for a request
that then 401s — without spending a cent on OpenAI. Keying on the subject
rather than the IP is what makes the cap mean something: a loop can rotate
its source address, not its user id.

### Tiers

| Tier | Env | Default | What it guards |
|---|---|---|---|
| `whisper_limit` | `RATE_LIMIT_WHISPER` | `20/min; 200/hr` | audio upload → transcription |
| `llm_limit` | `RATE_LIMIT_LLM` | `30/min; 400/hr` | one interactive LLM call |
| `heavy_limit` | `RATE_LIMIT_HEAVY` | `10/min; 100/hr` | multi-call generation, media, training |
| `regenerate_limit` | `RATE_LIMIT_REGENERATE` | `1/min` per `session_id` | icebreaker double-click guard (`force=true` bypasses) |
| `guest_funnel_limit` | `GUEST_FUNNEL_RATE_LIMIT_PER_IP_PER_HOUR` / `_GLOBAL_PER_HOUR` | `5/hr` per IP, `200/hr` global | the anonymous funnel (unchanged caps) |

Defaults are sized against **the threat** — a client loop doing 10+ req/s —
not against tidiness. They sit far above what a human doing real work
produces, because a limit that trips during a real session breaks the live
loop, which is a hard REJECT. **Raise them in env before raising them in
code.**

### What is capped, and what is deliberately not

Capping is **opt-in per route**: there are no default limits, so anything
undecorated is unlimited. That is the point — health probes, the internal
cron webhooks and the FE's polling GETs must never be capped, and an opt-in
list cannot accidentally take out a surface nobody thought about.

Decorated today (see `test_rate_limits.CoveredRoutesTests`, which fails if
one is dropped):

- **Whisper** — `POST /v2/lab/recordings`, `POST /v2/coach/annotation-uploads`,
  `POST /v2/coach/training-imports`
- **LLM** — `/v2/chat/query`, `/v2/chat/snippet-followup`, `/v2/coaching/turn`,
  `/v2/coaching/state-machine/turn`, `/v2/coaching/start`,
  `/v2/coaching/intro-bubble`, `/v2/user/chat/first-question`,
  `/v2/user/coaching/self-rating`, `/v2/onboarding/opener/{start,next}`,
  `/v2/coach/snippets/<id>/say-it-stronger`,
  `/v2/admin/users/<id>/directives-queue/suggest`,
  `/v2/explore/arc/<id>/ideal-text/save`,
  `/v2/explore/arc/<id>/blocks/<key>/decide`,
  `/v2/explore/arc/<id>/prior-take/decide`,
  and the life-panel LLM routes (`/v2/life/{board,notes,cases,lookup}`,
  `/v2/life/proposals/<id>/approve`)
- **Heavy** — `/v2/lab/presentation/extract`, `/v2/admin/learning/train`,
  `/v2/coach/arc/<id>/verify`, `/v2/coach/arc/<id>/ideal-text/approve`,
  `/v2/coach/sessions/<id>/{recut,video}`,
  `/v2/coach/sessions/<id>/snippets/<id>/breakthrough-video`,
  `/v2/life/setup/{complete,propose-from-document}`, `/v2/life/wins/derive`

Two deliberate exclusions worth knowing:

- **`PUT /v2/explore/arc/<id>/ideal-text/user-edit`** spends nothing on
  OpenAI and may be autosaved by the FE. Capping it would buy no protection
  and could break typing.
- **FE-polled GETs** (`/v2/life/day`, the ideal-text and readout GETs) are
  uncapped even where they can lazily generate, because their generators are
  `ensure_`-shaped: the first call generates, the rest are cheap reads.

### The 429 response

See **§4** — it rides `utils/errors.py`'s envelope, plus
`retry_after_seconds`. The guest funnel keeps its own copy ("Too many trial
uploads — …") verbatim.

---

## 2. Live-loop safety

A limiter sits in front of every capped request, so its failure modes matter
more than its features. Each of these is verified in
`test_rate_limits.LiveLoopTests`:

| Failure | Behaviour |
|---|---|
| `flask_limiter` not installed | null limiter — decorators become identities, app boots, nothing capped |
| `RATE_LIMIT_ENABLED=0` | registered but off |
| `REDIS_URL` unset | `memory://` — still capped, but per-worker and lost on restart. Logged as a **boot WARNING** |
| broker unreachable / refused | `swallow_errors` + in-memory fallback; flask-limiter re-probes Redis on exponential backoff |
| broker **blackholed** (packets dropped) | bounded by `socket_connect_timeout=2` / `socket_timeout=2` |
| storage URI malformed | `init_app` logs and continues; app serves uncapped |

That last-but-one row is the one to not "clean up": **without those socket
timeouts a blackholed broker hangs every request forever.** Measured, not
theoretical — same fail-fast contract as `services/job_queue.py`.

Strategy is `moving-window` (override with `RATE_LIMIT_STRATEGY`). It
preserves the guest funnel's documented sliding 1-hour window and denies the
burst-at-the-boundary that `fixed-window` allows — where a client can spend
2x the cap across a window edge.

---

## 3. Rollout

Nothing to migrate; no tables, no columns.

1. **Deploy.** Rate limiting is on immediately, backed by `memory://`. The
   caps apply per worker — weaker than the stated number, but strictly more
   protection than none. The boot log says so:
   `rate_limits: active but storage is IN-PROCESS (memory://) …`
2. **Set `REDIS_URL` on the WEB service** (the worker service already has
   it — same Railway Redis plugin, and the limiter namespaces its keys, so
   sharing it with the queue is safe). Redeploy. The boot log flips to
   `rate_limits: active, durable storage (shared across workers) …` and the
   caps become global.
3. **Watch** `rate limited [ref=…] POST <path> scope=<tier> retry_after=<n>s` in the
   logs for a day. Real users tripping a cap show up here first; raise the
   matching `RATE_LIMIT_*` env var if so — no redeploy of code needed.

Kill switch: `RATE_LIMIT_ENABLED=0`.

---

## 4. The JSON error contract

**This is now owned by `utils/errors.py` (PR #329), not by this work.**

This branch originally carried its own `services/error_contract.py`. While
it was in review, #329 landed a global JSON error net that does the same job
and more — a `ref` correlation id shared by the client envelope, the log
line and the Sentry event, plus `scrub()` redaction of secret- and
path-shaped substrings. Keeping both would have meant two competing
`errorhandler(Exception)` registrations on one app, with whichever
registered last silently winning. The duplicate was deleted; #329's net
stands.

What this branch still contributes is **the 429**, registered by
`services/rate_limits.py::register_429` (called from `init_app`):

```jsonc
// 429
{
  "code": "RATE_LIMITED",
  "error": "Too many requests — slow down and try again.",
  "ref": "a1b2c3d4",                 // utils.errors correlation id
  "retry_after_seconds": 60          // mirrors the Retry-After header
}
```

It has to win over the generic `HTTPException` handler, and it does: Flask
resolves the code-keyed handler (429) before the class-keyed one, whenever
each was registered. It has to win because the generic net would drop the
two things a throttled caller actually needs — how long to wait, and the
guest funnel's own copy ("Too many trial uploads — …").

The generic 429 sentence is **not** duplicated here: `breach_message()`
returns `None` unless a limit carries its own `error_message`, so
`utils.errors._STATUS_COPY[429]` supplies it. One source of truth.

The body never contains flask-limiter's limit expression ("3 per 1 minute")
— that is an internal detail, not copy.

`X-RateLimit-*` budget headers are **off** by default (`RATE_LIMIT_HEADERS=1`
to publish them). With them on, flask-limiter also stamps `Retry-After` on
*successful* responses, and a FE that backs off on "is `Retry-After`
present?" would throttle itself on every 200.

## 5. Tests

```
python3 -m unittest test_rate_limits
```

(The error-contract tests went with the duplicate module — `utils/errors.py`
carries its own coverage from #329.)

`test_rate_limits.CoveredRoutesTests` is a static (AST) drift guard: it
fails if a paid route loses its decorator or a handler is renamed without
its cap. It does not claim the covered list is exhaustive — it claims these
surfaces stay covered.
