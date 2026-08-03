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
2. **Only 413 and 405 were handled**, so anything else — an unhandled
   exception, a 404, an `abort(400)` — rendered Werkzeug's HTML error page.
   The Next.js app then crashed trying to `JSON.parse` a `<!doctype html>`,
   on precisely the responses it most needed to degrade gracefully on.

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

```jsonc
// 429
{
  "code": "RATE_LIMITED",
  "error": "Too many requests. Please wait a moment and try again.",
  "retry_after_seconds": 60          // mirrors the Retry-After header
}
```

`retry_after_seconds` is the field the icebreaker regenerate endpoint has
always sent, so the FE has one shape to handle. The guest funnel keeps its
own copy ("Too many trial uploads — …") verbatim.

The body **never** contains flask-limiter's limit expression ("3 per 1
minute") — that is an internal detail, not copy.

`X-RateLimit-*` budget headers are **off** by default (`RATE_LIMIT_HEADERS=1`
to publish them). With them on, flask-limiter also stamps `Retry-After` on
*successful* responses, and a FE that backs off on "is `Retry-After`
present?" would throttle itself on every 200.

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
3. **Watch** `rate limited: POST <path> scope=<tier> retry_after=<n>s` in the
   logs for a day. Real users tripping a cap show up here first; raise the
   matching `RATE_LIMIT_*` env var if so — no redeploy of code needed.

Kill switch: `RATE_LIMIT_ENABLED=0`.

---

## 4. The JSON error contract

`services/error_contract.py::register(app, config)` installs all of it, and
`app.py` calls it last so it sits behind every blueprint.

| Status | `code` | When |
|---|---|---|
| 413 | `PAYLOAD_TOO_LARGE` | body over `MAX_CONTENT_LENGTH` (unchanged) |
| 405 | `METHOD_NOT_ALLOWED` | (unchanged) |
| 429 | `RATE_LIMITED` | see §1 |
| 4xx | derived from the status name — `NOT_FOUND`, `BAD_REQUEST`, `UNAUTHORIZED`, … | any other HTTP error |
| 500 | `INTERNAL_ERROR` | anything unhandled |

Three things the catch-all has to get right, all pinned by
`test_error_contract`:

1. **HTTPExceptions keep their own status.** They reach `errorhandler(Exception)`
   too — Flask's lookup walks the exception MRO and lands on `Exception`
   when nothing more specific matches — so a 404 must not become a 500. The
   413/405/429 handlers still win, because Flask checks code-keyed handlers
   before class-keyed ones.
2. **Sentry must still see crashes.** Registering `errorhandler(Exception)`
   *suppresses* Flask's `got_request_exception` signal, which is how
   sentry-sdk's Flask integration normally captures unhandled errors. The
   handler therefore captures explicitly. Without that, adding a nicer error
   page would have silently blinded Sentry — the single least obvious thing
   in this change.
3. **It re-raises where exceptions should propagate** (`app.debug`, or an
   explicit `PROPAGATE_EXCEPTIONS`), so the Werkzeug debugger and test
   tracebacks still work.

`error` text: an explicit `abort(400, "take_session_id is required")`
survives verbatim, but an untouched Werkzeug default collapses to the short
status name — their defaults are browser copy ("If you entered the URL
manually please check your spelling…"), which has no business in an API
contract.

Production never includes exception internals. Outside production the body
carries an extra `detail` field (`"RuntimeError: ..."`) for debugging.

---

## 5. Tests

```
python3 -m unittest test_rate_limits test_error_contract
```

`test_rate_limits.CoveredRoutesTests` is a static (AST) drift guard: it
fails if a paid route loses its decorator or a handler is renamed without
its cap. It does not claim the covered list is exhaustive — it claims these
surfaces stay covered.
