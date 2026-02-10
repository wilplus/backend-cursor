# Root cause: "Session must be in warm_up for recording-1" and similar errors

## What’s going wrong

The **backend** stores one **session status** per homework session and only allows certain API calls when the session is in the right status. The **frontend** is showing a step (e.g. step 1 = Warm-up) that does **not** come from that backend status. So the UI says “you’re on step 1” but the session in the DB is already e.g. **final_task_ready** (step 3). When the user does step-1 actions (get upload URL, submit recording-1), the backend correctly returns **409 INVALID_SESSION_STATE** because the session is not in `warm_up`.

**Root cause:** The current step in the UI is **not** derived from **GET session/status** → `session.status`. It’s coming from something else (default step, local state, URL, or heuristics). So the UI and backend get out of sync.

**Fix (frontend):** On load (and when entering homework), call **GET /v2/homework/session/status** and set the current step from `session.status`:

- `warm_up` → step 1 (Warm-up task + recording-1)
- `task_block` → step 2 (Metric answers)
- `final_task_ready` → step 3 (Final task + recording-2)
- `post_questions` → step 4 (Questions)
- `completed` → step 5 (Report/done)

Use status as the **single source of truth**; only fall back to heuristics when status is missing or unknown. Then the UI won’t call recording-upload-url for recording-1 when the session is already `final_task_ready`, and the 409 goes away.

---

## How `getRecordingUploadUrl` is wired

1. **Frontend** has a `sessionId` (e.g. from URL or from a previous “Start homework” call).
2. User is on the Warm-up step. Frontend calls **getRecordingUploadUrl(sessionId, recording, signal)** where `recording` is `"1"` or `"2"`.
3. That does **POST** `{BFF}/session/{sessionId}/recording-upload-url` with body `{ recording: "1" }` (or `"2"`).
4. **BFF** proxies to **Flask** `POST /v2/homework/session/{id}/recording-upload-url` with the same body and auth.
5. **Flask** loads the session and checks status:
   - For **recording "1"**: requires `status == warm_up`. If not (e.g. `final_task_ready`) → **409** with `"Session must be in warm_up for recording-1"` and `"status": "final_task_ready"`.
   - For **recording "2"**: requires `status == final_task_ready`. If not → **409** with `"Session must be in final_task_ready for recording-2"`.
6. If status is correct, Flask returns 200 with `storage_path` and `bucket`. Frontend then uploads the blob to that path and calls recording-1 or recording-2 with `storage_path` + `duration_seconds`.

So the 409 happens because at step 5 the session status in the DB is not the one required for that `recording` value, while the UI is showing the step that corresponds to that recording. Fix: derive the step from status so the UI never shows “step 1” when status is already `final_task_ready`.

---

## All endpoints that depend on session status (same class of errors)

If the frontend step is not driven by `session.status`, any of these can return **404** or **409** when the user tries to do the “current” step while the backend is in a different state.

| Endpoint | Required status | Wrong status → response |
|----------|------------------|--------------------------|
| **GET** `/session/status` | (any; returns current session + status) | N/A |
| **POST** `/session/start` | (creates or returns active session) | N/A |
| **GET** `/session/:id/warm-up-task` | `warm_up` | 404 "Session not found or not in warm_up" |
| **POST** `/session/:id/recording-upload-url` body `{ recording: "1" }` | `warm_up` | 409 "Session must be in warm_up for recording-1" |
| **POST** `/session/:id/recording-upload-url` body `{ recording: "2" }` | `final_task_ready` | 409 "Session must be in final_task_ready for recording-2" |
| **POST** `/session/:id/recording-1` | `warm_up` | 409 "Session not found or not in warm_up" |
| **GET** `/session/:id/task-block` | `task_block` | 404 "Session not found or not in task_block" |
| **POST** `/session/:id/metric-answers` | `task_block` | 404 "Session not found or not in task_block" |
| **POST** `/session/:id/recording-2` | `final_task_ready` | 404 "Session not found or not in final_task_ready" |
| **GET** `/session/:id/questions` | `post_questions` or `completed` | 404 "Session not found or wrong status" |
| **POST** `/session/:id/post-answers` | `post_questions` (or already `completed` → idempotent 200) | 404 "Session not found or not in post_questions" |

**recording-metrics-chunk** allows any of `warm_up`, `task_block`, `final_task_ready`, `post_questions`; it only rejects if status is something else (e.g. `completed` or missing). So it’s less likely to 409 from a simple “step 1 vs step 3” mismatch, but still depends on session existing and being in an “active” state.

---

## Summary

- **Root problem:** UI step is not the same as backend `session.status`, so the UI triggers calls that the backend rejects (409/404).
- **Wiring:** `getRecordingUploadUrl` → POST recording-upload-url → Flask checks status for recording 1 or 2 → 409 if status doesn’t match.
- **Fix:** Drive the current step from **GET session/status** → `session.status` so the UI never calls recording-upload-url (or recording-1, metric-answers, recording-2, questions, post-answers) when the session is in the wrong status. That avoids this whole class of errors.
