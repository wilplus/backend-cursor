# Clear steps to make the homework flow work

Follow these in order. All work is in the **frontend** and **BFF**; backend and Supabase are already in place.

**Where to implement:**  
- **Backend (this repo):** No code changes needed. GET session/status, recording-upload-url, recording-1/2, task-block, metric-answers, questions, post-answers, recording-metrics-chunk are implemented and return the shapes in `docs/EXAMPLE-GET-SESSION-STATUS-RESPONSES.md`.  
- **Frontend + BFF (other repo):** Implement the steps below in your Next/React app and BFF routes. Use this doc as the checklist.

You now have confirmed **real GET session/status payload shapes** and a clear list of mismatches the frontend must stop assuming: `task_block`, `final_task`, `report_text`, and a questions list in status.

---

## Frontend implementation summary (reference)

The following was implemented in the frontend (for reference; this repo is the backend).

- **Pre-checks:** Backend target via BFF/env; mapping strategy = read API in snake_case, normalize in `deriveStepFromStatus` / `applyStatusToState`, camelCase in React state.
- **Status-first + has_active_session:** GET status handler clears full session state when `has_active_session === false` or no session id; otherwise calls `applyStatusToState(statusRes)` so step is overwritten from response.
- **Session id:** `sessionId = statusRes.session_id ?? statusRes.session?.id ?? null` in `applyStatusToState`; guards in handlers so no session-scoped calls without valid sessionId.
- **Field mapping (deriveStepFromStatus):** warmUpText from `warm_up_task?.text ?? warm_up_task_text ?? session.warm_up_task_text`; taskBlock from `task_block` if present else built from `session_metric_question_1/2/3`; finalTaskText from `session.final_task_text ?? final_task_text ?? toText(final_task)`; reportText from `report_text ?? session.context_long`; performanceScoreEnd from `performance_score_end ?? session.performance_score_end`.
- **Types:** `HomeworkSessionStatus` extended with `session` (id, status, warm_up_task_text, final_task_text, context_long, performance_score_end, session_metric_question_1/2/3), `has_active_session`, optional `session_id`.
- **Step 4:** Existing effect already GET questions when step === 4 and questions empty (fetch-on-demand).

Order used: (1) status-first + has_active_session in getStatus handler, (2) session id in applyStatusToState, (3) field mappings in deriveStepFromStatus, (4) types. Frontend files: `HomeworkFlowCard.tsx`, `types-homework.ts`.

---

## Before you start — two pre-checks

Do these so you don’t implement against the wrong environment or mix naming styles.

**1) Confirm your frontend is hitting the backend you think it is**  
Same domain/env as the example JSON in `docs/EXAMPLE-GET-SESSION-STATUS-RESPONSES.md`. If the frontend talks to a different API (e.g. staging vs prod, or a mock), the response shape may differ and the mapping will break.

**2) Pick one mapping strategy**

- **Option A:** Keep **snake_case** everywhere in UI state (read backend keys as-is).
- **Option B:** **Normalize once** in `applyStatusToState()` and use **camelCase** internally everywhere else **(recommended)**.

Stick to one; don’t mix ad-hoc reads of snake_case in some components and camelCase in others.

---

## Implementation order (test after each step)

Implement in this order so you can verify behavior at each stage:

1. **Status-first step derivation**  
   Step = map from `session.status` (warm_up → 1, task_block → 2, final_task_ready → 3, post_questions → 4, completed → 5).  
   If `has_active_session: false`: clear session state and show “Start”.

2. **Session id normalization**  
   `sessionId = res.session_id ?? res.session?.id ?? null`.  
   Guard: no sessionId ⇒ no session-scoped API calls.

3. **Replace missing fields with correct ones**  
   - Warm-up: `warm_up_task.text` or `session.warm_up_task_text`  
   - Step 2 questions: `session_metric_question_1` / `_2` / `_3` (build taskBlock locally)  
   - Final task: `session.final_task_text`  
   - Report: `session.context_long`  
   - Performance score: `session.performance_score_end`

4. **Fetch-on-demand only where needed**  
   Step 4: fetch questions using `post_question_ids` (status does not include the question list).

The phases below follow this order in detail. If you paste your current **`applyStatusToState()`** and **`deriveStepFromStatus()`**, the exact lines to change can be pointed out to match the backend contract with minimal risk.

---

## Phase 1: Status as source of truth (fixes 409 and wrong step)

### Step 1 — Map status response correctly

- Add or update **`applyStatusToState(statusRes)`** in one place (e.g. homework flow component or util).
- **Do not** read `task_block`, `final_task`, or `report_text` from the response; the backend does not send those.
- Use this mapping (backend uses **snake_case**):

  | Your state      | From response |
  |-----------------|----------------|
  | sessionId       | `res.session_id ?? res.session?.id ?? null` |
  | status          | `res.session?.status ?? null` |
  | warmUpText      | `res.warm_up_task?.text ?? res.session?.warm_up_task_text ?? ""` |
  | step 2 questions| `res.session?.session_metric_question_1`, `_2`, `_3` (build taskBlock from these if needed) |
  | finalTaskText   | `res.session?.final_task_text ?? ""` |
  | reportText      | `res.session?.context_long ?? ""` |
  | performanceScoreEnd | `res.session?.performance_score_end ?? null` |

- Derive **step** only from **status**:  
  `warm_up` → 1, `task_block` → 2, `final_task_ready` → 3, `post_questions` → 4, `completed` → 5.

**Ref:** `docs/EXAMPLE-GET-SESSION-STATUS-RESPONSES.md` §4 (full contract and minimal mapping).

---

### Step 2 — Overwrite step from status every time

- On **every** successful **GET session/status**, overwrite the UI step from `session.status`. Do **not** keep the previous step.
- If **`has_active_session: false`** (or `session` is null): clear `sessionId`, `session`, and step; show “Start homework”; do **not** call any session-scoped API until **POST session/start** has returned a new session id.

---

### Step 3 — Load and resume

- When the user enters the homework screen: call **GET session/status**.
- If `has_active_session` is true and `session` is non-null → call `applyStatusToState(response)`.
- If `has_active_session` is false or session is null → clear sessionId and step; show “Start homework”; do not call recording-upload-url or recording-metrics-chunk until after **POST session/start**.

---

### Step 4 — Guard recording-upload-url by step

- Call recording-upload-url with **`recording: "1"`** only when **current step is 1** (status `warm_up`).
- Call with **`recording: "2"`** only when **current step is 3** (status `final_task_ready`).
- Never call it for recording "1" when the user is already on step 3.

---

### Step 5 — Refetch status after each step-advancing action

- **After recording-1 succeeds:** Call GET session/status, then `applyStatusToState(response)`. Do not set step or taskBlock from the recording-1 response.
- **After metric-answers succeeds:** Call GET session/status, then `applyStatusToState(response)`. Do not set step or finalTaskText from the metric-answers response.
- **After recording-2 succeeds:** Call GET session/status, then `applyStatusToState(response)`. Do not set step or questions from the recording-2 response. If after apply you are on step 4 and questions are empty, then call **GET questions** and set questions from that.

---

## Phase 2: No blank screens (step 2 and 4 content)

### Step 6 — Step 2 (metric questions)

- If the backend does **not** expose **GET task-block**, do **not** call it. Build the task block from `session_metric_question_1`, `session_metric_question_2`, `session_metric_question_3` in status (IDs can be null/synthetic).
- If the backend **does** expose GET task-block, you may call it when **step === 2** and task block is still missing, and set taskBlock from the response.
- Implement this in a single place (e.g. `applyStatusToState` or a `useEffect` when step === 2 && !taskBlock).

---

### Step 7 — Step 4 (post-questions)

- Status only has **`post_question_ids`**; it does not include the question list. When **step === 4** and questions are empty, call **GET questions** (with current sessionId) and set questions from the response.

---

### Step 8 — Step 5 (report)

- Use **`session.context_long`** for reportText when status is `completed`. If `context_long` is absent (e.g. still generating), show “Report pending”. Do **not** assume a separate GET report endpoint exists.

---

## Phase 3: BFF — recording-metrics-chunk (wheel)

### Step 9 — BFF route for chunks

- Ensure the BFF has a route: **POST** `.../api/homework/session/[sessionId]/recording-metrics-chunk` that proxies to the backend **POST** `/v2/homework/session/:id/recording-metrics-chunk` with the same body (arrayBuffer) and auth.
- If using Next 15: `params` is a Promise — use `const { sessionId } = await params;` and ensure sessionId is defined (return 400 if not).
- Forward headers: X-Sample-Rate, X-Seq, X-T-Ms (map X-Chunk-Seq / X-Chunk-Start-Ms if your client sends those).
- Send **Authorization: Bearer &lt;student token&gt;** to the backend.

**Ref:** `docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts` in this repo.

---

### Step 10 — Frontend: chunk URL and lifecycle

- The chunk pipeline must POST to **same-origin** `/api/homework/session/:sessionId/recording-metrics-chunk` (your BFF), not to another host.
- Start sending chunks when the user is on the step that shows the wheel (step 1 or 3). Do not tear down the pipeline on re-render when only state from `applyStatusToState` updates; keep it running until the user leaves the step or submits.
- When recording-metrics-chunk returns 200, use the response (e.g. voiced_ratio, pause_score) to update the wheel UI so the indicator moves.

---

## Phase 4: Upload (avoid 403)

### Step 11 — Bucket and RLS

- Use the **bucket** value returned by **recording-upload-url** (e.g. `audio_recordings`). Do not hardcode a different bucket.
- Confirm Supabase Storage RLS allows INSERT for the user on that bucket (see `docs/SUPABASE-STORAGE-RLS-AUDIO-RECORDINGS.md`).

---

## What looks solid (no changes needed in principle)

If these are implemented as in the plan and the “Frontend implementation summary” section above:

- **Status-first step derivation** from `session.status` with overwrite on every GET session/status.
- **Session id normalization:** `session_id ?? session?.id`.
- Correct mapping: metric questions from `session.session_metric_question_1/2/3`, final task from `session.final_task_text`, report from `session.context_long`.
- **Step 4 fetch-on-demand** for questions.

That removes the main “wrong step / INVALID_SESSION_STATE / missing fields → fallback text” class of bugs.

---

## Remaining gaps / risks (confirm these 5 items)

Even with status/step mapping correct, these can still break the flow. **Explicitly verify each.**

### 1) BFF auth forwarding consistency (critical)

If any BFF route proxies to Flask **without** the student’s auth (Authorization header or cookie), you can get `has_active_session: false`, `SESSION_NOT_FOUND`, or `INVALID_SESSION_STATE` even when the session exists.

**Verify every homework BFF route forwards auth**, not just status:

- `/api/homework/session/status`
- `/api/homework/session/start`
- `/api/homework/session/[id]/recording-upload-url`
- `/api/homework/session/[id]/recording-1`
- `/api/homework/session/[id]/recording-2`
- `/api/homework/session/[id]/recording-metrics-chunk`
- Questions endpoints

If one drops auth, session-scoped calls will fail.

---

### 2) Wheel pipeline must not use localhost ingest

Calls to `http://127.0.0.1:7242/ingest/...` will always fail in production (mixed content + CORS).

**Confirm:**

- Chunk pipeline **always** POSTs to **same-origin** `/api/homework/session/:id/recording-metrics-chunk`.
- It **never** uses localhost in production builds.

---

### 3) Start/stop gating for metrics-chunk (prevents retry storms)

If the pipeline runs while backend status is `task_block` (step 2), you get “not in recording state” and many failed requests.

**Confirm:**

- Start metrics-chunk **only** when step is **1 or 3** *and* recorder is active.
- Stop when leaving those steps or when recording stops.
- Use backoff / stop-on-error so the client doesn’t hammer the endpoint.

---

### 4) Storage upload: RLS + bucket correctness

Even with session logic fixed, **Send** can fail if:

- Bucket name mismatches (e.g. frontend uses `recordings` but backend returns `audio_recordings`, or vice versa).
- Storage RLS doesn’t allow INSERT (and UPDATE if using `upsert: true`) for `auth.uid()/…`.

Phase 4 (bucket from API + RLS) is not optional—just separate from status mapping.

---

### 5) Auto-start behavior: retry path

When `has_active_session: false` → clear state → call `handleStart()`, if start fails (network, auth, backend down) the user can get stuck (e.g. `autoStartAttempted` blocking retries).

**Confirm:**

- There is a visible **“Start / Retry”** control that calls start again.
- `autoStartAttempted` (or equivalent) does **not** permanently block retries.

---

## Definition of Done (run after implementation)

In DevTools Network, verify this progression:

| Step | Expectation |
|------|-------------|
| Load | `GET /api/homework/session/status` returns active session with `session.status: warm_up` (or triggers start). |
| Step 1 | `POST recording-upload-url` 200 → Storage upload 2xx → `POST recording-1` 200 → then `GET status` returns `task_block`. |
| Step 2 | Metric submit → `POST metric-answers` 200 → `GET status` returns `final_task_ready` with `session.final_task_text`. |
| Step 3 | recording-upload-url (recording "2") 200 → upload → recording-2 200 → status becomes `post_questions`. |
| Step 4 | Submit → status becomes `completed` with `context_long` and `performance_score_end`. |
| Wheel | During step 1 and 3, `recording-metrics-chunk` returns 200 repeatedly and the wheel moves. |

---

## How to “finish” it

1. **Run the Definition of Done** network progression above.
2. **If something breaks**, paste **one** failing request so the last 1–2 integration issues can be fixed quickly:
   - **Request URL**
   - **Status code**
   - **Response body** (JSON or text)
   - **For Storage failures:** bucket name, object path, and whether the request had an **Authorization** header (or cookie)

---

## Summary checklist

| # | Done | What |
|---|------|------|
| 1 | ☐ | `applyStatusToState` with correct mapping (snake_case; no task_block/final_task/report_text) |
| 2 | ☐ | Overwrite step from status every time; clear state when has_active_session false |
| 3 | ☐ | On load: GET status → apply or clear; no session APIs until POST start when no session |
| 4 | ☐ | recording-upload-url only when step 1 (rec "1") or step 3 (rec "2") |
| 5 | ☐ | After recording-1, metric-answers, recording-2: GET status → applyStatusToState |
| 6 | ☐ | Step 2: build task block from status fields; call GET task-block only if backend has it and block missing |
| 7 | ☐ | Step 4: GET questions when questions empty |
| 8 | ☐ | Step 5: reportText from context_long; "Report pending" if absent |
| 9 | ☐ | BFF: POST recording-metrics-chunk route (params, headers, auth) |
| 10 | ☐ | Frontend: chunk URL to BFF; pipeline lifecycle; update wheel from response |
| 11 | ☐ | Use bucket from API; verify Storage RLS |
| **12** | ☐ | **Confirm 5 remaining gaps** (BFF auth, no localhost wheel, chunk gating, storage RLS, start retry) |

---

**Full detail:** `docs/IMPLEMENT-THIS-TO-MAKE-FLOW-WORK.md`  
**Response shape and contract:** `docs/EXAMPLE-GET-SESSION-STATUS-RESPONSES.md` §4  
**Wheel not working:** `docs/FIX-WHEEL-NOT-WORKING.md` — checklist (BFF route, auth, same-origin URL, step gating, using response.pause_score).

**Sanity check:** If you paste BFF code for `/api/homework/session/status` and `/api/homework/session/[sessionId]/recording-upload-url`, auth forwarding and production-safe paths can be verified.
