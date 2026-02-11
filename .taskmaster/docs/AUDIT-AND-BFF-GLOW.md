# Audit checklist, BFF rationale, and glow removal

Use this when auditing the frontend against taskmaster contracts or when deciding which BFF routes to use.

---

## 1) Audit: files and punch-list

To get a **line-level punch-list** (with code snippets), you need the **frontend** repo or these files (this repo is backend-only and doesn’t contain them):

- `src/components/homework/HomeworkFlowCard.tsx`
- `src/lib/api/homework-client.ts`
- `src/components/homework/AnswerMetricQuestionsScreen.tsx`
- `src/components/recording/AudioRecorder.tsx`
- All routes under `src/app/api/homework/session/**`

**How to run the audit:** Open the frontend repo in Cursor (or paste the file contents), then ask: “Audit these files against the taskmaster contracts in AUDIT-AND-BFF-GLOW.md and give a concrete checklist of changes with code snippets.” The criteria are below.

### What to verify (taskmaster contracts)

**Status → step source of truth**

- Step derived **only** from `GET /api/homework/session/status` → `session.status`.
- On every successful status fetch: **overwrite** step + all step-derived state (no “preserve previous step” logic).

**Session identity + lifecycle**

- `sessionId = res.session_id ?? res.session?.id`.
- When `has_active_session: false`: clear session state and **do not** call any session-scoped endpoints until POST start returns a session id.
- Ensure “completed” sessions aren’t treated as active (frontend should see none active and start a new one).

**Field mapping (snake_case)**

- Warm-up: `warm_up_task.text` or `session.warm_up_task_text`.
- Step 2 questions: build from `session_metric_question_1/2/3` (not `task_block`).
- Final task: `session.final_task_text`.
- Report: `session.context_long` (fallback “Report pending.”).
- Score: `session.performance_score_end`.

**Mutations + refetch**

- After `recording-1`, `metric-answers`, `recording-2`, `post-answers`: must refetch status and apply.

**Recording contract**

- Upload flow: `recording-upload-url` → Supabase Storage upload → POST `recording-1/2` with **JSON** body (not FormData with audio blob).
- Enforce/show backend error for recording_2 duration **60–300 s**.

**Step 4 questions**

- If step = 4 and questions empty: GET `.../questions`.

---

## 2) BFF routes: when you need them

You need the **BFF routes** if the frontend calls **same-origin** `/api/homework/...` (as per taskmaster).

**Why use BFF**

1. Frontend is written to call `/api/...`; without BFF routes the flow can’t progress past status/start.
2. Auth: BFF attaches `Authorization: Bearer <token>` server-side.
3. Avoid CORS and backend URL exposure: browser talks only to Next.js.
4. Mock mode (e.g. `MOCK_HOMEWORK_BACKEND=1`) works at BFF.

**Routes needed for full homework flow**

- `session/start` (POST)
- `session/status` (GET)
- `session/[sessionId]/recording-upload-url` (POST)
- `session/[sessionId]/recording-1` (POST)
- `session/[sessionId]/recording-2` (POST)
- `session/[sessionId]/metric-answers` (POST)
- `session/[sessionId]/questions` (GET)
- `session/[sessionId]/post-answers` (POST)
- `session/[sessionId]/task-block` (GET, optional)
- `session/[sessionId]/warm-up-task` (GET, optional)

**No BFF for wheel:** Wheel = client-side only (AnalyserNode). Backend does **not** expose `recording-metrics-chunk` (glow removed).

**If you call backend directly instead:** Point `homework-client.ts` at `NEXT_PUBLIC_API_URL/v2/...`, send token from client, and set backend CORS.

---

## 3) Remove glow fully (frontend + BFF)

Backend taskmaster: **wheel only; no glow.**

### In the frontend repo

**Delete**

- `src/hooks/useChunkMetrics.ts`
- `src/components/recording/AmbientGlowCircle.tsx`

**In AudioRecorder (or recorder component)**

- No PCM chunk pipeline.
- No calls to any `recording-metrics-chunk` client function.
- Remove any UI driven by `pause_score` / `pause_detected`.

**In homework-client**

- Remove any function that calls `/api/homework/session/:id/recording-metrics-chunk`.
- Remove exported types for `pause_score`, etc.

**Delete BFF route (if present)**

- `src/app/api/homework/session/[sessionId]/recording-metrics-chunk/**` — backend no longer has this endpoint.

**Sanity check**

```bash
rg -n "ChunkMetrics|recording-metrics-chunk|pause_score|pause_detected|AmbientGlowCircle|glow" src
```

(Should find nothing.)

**Result**

- Recorder shows **wheel** (strength/pace) via `useRealtimeStrengthPace`.
- During recording, only: `recording-upload-url`, Supabase Storage upload, POST `recording-1/2`.

---

## 4) Prompt to run in the frontend repo

Copy-paste this into Cursor (or your AI) **in the frontend project** to run the audit and get a concrete punch-list and glow-removal confirmation:

```
Audit our homework flow against the backend taskmaster and fix any violations.

Use the backend repo's taskmaster as the source of truth. If you have access to it, read:
- .taskmaster/docs/APP_DESCRIPTION.md (or docs/taskmaster/APP_DESCRIPTION.md)
- .taskmaster/docs/AUDIT-AND-BFF-GLOW.md

If not, apply these rules:

**Status → step**
- Derive step only from GET /api/homework/session/status → session.status (warm_up→1, task_block→2, final_task_ready→3, post_questions→4, completed→5).
- On every successful status fetch, overwrite step and all step-derived state. No "preserve previous step" logic.

**Session identity + lifecycle**
- sessionId = res.session_id ?? res.session?.id.
- When has_active_session is false (or session is null), clear session state and do not call any session-scoped endpoints until after POST start returns a session id.
- Do not treat completed sessions as active.

**Field mapping (backend sends snake_case)**
- Warm-up text: res.warm_up_task?.text ?? res.session?.warm_up_task_text ?? "".
- Step 2 questions: build from session.session_metric_question_1, session_metric_question_2, session_metric_question_3 (not from a task_block object).
- Final task: session.final_task_text.
- Report: session.context_long (fallback e.g. "Report pending.").
- Score: session.performance_score_end.

**Mutations + refetch**
- After recording-1, metric-answers, recording-2, and post-answers: refetch GET session/status and apply the response to state.

**Recording**
- Flow: call recording-upload-url → upload to Supabase Storage → POST recording-1 or recording-2 with a JSON body (storage_path, duration_seconds), not FormData with the audio blob.
- Recording_2 must be 60–300 seconds; show or handle backend error if duration is out of range.

**Step 4**
- When step is 4 and questions are empty, GET /api/homework/session/[sessionId]/questions.

**Glow removal (wheel only, no glow)**
- Delete useChunkMetrics (or equivalent) and AmbientGlowCircle (or any glow component).
- In the recorder: no PCM chunk pipeline, no calls to recording-metrics-chunk, no UI driven by pause_score/pause_detected.
- In homework-client: remove any function that calls recording-metrics-chunk and types for pause_score etc.
- Delete the BFF route: src/app/api/homework/session/[sessionId]/recording-metrics-chunk.
- Wheel stays client-side only (e.g. useRealtimeStrengthPace for strength/pace). During recording, only call recording-upload-url, then Storage upload, then POST recording-1/2.

Please:
1. List every violation you find (file + line or snippet).
2. Propose concrete code changes (diffs or snippets) to fix them.
3. Confirm glow is fully removed (no ChunkMetrics, recording-metrics-chunk, pause_score, AmbientGlowCircle, or glow UI).
```
