# Backend–frontend fit: student homework flow

Does the frontend structure (steps 0–5, variables, source of truth) fit the backend? Yes, with the mappings below. The only “thin” parts are **task_block** and **questions**: the backend does not return them as shaped objects in GET session/status, so the frontend correctly uses step-specific GETs when needed.

---

## 1. Step and source of truth

| Frontend | Backend | Fit |
|----------|---------|-----|
| Step 0 = no session / loading | GET session/status → `has_active_session: false` or `session: null` | Yes. |
| Step 1–5 from `session.status` only | Status enum: `warm_up`, `task_block`, `final_task_ready`, `post_questions`, `completed` | Yes. Map to step 1–5; nothing else overrides when status is present. |
| Step 0 → POST session/start when no session | Backend returns 200 with session_id + warm_up_task when active exists, or 201 with new session. | Yes. |

---

## 2. GET session/status response → frontend variables

Backend returns:

- **session**: full `v2_sessions` row (all columns).
- **session_id**: `active["id"]` (same as `session.id`).
- **has_active_session**: true.
- **warm_up_task**: `{ id, text }` (from DB or session snapshot).

So the **session** object contains (among others): `id`, `user_id`, `status`, `warm_up_task_id`, `warm_up_task_text`, `session_metric_question_1`, `session_metric_question_2`, `session_metric_question_3`, `recording_1_id`, `context_short`, `performance_score_1`, `selected_task_id`, `metric_answers`, `final_task_text`, `recording_2_id`, `performance_score_2`, `post_question_ids`, `context_long`, `context_long_entries`, `performance_score_end`.

| Frontend variable | Backend source | Note |
|-------------------|----------------|------|
| **step** | `deriveStepFromStatus(statusRes).step` from **session.status** | 1=warm_up, 2=task_block, 3=final_task_ready, 4=post_questions, 5=completed. |
| **sessionId** | **session_id** or **session.id** | Same value. |
| **warmUpText** | **warm_up_task.text** or **session.warm_up_task_text** | Backend sends warm_up_task at top level; session also has snapshot. |
| **taskText** | **session.context_short** (if needed) | Short summary of recording 1. Step 2 “task” content is mainly taskBlock (3 questions). |
| **taskBlock** | Not in status as a shaped object. Session has **session.session_metric_question_1/2/3** (text only). | **Thin:** use **GET task-block** when step === 2 and taskBlock empty. Backend GET task-block returns `{ task_block: { metric_question_1, metric_question_2, metric_question_3 } }`. |
| **finalTaskText** | **session.final_task_text** | Present on session once status is task_block or later. |
| **questions** | Session has **session.post_question_ids** (ids only). Question list (id, text, answer_type) is not in status. | **Thin:** use **GET questions** when step === 4 and questions empty. |
| **reportText** | **session.context_long** | Report body. |
| **performanceScoreEnd** | **session.performance_score_end** | Present when status is completed. |

So: **session_id**, **status**, **warm_up_task**, **final_task_text**, **context_long**, **performance_score_end** are all in the status response (session object or top-level). **task_block** and **questions** are thin: frontend’s “when step 2 and missing → GET task-block; when step 4 and empty → GET questions” matches the backend.

---

## 3. API calls per step (backend contract)

| Step | Frontend calls | Backend expects |
|------|----------------|-----------------|
| 0 | GET session/status; if no session, POST session/start | Status returns session or null; start creates session (status=warm_up). |
| 1 | recording-upload-url (recording "1"), upload blob, POST recording-1 | Session must be warm_up for recording "1" and recording-1. |
| 2 | GET task-block (if thin), POST metric-answers | Session must be task_block. |
| 3 | recording-upload-url (recording "2"), upload blob, POST recording-2 | Session must be final_task_ready for recording "2" and recording-2. |
| 4 | GET questions (if thin), POST post-answers | Session must be post_questions. |
| 5 | (none) | Session is completed; report already from post-answers. |

All of that matches the backend.

---

## 4. Summary

- **Step and “where the user is”:** Single source of truth is GET session/status → **session.status**. Frontend’s rule (status wins; no override by URL or recording_1_id/recording_2_id) fits the backend.
- **Session id:** Use **session_id** or **session.id** from status response for all session-scoped APIs. Fits.
- **Content:** Most content (warmUpText, finalTaskText, reportText, performanceScoreEnd) is on the **session** object. **task_block** and **questions** are thin: frontend uses GET task-block and GET questions when step 2/4 and missing. Fits.
- **After mutations:** Frontend calls GET session/status and applyStatusToState after recording-1, metric-answers, recording-2. Backend updates status and session fields on those endpoints, so refetch gives the new step and content. Fits.

No backend change needed for this frontend structure. The only nuance is naming: backend uses **context_long** for the report text and **final_task_text** for the final task; frontend uses **reportText** and **finalTaskText** — mapping is straightforward.

---

## 5. Compatibility / incompatibility list

### Compatible (they fit)

1. **Step model / state machine** — Backend `v2_sessions.status` drives the flow; frontend derives step from `session.status` and does not derive from recording IDs when status exists. Aligned.
2. **Session identity** — Backend provides `session_id` (top-level) and `session.id`; frontend uses `statusRes.session_id ?? statusRes.session?.id`. Good.
3. **Storage upload-by-path** — Backend bucket `audio_recordings`, path `{user_id}/{session_id}/{uuid}.webm`, returns `storage_path`; frontend uploads to that path then calls recording-1/2 with `{ storage_path, duration_seconds }`. Matches (subject to Storage RLS).
4. **Task block / final task are backend-owned** — Backend sets context and task after recording-1; generates `final_task_text` after metric-answers. Frontend only displays. Compatible.

### Incompatible / risky assumptions (can break)

**A) Thin vs full status** — If backend ever returns **thin** status (only `session` + maybe `warm_up_task`), the frontend must do follow-up GETs (task-block for step 2, questions for step 4). If the frontend assumes task_block / final_task_text / questions / report are always present in status, you get blank screens. **Action:** Treat `session.status` as authoritative for step; treat other content as “may require fetch” and implement the follow-up GETs.

**B) Key name mismatches** — Backend uses **snake_case** and specific names. Frontend must not assume:
- `final_task` (object) — backend has **`session.final_task_text`** (string).
- `report_text` or `report` at top level — backend has **`session.context_long`**.
- Top-level **`task_block`** — backend has **`session.session_metric_question_1/2/3`** or GET task-block.
- **Action:** Standardize all mapping in one place (e.g. `applyStatusToState()`) and never read these keys ad-hoc in components. Support both `warm_up_task.text` and `session.warm_up_task_text`.

**C) “Active session” vs stale sessionId** — Backend can return `{ "has_active_session": false, "session": null }` while the UI still has a stale `sessionId`. Then session-scoped calls get SESSION_NOT_FOUND or INVALID_SESSION_STATE. **Action:** When `has_active_session` is false, clear sessionId and step; require POST session/start before any recording or metrics calls.

**D) Chunk pipeline endpoint** — Production chunk pipeline must call **same-origin** `/api/homework/session/:id/recording-metrics-chunk` (BFF), not a different host (e.g. `127.0.0.1:7242/ingest/...`). **Action:** Ensure the wheel/chunk pipeline only uses the BFF recording-metrics-chunk route.

**E) Bucket name** — Backend uses bucket **`audio_recordings`**. If frontend or mocks use **`recordings`**, RLS/policy will target the wrong bucket. **Action:** Always use the **`bucket`** value returned by recording-upload-url.

### Summary

- **Conceptually compatible:** yes (same state machine, storage_path, status-driven step).
- **Contract-level compatible:** only after exact response keys and thin/full behavior are standardized and verified. Use the contract verification checklist below once.

---

## 6. Contract verification checklist (do once)

Capture real JSON responses for:

| # | Request | Purpose |
|---|---------|--------|
| 1 | **GET** `/api/homework/session/status` | Once in each status: warm_up, task_block, final_task_ready, post_questions, completed. Confirm keys: session, session_id, has_active_session, warm_up_task; session.status, session.final_task_text, session.context_long, session.performance_score_end. |
| 2 | **POST** `/api/homework/session/start` | Confirm session_id, status, warm_up_task. |
| 3 | **POST** `/api/homework/session/:id/recording-1` | Confirm recording_id, performance_score_1, task_block shape. |
| 4 | **POST** `/api/homework/session/:id/metric-answers` | Confirm final_task. |
| 5 | **GET** `/api/homework/session/:id/task-block` | Confirm task_block: { metric_question_1, metric_question_2, metric_question_3 }. |
| 6 | **GET** `/api/homework/session/:id/questions` | Confirm questions array shape. |

Use these to lock types and `applyStatusToState` / `deriveStepFromStatus` so key names and thin vs full behavior are consistent. Example status payloads: **`docs/EXAMPLE-GET-SESSION-STATUS-RESPONSES.md`**.
