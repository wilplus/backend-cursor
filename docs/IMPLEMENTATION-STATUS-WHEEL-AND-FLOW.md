# Implementation status: wheel and flow

## 1. Done

| Item | Where | Status |
|------|--------|--------|
| **Storage RLS** (403 on Send) | Supabase | You confirmed done: policies for `audio_recordings` (insert, update, select) so uploads succeed. |
| **Backend recording-upload-url** | Flask | Implemented: returns 200 with `storage_path` + `bucket` when session is in correct status; returns **409** with `INVALID_SESSION_STATE` when status is wrong (e.g. recording "1" but session not `warm_up`). |
| **Backend recording-metrics-chunk** | Flask | Implemented: accepts raw PCM, returns metrics; rate limit 120/min; returns 404/409/400/429 when session missing or wrong state or body invalid. |
| **Backend GET session/status** | Flask | Implemented: returns active session with `session_id`, `status`, `warm_up_task`, etc. Frontend can derive step from `status`. |
| **BFF reference route (chunk)** | This repo | Implemented: `docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts` — pure proxy, Next 15 params handling, X-Chunk-Seq / X-Chunk-Start-Ms → X-Seq / X-T-Ms. Copy into frontend repo. |
| **Docs** | This repo | Implemented: SUPABASE-STORAGE-RLS-AUDIO-RECORDINGS.md, ROOT-CAUSE-SESSION-STATUS-MISMATCH.md, PROMPT-FIX-SESSION-NOT-FOUND-RECORDING.md, FIX-WHEEL-AND-FLOW-SUMMARY.md, TRACEBACK-WHEEL-STOPPED-AFTER-BFF-CHANGE.md. |

---

## 2. Cannot execute here (frontend only)

| Item | What it is | Why you see 409 |
|------|------------|------------------|
| **Flow: step from status** | On load, call GET session/status; set current step from `session.status` (warm_up→1, task_block→2, final_task_ready→3, post_questions→4, completed→5). After recording-1, metric-answers, recording-2 succeed, call GET session/status again and apply to state so the UI advances. | This is **frontend** code (e.g. in HomeworkFlowCard or homework client). This repo is the **backend**; we cannot run or edit the frontend app. |
| **409 on recording-upload-url** | Your URL: `https://app.willonski.com/api/homework/session/9cf95976-c4a3-496d-bbe8-987113d966c4/recording-upload-url` returns **409**. The backend is **correct**: it returns 409 when you request an upload URL for recording "1" but the session is **not** in `warm_up`, or for recording "2" but the session is **not** in `final_task_ready`. So the "wrong" part is not the backend — it's that the **frontend** is calling recording-upload-url (for step 1) while the session in the DB is already in a later status. | Fix: **frontend** must derive the current step from GET session/status. If status is e.g. `final_task_ready`, show step 3 (Final task) and do **not** call recording-upload-url with `recording: "1"`. Once the step is driven by status, the frontend will only call recording-upload-url when the backend will return 200. |

So we **cannot implement** the fix for 409 in this repo. The backend already behaves correctly. The implementation is in the **frontend repo**: use status as the single source of truth for the step and only call recording-upload-url when the current step matches (step 1 → recording "1" and status must be warm_up; step 3 → recording "2" and status must be final_task_ready).

---

## 3. To be implemented (where)

| # | What | Where |
|---|------|--------|
| 1 | **applyStatusToState(statusRes)** — one function that sets sessionId, runs deriveStepFromStatus, updates step + warmUpText + taskBlock + finalTaskText + questions + reportText + performanceScoreEnd. | Frontend (e.g. HomeworkFlowCard.tsx) |
| 2 | **On load / resume** — when user enters homework, call GET session/status; if there’s an active session, call applyStatusToState(response). No other source for the initial step. | Frontend |
| 3 | **After recording-1 success** — call GET session/status, then applyStatusToState(response). Do not set step or taskBlock from the recording-1 response. | Frontend |
| 4 | **After metric-answers success** — call GET session/status, then applyStatusToState(response). Do not set step or finalTaskText from the metric-answers response. | Frontend |
| 5 | **After recording-2 success** — call GET session/status, then applyStatusToState(response). Do not set step or questions from the recording-2 response. Optionally if step 4 and questions empty, call GET questions and set questions only. | Frontend |
| 6 | **BFF recording-metrics-chunk** — In the **frontend/BFF repo**, ensure the live route matches the reference (or copy from `docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts`): Next 15 params resolved, sessionId validated, headers X-Seq/X-T-Ms (or X-Chunk-Seq/X-Chunk-Start-Ms mapped). | BFF (frontend repo) |
| 7 | **Wheel** — Ensure PCM pipeline runs when the wheel step is visible; update wheel state from recording-metrics-chunk response (200). If chunk requests are 404, fix BFF sessionId (see #6). | Frontend |

---

## 4. What is wrong (summary)

| Symptom | What’s wrong | Fix (where) |
|---------|--------------|-------------|
| **409 on recording-upload-url** | Frontend is on “step 1” and calls recording-upload-url for recording "1", but the session in the DB is **not** in `warm_up` (e.g. already `final_task_ready`). Backend correctly rejects. | Frontend: derive step from GET session/status; only call recording-upload-url when step and status match. |
| **Wheel not updating** | Chunk requests not sent, or 401/404/400, or 200 but frontend doesn’t update wheel state. | BFF: correct chunk route (params, headers). Frontend: pipeline lifecycle + update wheel from chunk response. |
| **Next step only after refresh** | After recording-1 / metric-answers / recording-2, frontend doesn’t refetch status and apply it. | Frontend: after each of those three successes, call GET session/status and applyStatusToState. |

---

## 5. Backend: no change needed for 409

The backend **must** return 409 when:

- Body is `{ "recording": "1" }` and session status is not `warm_up`, or  
- Body is `{ "recording": "2" }` and session status is not `final_task_ready`.

So we do **not** change the backend to “fix” the 409. The fix is the frontend using session status as the source of truth so it never calls recording-upload-url in a state where the backend will return 409.

## 6. Status must win over heuristics

If you have code that sets the step from legacy heuristics (e.g. `recording_1_id` / `recording_2_id` present) **before** you process `session.status`, it can override the correct step. **Ensure `session.status` wins:** derive step from status first; use heuristics only when status is missing or unknown. Do not let heuristics override the step when status is present.
