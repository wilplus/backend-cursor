# BE handoff — push the analysis-state flip (kill the FE's 2s status polling)

Status: **NOT STARTED.** FE half shipped 2026-08-03 (frontend-cursor #232,
`fb831b4`). Implementation here is small (~30 LOC + tests at ONE choke point).
Founder queued this 2026-08-04.

`FILTER: ADVANCE-F1-SURFACE — cat {F1-SURFACE} — fences {clear: plumbing-state
payload only (AC-9), push-first with poll fallback (LIVE LOOP)} — locks {clear}
— redirect: n/a`

---

## Context — what the FE shipped and what still polls

frontend-cursor #232 replaced the Lab's 2s / Lounge's 5s **client** polling of
`GET /v2/lab/recordings/<id>/readout` with one SSE stream from the FE's BFF.
But the BFF bridge still polls THIS backend server-side at the same 2s cadence
per in-flight job — the browser↔Vercel churn is gone, the Vercel↔Flask churn
is not. This handoff is the backend half: push the state flip so nothing polls.

The per-tick cost here is small but real: while `analysis_state='processing'`
the readout GET returns early after one session SELECT
([routes/v2/lab_recording.py:1042](../routes/v2/lab_recording.py)) — the cost
is a request cycle **occupying one of the web tier's 2 sync gunicorn workers**
every 2s per processing user, not computation.

---

## Decision: do NOT build native SSE on the current web tier

The FE's events route documents an upstream SSE contract
(`GET /v2/lab/recordings/<id>/events`, `text/event-stream`) and auto-upgrades
to passthrough if this backend ever serves it. **Do not implement it on
today's config.** The web service runs 2 sync gunicorn workers
(`bin/railway-web.sh`, warmup contract in `gunicorn_conf.py`): every held-open
SSE connection parks a worker for its lifetime, so TWO concurrent processing
users would starve the entire backend — uploads, chat, coach, everything.
That is a live-loop outage built from a UX nicety.

Rejected alternatives, so we don't re-litigate:

| Option | Why not |
|---|---|
| gevent/eventlet workers to make SSE cheap | Monkey-patching + the numba/librosa `post_worker_init` warmup contract + `--timeout 1800` upload semantics is a risky, all-surface migration to serve one status signal. |
| Dedicated async SSE sidecar service | New Railway service = new cost + operational surface for a signal Supabase already delivers free. |
| Supabase `postgres_changes` on `v2_sessions` for guests | Guest sessions have `user_id IS NULL`; letting the `anon` role SELECT unclaimed rows (required for the realtime filter to match) would let anyone **enumerate unclaimed session UUIDs — and the UUID is the capability** in the guest trust model ([routes/v2/lab_recording.py:1012](../routes/v2/lab_recording.py)). Capability leak → rejected. Authed-only push would strand the guest funnel, which is exactly where the Lab polling lives. |

The SSE contract stays on file: if the stack ever moves to async workers, the
FE upgrades itself with zero FE changes.

---

## Recommended: Supabase Realtime **broadcast** at the state flip

The moment of the flip is already a single choke point:
`db.set_session_analysis_state` ([services/db.py:10525](../services/db.py)).
Every execution mode funnels through it — the daemon path
(routes/v2/lab_recording.py:824/858/863/870), the RQ worker + recovery sweeps
(services/pipeline_jobs.py:197/327/338), and training imports
(services/training_import.py). Instrument that one method and every mode,
including CAS-guarded recovery, broadcasts for free.

Broadcast channels fit the guest trust model exactly: **the channel NAME is
the capability** (contains the session UUID), nothing is enumerable, no RLS
change, no table exposure. The FE already runs supabase-js and already ships
the two-tier push-primary/poll-fallback pattern
(frontend-cursor `usePublishLiveSubscription`).

### Contract (FE will build against this verbatim)

- Channel (topic): `lab-session-{session_id}`
- Event name: `analysis_state`
- Payload: `{"session_id": "<uuid>", "analysis_state": "processing" | "ready" | "failed"}`

**Payload is mechanical plumbing state ONLY — never the readout, never scores,
never verdicts.** Same AC-9 split-sink rule as the job-status route
([routes/jobs.py:8](../routes/jobs.py)): push says "state changed", the
existing readout GET serves the content. On `ready`/`failed` the FE does ONE
readout fetch and stops listening.

### Implementation sketch

Inside `set_session_analysis_state`, after the successful `.update()`:

```python
# services/realtime_notify.py (new, ~20 LOC)
def broadcast_analysis_state(session_id: str, state: str) -> None:
    """Best-effort realtime nudge. MUST never raise: the FE keeps its
    poll fallback, so a lost broadcast costs latency, not correctness."""
    try:
        requests.post(
            f"{SUPABASE_URL}/realtime/v1/api/broadcast",
            headers={"apikey": SERVICE_KEY,
                     "Authorization": f"Bearer {SERVICE_KEY}"},
            json={"messages": [{
                "topic": f"lab-session-{session_id}",
                "event": "analysis_state",
                "payload": {"session_id": session_id,
                            "analysis_state": state},
                "private": False,
            }]},
            timeout=2,
        )
    except Exception:
        logger.debug("analysis-state broadcast skipped sid=%s", session_id)
```

Notes for the implementer:

- One-shot REST send (no websocket client in the worker); verify the current
  broadcast endpoint shape against Supabase docs at build time — the sketch's
  URL/body may have drifted.
- supabase-py is pinned 2.6.0 (services/db.py:68 comment); its realtime
  send support is not something to depend on — hence plain HTTP.
- `timeout=2` and swallow-everything are load-bearing: this fires inside the
  worker's pipeline and inside recovery sweeps; a slow/broken Realtime must
  cost nothing (best-effort, same posture as `set_session_analysis_state`
  itself).
- Fire AFTER the DB write succeeds, never before (the poll fallback must
  agree with what push announced).
- Free-tier budget: ~2–3 messages per take (processing → ready/failed)
  against Supabase free tier's ~2M realtime messages/month — negligible.

### Tests

Mirror the house style (see `test_db_session_status.py`,
`test_processing_jobs.py` fakes):

1. Flip to each of processing/ready/failed → broadcast called once with the
   contract payload; topic embeds the session id.
2. Broadcast raising/timeout → `set_session_analysis_state` still returns
   True and the update persists (never raises, never blocks the pipeline).
3. Failed `.update()` (missing column path, services/db.py:10541) → NO
   broadcast (push must not announce a write that didn't land).

---

## FE follow-up (ours, frontend-cursor — not this repo's work)

Once this ships, FE adds the broadcast subscription as the PRIMARY tier of
`useLabReadoutLive` (supabase-js `channel("lab-session-<id>")`), keeping the
existing SSE-bridge and 2s poll as fallback tiers, then retires the bridge's
server-side 2s upstream polling to fallback-only. FE will confirm the contract
above before building; any change to topic/event/payload names needs a ping
back to FE first.

## Open question for founder (non-blocking)

The same broadcast pattern trivially extends to the admin-publish signal the
FE currently gets via `postgres_changes` on `v2_sessions`
(+ 20s poll fallback). Not in scope here; flagging that consolidation is
available if we ever want one push mechanism instead of two.
