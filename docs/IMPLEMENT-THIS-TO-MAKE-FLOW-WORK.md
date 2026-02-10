# Implement this to make the flow work in real life

Checklist of what to implement in the **frontend** and **BFF** so the 409 goes away, the wheel works, and the step advances without refresh. Backend and Supabase (Storage RLS) are already in place.

---

## 1. Frontend: status as single source of truth for step

**Goal:** Step and “current session” come only from GET session/status. No 409 from calling recording-upload-url when the session is already past warm_up.

| # | What to implement | Where |
|---|-------------------|--------|
| 1.1 | **applyStatusToState(statusRes)** — One function that maps status → state. **Do not** read `task_block`, `final_task`, or `report_text`; backend does not send those. Use the **minimal mapping** in **`docs/EXAMPLE-GET-SESSION-STATUS-RESPONSES.md` §4** (Contract realities): `sessionId` from `res.session_id ?? res.session?.id`; `status` from `res.session?.status`; `warmUpText` from `res.warm_up_task?.text ?? res.session?.warm_up_task_text`; step 2 questions from `res.session?.session_metric_question_1/2/3` (or GET task-block when step 2 and taskBlock empty); `finalTaskText` from `res.session?.final_task_text`; `reportText` from `res.session?.context_long`; `performanceScoreEnd` from `res.session?.performance_score_end`. All backend keys are **snake_case**. | e.g. HomeworkFlowCard.tsx |
| 1.2 | **deriveStepFromStatus** — Step **only** from `session.status`: warm_up→1, task_block→2, final_task_ready→3, post_questions→4, completed→5. When status is present, **do not** derive step from recording_1_id / recording_2_id or URL. Use heuristics only when status is missing or unknown. | Same file or shared util |
| 1.3 | **On load / resume** — When user enters homework: call GET session/status. If `has_active_session` is true and session is non-null, call `applyStatusToState(response)`. If `has_active_session` is false (or session null), **clear** sessionId and step; show “Start homework” and do not call recording-upload-url or recording-metrics-chunk until after POST session/start. | HomeworkFlowCard (e.g. useEffect on mount) |
| 1.4 | **Only call recording-upload-url when step matches** — Call recording-upload-url with `recording: "1"` only when current step is 1 (status warm_up). Call with `recording: "2"` only when current step is 3 (status final_task_ready). Never call it for recording "1" when you’re on step 3. | Same (guard before calling getRecordingUploadUrl) |

**Status-first and overwrite (avoids stale-step bugs):**

- On every successful **GET session/status**, **overwrite** the UI step from `session.status` — do not preserve a previous step. Status is the single source of truth.
- If **`has_active_session: false`**, **clear** `sessionId` and `session` (and step); do not call any session-scoped endpoints until **POST session/start** returns a new session id.

**Handoff:** If you paste your current `applyStatusToState()` (or equivalent status → state mapping), the exact lines to change can be pointed out using **EXAMPLE-GET-SESSION-STATUS-RESPONSES.md §4** and the minimal mapping there.

---

## 2. Frontend: refetch status after step-advancing mutations

**Goal:** UI advances to the next step without refresh.

| # | What to implement | Where |
|---|-------------------|--------|
| 2.1 | **After recording-1 success** — Call GET session/status, then `applyStatusToState(response)`. Do **not** set step or taskBlock from the recording-1 response. | In handleRecording1Complete (or equivalent) |
| 2.2 | **After metric-answers success** — Call GET session/status, then `applyStatusToState(response)`. Do **not** set step or finalTaskText from the metric-answers response. | In handleMetricAnswersSubmit |
| 2.3 | **After recording-2 success** — Call GET session/status, then `applyStatusToState(response)`. Do **not** set step or questions from the recording-2 response. If after apply you’re on step 4 and questions are empty, then call GET questions and set questions only. | In handleRecording2Complete |

---

## 3. Frontend: thin status — fill step content when missing

**Goal:** No blank screens when status doesn’t include task_block or questions. Only call follow-up GETs when content is actually missing; avoid depending on endpoints that don’t exist in your backend/BFF.

**Thin vs full status — when to do follow-up GETs:**

| Step | Status | What status has | Action |
|------|--------|-----------------|--------|
| **2** | `task_block` | Often **`session_metric_question_1/2/3`** (three strings). | If the backend does **not** expose GET task-block, do not call it — use only status fields to build task block. If GET task-block **does** exist, you can call it when step === 2 and task block is still missing. |
| **4** | `post_questions` | Only **`post_question_ids`** (IDs). No question list in status. | **GET questions** is required to show the list. Call when step 4 and questions state is empty. |
| **5** | `completed` | **`session.context_long`** (report text) when ready. | If `context_long` is present → use it for reportText. If absent (e.g. still generating) → show “Report pending”. **Do not** assume a separate GET report endpoint exists; this backend does not expose one for the student flow (report comes from status or from POST post-answers response). |

**Caveat:** If the backend does not expose GET task-block, do not call it — use only status fields. If it does exist, you can call it when step === 2 and task block is still missing.

| # | What to implement | Where |
|---|-------------------|--------|
| 3.1 | **Step 2 and no taskBlock** — If backend does **not** expose GET task-block, use only `session_metric_question_1/2/3` from status to build a minimal taskBlock (IDs null/synthetic). If GET task-block **does** exist, call it when step === 2 and task block is still missing, and set taskBlock from the response. | e.g. useEffect that runs when step === 2 && !taskBlock |
| 3.2 | **Step 4 and no questions** — When step === 4 and questions are empty, call GET questions (with current sessionId) and set questions from the response. | e.g. useEffect when step === 4 && questions.length === 0 |

---

## 4. BFF: recording-metrics-chunk route

**Goal:** Chunk requests reach the backend with valid sessionId and headers so the wheel can get 200 and update.

| # | What to implement | Where |
|---|-------------------|--------|
| 4.1 | **Correct route** — Ensure the BFF has a route for POST `.../recording-metrics-chunk` that proxies to Flask `POST /v2/homework/session/:id/recording-metrics-chunk` with body (arrayBuffer) and auth. No Supabase insert in this route. | BFF: e.g. `src/app/api/homework/session/[sessionId]/recording-metrics-chunk/route.ts` |
| 4.2 | **Next 15 params** — If using Next 15, `params` is a Promise. Use `const { sessionId } = await params;` (or equivalent) before building the URL. Ensure sessionId is defined; if not, return 400. | Same route |
| 4.3 | **Headers** — Forward X-Sample-Rate, X-Seq, X-T-Ms to the backend. If the frontend sends X-Chunk-Seq / X-Chunk-Start-Ms, map them to X-Seq / X-T-Ms. | Same route |
| 4.4 | **Auth** — Send Authorization: Bearer &lt;student_token&gt; (e.g. from getV2AccessToken() or forwarded from request). | Same route |

Reference implementation: **`docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts`** in this repo.

---

## 5. Frontend: wheel (chunk pipeline + UI update)

**Goal:** Wheel moves in real time when the user is on step 1 or 3.

| # | What to implement | Where |
|---|-------------------|--------|
| 5.1 | **Chunk URL** — The pipeline must POST to **same-origin** `/api/homework/session/:sessionId/recording-metrics-chunk` (your BFF), not to another host (e.g. not 127.0.0.1/ingest). | PCM chunk pipeline / homework client |
| 5.2 | **Pipeline lifecycle** — Start sending chunks when the step that shows the wheel is mounted (step 1 or 3). Don’t tear down the pipeline on re-render when only state from applyStatusToState updates; keep it running until the user leaves the step or submits. | Component that shows the wheel |
| 5.3 | **Update wheel from response** — When recording-metrics-chunk returns 200, use the response (e.g. voiced_ratio, pause_score or your wheel fields) to update the wheel component state so the dot/indicator moves. | Same component or hook |

---

## 6. Frontend: bucket and upload

**Goal:** No 403 on upload; correct bucket.

| # | What to implement | Where |
|---|-------------------|--------|
| 6.1 | **Use bucket from API** — Use the **bucket** value returned by recording-upload-url (e.g. `audio_recordings`). Do not hardcode a different bucket (e.g. `recordings`). | Upload code after getRecordingUploadUrl |
| 6.2 | **Storage RLS** — Supabase bucket must allow INSERT for the user (see `docs/SUPABASE-STORAGE-RLS-AUDIO-RECORDINGS.md`). Already done on your side; ensure no other bucket is used. | Supabase Dashboard (already done) |

---

## 7. Order to implement (suggested)

1. **§1 + §2** — Status as source of truth and refetch after mutations. This fixes 409 and “step only advances after refresh”.
2. **§4** — BFF recording-metrics-chunk (params, headers, auth). This fixes 404/401 on chunk requests.
3. **§5** — Wheel pipeline lifecycle and UI update from chunk response. This makes the wheel move.
4. **§3** — Thin-status fill (task-block, questions) so step 2 and 4 are never blank.
5. **§6** — Already done if you use the bucket from the API and have Storage RLS; just verify.

---

## 8. Backend / Supabase (no implementation needed here)

- Backend: GET session/status, recording-upload-url, recording-1/2, task-block, metric-answers, questions, post-answers, recording-metrics-chunk are implemented. No backend changes required.
- Supabase Storage RLS: You added policies for `audio_recordings`. No further backend work.

All implementation is in the **frontend repo** (React state, applyStatusToState, deriveStepFromStatus, pipeline, wheel UI) and **BFF** (recording-metrics-chunk route). Use this checklist and the referenced docs until 409 is gone, the wheel updates, and the step advances without refresh.
