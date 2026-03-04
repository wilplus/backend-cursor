# Manual testing: Post-recording questions (“next step”) flow

Use this checklist to verify the backend and frontend for the **post-recording questions** step that appears after the warm-up recording and before the report.

---

## Prerequisites

- [ ] Backend running (e.g. `python app.py`) with valid `.env` (Supabase, OpenAI, etc.).
- [ ] Frontend running and pointing at the backend (or use BFF that proxies to `/v2/homework/*`).
- [ ] A test user with a Supabase JWT (e.g. sign in in the app and use the access token).
- [ ] At least one **warm-up task** assigned to the test user (Admin → Student → warm-up tasks). Otherwise session start may 422.
- [ ] (Optional) **Post-recording questions** assigned to the test user (Admin → Student → Post-recording questions). If none, you should still see the “next step” with “No questions” and a “Continue to report” action.

---

## 1. Session start and status

| # | Action | Expected |
|---|--------|----------|
| 1.1 | `POST /v2/homework/session/start` with `Authorization: Bearer <token>`, body `{}` | 200, `session_id`, `status: "warm_up"` (or equivalent), optional `warm_up_task`. |
| 1.2 | `GET /v2/homework/session/status` with same token | 200, `has_active_session: true`, `session` with same `session_id`, `status` (e.g. `recording_1_required` or `warm_up`). |

---

## 2. Upload recording (recording-1)

| # | Action | Expected |
|---|--------|----------|
| 2.1 | Upload a short audio (e.g. WebM) via `POST /v2/homework/session/<session_id>/recording-1` (multipart `audio` or JSON with `storage_path` + `duration_seconds`). | 200, `recording_id`, `status: "report_generating"` (or similar), `recording_1_processing: true`. |
| 2.2 | Immediately call `GET /v2/homework/session/status`. | 200, same session, status still “in progress” (e.g. `report_generating` / `completing_from_recording_1`). Session remains “active”. |
| 2.3 | Poll `GET /v2/homework/session/status` every few seconds. | After the recording-1 job finishes, status becomes `post_questions`. |

---

## 3. Post-recording questions (GET questions)

| # | Action | Expected |
|---|--------|----------|
| 3.1 | With session in `post_questions`, call `GET /v2/homework/session/<session_id>/questions` with same token. | 200, `questions: [ ... ]` (array of `{ id, text, answer_type, code? }`). If the user has no questions assigned: `questions: []`. |
| 3.2 | Call `GET .../questions` when session is still `completing_from_recording_1` (before job sets `post_questions`). | 200 with questions list, or 409 if your backend only allows `post_questions` (current implementation allows both). |
| 3.3 | Call `GET .../questions` with wrong `session_id` or another user’s session. | 404. |
| 3.4 | Call `GET .../questions` when session is `warm_up` or `completed`. | 409 `INVALID_SESSION_STATE`. |

---

## 4. Submit post-answers and completion

| # | Action | Expected |
|---|--------|----------|
| 4.1 | With session in `post_questions`, call `POST /v2/homework/session/<session_id>/post-answers` with body `{ "answers": [ { "question_id": "<id>", "answer_text": "My answer" } ] }` (use real question `id` from GET questions). | 200, `status: "completed"`, `report_text`, `performance_score_end`, `completed_at_iso`. |
| 4.2 | Same as 4.1 but body `{ "answers": [] }` (no questions or user skipped). | 200, same shape; session completes and report is generated. |
| 4.3 | Call `POST .../post-answers` when session is still `completing_from_recording_1` (before job sets `post_questions`). | 409 `INVALID_SESSION_STATE`. |
| 4.4 | After a successful post-answers, call `GET /v2/homework/session/status`. | 200, `has_active_session: false` (or no session / step 0). |
| 4.5 | After completion, call `GET /v2/homework/session/<session_id>/report`. | 200, full report payload (report_text, scores, recording, etc.). |

---

## 5. End-to-end flow (happy path)

| # | Step | Check |
|---|------|--------|
| 5.1 | Start session. | Session created, status warm_up / recording_1_required. |
| 5.2 | Upload recording-1. | 200, report_generating. |
| 5.3 | Poll status until `post_questions`. | Status changes to post_questions after job runs. |
| 5.4 | GET questions. | 200, list of questions (or empty). |
| 5.5 | POST post-answers (with or without answers). | 200, completed, report_text in response. |
| 5.6 | GET report. | 200, same report content; playback/transcript available. |
| 5.7 | GET status again. | No active session; step 0 payload (e.g. tutor_feedback_deadline if applicable). |

---

## 6. Edge cases and errors

| # | Scenario | Expected |
|---|----------|----------|
| 6.1 | POST post-answers twice for the same session (second time session already completed). | First: 200. Second: 409 or 404 (session no longer in post_questions). |
| 6.2 | GET report before POST post-answers (session still post_questions). | 409 REPORT_NOT_READY. |
| 6.3 | POST post-answers with invalid body (e.g. missing `answers` key). | 200 with `answers` treated as [] (backend normalizes to empty list). |
| 6.4 | Abandon session while in `post_questions` (if your app has abandon). | Session deleted; GET status returns no active session. |

---

## 7. Admin / data checks (optional)

| # | Check | Where |
|---|--------|--------|
| 7.1 | Session row has `status = 'completed'` and `post_answers` populated after POST post-answers. | Supabase `v2_sessions` for that session. |
| 7.2 | Report and recording are linked to the session; admin can open the same report. | Admin panel: student → session → report. |
| 7.3 | Coach email sent after completion (if configured). | Inbox or logs. |

---

## 8. Frontend-specific (if applicable)

| # | Check | Notes |
|---|--------|--------|
| 8.1 | After recording upload, UI shows “Preparing…” or similar until status is `post_questions`. | Polling GET status. |
| 8.2 | When status is `post_questions`, UI shows “Reflective questions” (or “A few questions”) and the list from GET questions. | No “Step 4” label. |
| 8.3 | If GET questions returns `[]`, UI shows “No questions this time” and a single “Continue to report” button. | Button calls POST post-answers with `answers: []`. |
| 8.4 | On submit, UI sends answers in shape `{ answers: [ { question_id, answer_text } ] }` and then navigates to report (step 5). | Uses response or GET report. |
| 8.5 | Progress / steps show: Record → Questions (or Reflect) → Report (no “Step 4” in copy). | Optional 3-step progress. |

---

## Quick reference: API endpoints

- `POST /v2/homework/session/start` — create session.
- `GET /v2/homework/session/status` — active session + status (includes `post_questions` and `completing_from_recording_1`).
- `POST /v2/homework/session/<id>/recording-1` — upload warm-up recording (then status → completing_from_recording_1 → job → post_questions).
- `GET /v2/homework/session/<id>/questions` — list post-recording questions (when status is post_questions or completing_from_recording_1).
- `POST /v2/homework/session/<id>/post-answers` — submit answers (or []) and complete session; returns report payload.
- `GET /v2/homework/session/<id>/report` — get full report (only when status is completed).

All require `Authorization: Bearer <supabase_access_token>`.
