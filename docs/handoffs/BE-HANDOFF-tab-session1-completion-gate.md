# BE handoff — Session-1 completion gate (≥1 charisma + ≥1 stress + ≥60s)

Status: **NOT STARTED — three premise corrections + four FE-design decisions needed before I ship.**
Implementation is small once the design is settled (~80 LOC across one new endpoint + helper + tests). Want the answers in your reply so I don't have to round-trip.

---

## Three premise corrections

The brief is roughly right on intent but off on a few facts I need to call out:

### 1. The location `v2_flow_service.py` is wrong
The file exists but holds `compute_task_score` + `select_task_by_score_band` (homework-task picker). Has nothing to do with interview completion. **The actual finalize stub lives at `routes/v2_routes.py:17015` — `v2_public_interview_finalize`.** Today it just logs `funnel.end` and returns 200 unconditionally. No gate, no trigger chain.

### 2. The "tag each recording" caveat is already solved
`charisma_snippets.question_tone` (`"charisma" | "stress" | "ebcp"`) is set at every `POST /v2/public/interview/upload-answer` from the FE-supplied `question_tone` form field ([routes/v2_routes.py:12429](routes/v2_routes.py:12429)). **No new column needed.** The brief's "Add a prompt_intent column on recordings if not" caveat doesn't apply — we already have it on the per-snippet table, which is the granularity the gate needs.

### 3. "Trigger AI commentary + stickiness + signup CTA" is partially built
- AI commentary (`session_kpi_narrative`) generator: exists at `services/session_kpi_narrative.py::generate_session_kpi_narrative`.
- Stickiness: exists at `services/stickiness.py::compute_session_stickiness`.
- Signup CTA: **purely FE today**, no BE signal. If you want a BE-driven flag, that's a new contract.

The admin compute-metrics endpoint already chains both compute steps. The new finalize gate can call the same chain — no separate plumbing needed for the metric work.

---

## What's actually needed on BE — proposed contract (confirm or override)

### A. Gate predicate
A reusable helper that takes a guest_session_id and returns the readiness state:

```python
# services/interview_completion_gate.py (new)
def session_1_completion_state(guest_session_id: str) -> dict:
    """
    Returns:
      {
        "ready": bool,
        "criteria": {
          "has_charisma": bool,     # ≥1 snippet with question_tone='charisma'
          "has_stress":   bool,     # ≥1 snippet with question_tone='stress'
          "duration_ok":  bool      # sum(duration_ms) >= 60000
        },
        "current": {
          "charisma_count": int,
          "stress_count":   int,
          "total_duration_ms": int
        }
      }
    """
```

Pure function on the existing `charisma_snippets` rows. No DB writes, no LLM calls, no schema change.

### B. Probe endpoint (NEW)
So FE can enable/disable the "I'm done" button mid-funnel without trying to fake the gate client-side:

```http
GET /v2/public/interview/<guest_session_id>/completion-state
→ 200 { ready, criteria, current }   # the dict from §A above
→ 404 SESSION_NOT_FOUND
```

No auth. Reads only. Cheap (one indexed `charisma_snippets` query). FE polls or calls after each `upload-answer` response.

### C. Finalize endpoint — flip from stub to gated trigger
The existing `POST /v2/public/interview/finalize` at [routes/v2_routes.py:17015](routes/v2_routes.py:17015):

```http
POST /v2/public/interview/finalize
body { guest_session_id, total_duration_seconds?, reason? }

→ 200 {
    status: "ok",
    completion: { ready: true, criteria: {...}, current: {...} },
    next: {
      narrative_status: "generating" | "ready" | "failed",
      stickiness_status: "computing" | "ready" | "failed",
      signup_cta: { show: true, copy: "..." }     # only when ready
    }
  }

→ 422 {
    code: "SESSION_INCOMPLETE",
    error: "Need ≥1 charisma answer, ≥1 stress answer, and ≥60s of recording before finishing.",
    completion: { ready: false, criteria: {...}, current: {...} }
  }
```

### D. The trigger chain on a passing gate
Call `generate_session_kpi_narrative(session_id, overwrite=False)` and `compute_session_stickiness(...)` synchronously. They're already wired and fast (one LLM call each, ~3-5s total). FE blocks on the finalize response → sees `signup_cta: { show: true }` → renders the CTA.

If you want async (finalize returns immediately, FE polls a status endpoint), say so and I'll add a `GET /v2/public/interview/<guest_session_id>/post-finalize-status` for the polling. Sync is simpler and matches today's perceived latency (the existing compute-metrics endpoint is also sync).

---

## Four design decisions — your call

### Q1. Hard or soft gate?
- **Hard (recommended)**: `/finalize` returns 422 SESSION_INCOMPLETE when criteria fail. FE must call `/completion-state` first OR catch the 422 defensively. Server is the authority — admin can't accidentally short-circuit the funnel by sending finalize early.
- **Soft**: `/finalize` always returns 200 but with `completion.ready: false`. FE decides whether to honor it. Less server-authoritative but more permissive (a future product change to relax the gate is config-only).

### Q2. Sync or async trigger chain?
- **Sync (recommended)**: finalize blocks ~3-5s while narrative + stickiness compute, returns with both ready. FE renders signup CTA from the same response. Single round-trip, simple state machine.
- **Async**: finalize returns immediately (200 with `narrative_status: "generating"`), FE polls a new status endpoint until `ready`. More complex but masks LLM latency from the user.

### Q3. Signup CTA — BE-driven flag or pure FE?
- **BE flag (recommended)**: `next.signup_cta: { show, copy }` in the finalize response. Single source of truth; if you want to A/B the CTA copy later, it's a config flip.
- **Pure FE**: `next.signup_cta` field omitted. FE decides what CTA to show based on `completion.ready` alone.

### Q4. Re-finalize behavior?
- **Idempotent (recommended)**: second `/finalize` call on the same session re-returns the same payload, no recompute (narrative + stickiness columns are already populated). Cheap. Safe under double-click.
- **Reject**: second call returns 409 ALREADY_FINALIZED. Stricter but requires FE to manage the click-once state. Slightly worse UX.

---

## What FE needs to do (after answers)

- **Wire the probe endpoint** (`GET /completion-state`) into the recorder UI to enable/disable the "I'm done" button based on `ready`. Optional UX polish: surface the failing criterion ("Record one more stress-prompted answer to finish") so the user knows what's missing.
- **Wire the finalize trigger chain consumption** — handle the 422 SESSION_INCOMPLETE defensively, render the CTA from `next.signup_cta` if you pick Q3=BE flag.
- Nothing more. No schema change, no FE state-machine change beyond what `completion.ready` drives.

---

## Acceptance criteria (when BE ships, given Q1=hard, Q2=sync, Q3=BE flag, Q4=idempotent)

1. Guest session with 0 stress snippets → `GET /completion-state` returns `{ ready: false, criteria: { has_stress: false, ... } }`. `POST /finalize` returns 422.
2. Guest session with 1 charisma + 1 stress + 45s total → 422 (duration fails).
3. Guest session with 1 charisma + 1 stress + 60s total → `/completion-state` returns `{ ready: true }`. `POST /finalize` returns 200 with `narrative_status: "ready"`, `signup_cta.show: true`.
4. Re-`POST /finalize` on a passed session → same 200 payload, no recompute.
5. `funnel.end` log line still fires per the existing stub behavior, regardless of gate outcome (analytics signal preserved).

---

## Reply with

Four single-letter answers (Q1=H/S, Q2=Sync/Async, Q3=BE/FE, Q4=I/R). Defaults above are my recommendations — pick "all defaults" if you want to ship the path of least resistance. Once confirmed I ship in one commit + add a `test_interview_completion_gate.py` covering the three criteria + the trigger chain.
