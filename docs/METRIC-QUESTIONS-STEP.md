# Metric questions step (Step 2) – why it can get stuck

This doc explains why the homework flow can stop at the "Answer these questions" (metric questions) step and how to fix it.

## Implementation spec (metric questions screen)

Use this as the spec for the step 2 UI:

**1. Abandon session button (required)**  
On the metric questions screen, add a secondary button, e.g. "Abandon session" or "Start over", that:

- Calls `POST /api/homework/session/${sessionId}/abandon` (with your usual auth).
- On **200** or **404**: clear session state and go back to step 0 (start).
- You can disable it while the main form is submitting.

**2. Continue and errors**

- **Continue** should send `POST /api/homework/session/${sessionId}/metric-answers` with `{ answer_1, answer_2, answer_3 }` for every question that has text in `task_block`. Disable the button while the request is in flight.
- When the API returns **422** or **409**, show `data.message` or `data.error` (e.g. "Please answer all questions before continuing." or "Your recording is still being analyzed. Please wait a moment and try again.") so the user knows why they can't proceed and can fix it or retry.

**3. Optional: "Analyzing…" state**  
If you have `recording_1_processing` from status or the recording-1 response, you can disable Continue and show "Analyzing your recording…" until it's false (e.g. by polling status), so the user doesn't hit 409 by clicking too early.

---

## Frontend checklist (metric questions screen)

To avoid "no abandon button" and "cannot proceed" on step 2, the metric questions screen **must** have:

1. **Abandon session button**  
   A secondary button (e.g. "Abandon session" or "Start over") that:
   - Calls `POST /api/homework/session/{sessionId}/abandon` (with auth).
   - On **200** or **404**: clear session state and go to step 0 (start screen). Treat 404 as "session already gone" and still go to step 0.
   - Optionally disable this button while `submitting` is true so the user doesn’t leave mid-submit.

2. **Continue button**  
   Submits `POST /api/homework/session/{sessionId}/metric-answers` with body `{ answer_1, answer_2, answer_3 }` (only for questions that have text in `task_block`). Disable the button while the request is in flight (`submitting`).

3. **Show all questions from task_block**  
   Render one input per question that has non-empty text: `task_block.metric_question_1`, `metric_question_2`, `metric_question_3`. Send the corresponding `answer_1`, `answer_2`, `answer_3` (required fields; backend returns 422 if a required answer is empty).

4. **Show API errors so the user can proceed or retry**  
   When the API returns **422** or **409**, display `data.message` or `data.error` (e.g. "Please answer all questions before continuing." or "Your recording is still being analyzed. Please wait a moment and try again."). That way the user knows why Continue didn’t advance and can fix it or click "Try again" later.

5. **Optional: wait for recording-1 to finish before allowing Continue**  
   If `GET /v2/homework/session/status` (or the recording-1 response) includes `recording_1_processing: true`, you can disable Continue and show "Analyzing your recording…" and poll status until it’s false, then enable Continue. Otherwise, when the user clicks Continue too early they get 409 and you must show the message above.

Reference implementation: `docs/frontend-v2-deliverables/components/AnswerMetricQuestionsScreen.tsx`.

## Metric questions not displaying

If step 2 shows no questions (or they disappear after refresh):

1. **Backend (fixed):** The backend now saves `session_metric_question_1/2/3` when recording-1 succeeds, so GET status and GET task-block return the question texts. Deploy the latest backend so this is in effect.
2. **Frontend:** On step 2, you need a `task_block` with `metric_question_1.text`, `metric_question_2.text`, `metric_question_3.text`. Use the recording-1 response when you have it; if you only have the session (e.g. after refresh), build task_block from `session.session_metric_question_1/2/3` or call **GET** `/api/homework/session/:id/task-block` and use its `task_block`.
3. **Admin:** Ensure metric questions exist: in admin, **Metrics** / metric questions (positions 1, 2, 3) must have text. If `v2_metric_questions` is empty or has no text, the backend returns empty question texts.

## Why the tool stops and cannot proceed

1. **Backend requires all *configured* answers**  
   The API `POST /v2/homework/session/:id/metric-answers` accepts `answer_1`, `answer_2`, and optionally `answer_3`. The backend requires only the answers for questions that exist in the flow (admin may configure 2 or 3 metric questions). If the frontend sends empty answers for required questions, the backend returns **422** with `code: "VALIDATION_ERROR"` and `message: "Please answer all questions before continuing."`  
   **Fix:** Show all questions from `task_block` (only those with non-empty `text`). Submit answers for every question shown. Surface the backend `message` (or `error`) when the response is not OK so the user knows what to fix.

2. **Recording 1 still processing**  
   The backend will not generate the final task until the recording-1 background job has finished (it sets `performance_score_1` and `context_short`). If the user clicks "Continue" before that, the API returns **409** with `code: "RECORDING_1_PROCESSING"` and `message: "Your recording is still being analyzed. Please wait a moment and try again."`  
   **Fix:** Either (a) disable the "Continue" button and show "Analyzing your recording…" while `recording_1_processing === true`, and poll `GET /v2/homework/session/status` until `recording_1_processing` is false, or (b) when you get 409 RECORDING_1_PROCESSING, show the backend `message` and allow "Try again" after a few seconds.

3. **Repeated "metric Continue clicked" warnings**  
   If the API returns 422 or 409 and the frontend does not show the error, the user stays on the same step and may click "Continue" again. Each click can be logged as a warning. Ensure you:  
   - Show the API error (`data.message` or `data.error`) on 4xx.  
   - Keep the submit button disabled while `submitting` is true and re-enable it only after the request finishes (so double-clicks don’t send multiple requests).

## Abandon session button

The metric questions step must show an **"Abandon session"** (or "Start over") button so the user is not stuck with no way out.

- **Backend:** `POST /v2/homework/session/:id/abandon` — returns 200 when the session is deleted, 404 when it is already gone. The BFF route is in `docs/homework-bff-routes/session/[sessionId]/abandon/route.ts`.
- **Frontend:** On the metric-questions screen (and ideally every step), render a secondary button that calls the abandon API, then on success (or 404) clear state and go to step 0 (start). See `docs/FRONTEND-SESSION-GONE-START-OVER.md` and `docs/FRONTEND-SESSION-NOT-FOUND.md`.

## Recording-upload-url when session is already task_block (409 → 200 with task_block)

If the frontend calls **POST** `/v2/homework/session/:id/recording-upload-url` with `{ "recording": "1" }` after the session has already moved to `task_block` (e.g. recording-1 was submitted earlier, or page refreshed), the backend now returns **200** with:

- `already_past_step: true`
- `status: "task_block"`
- `task_block`: `{ metric_question_1, metric_question_2, metric_question_3 }`

**Frontend:** When you get a 200 from recording-upload-url, check for `data.already_past_step` and `data.task_block`. If present, treat it as "we're already at step 2" and set state to show the metric questions screen using `data.task_block` (do not treat as an error or try to upload again).

## Summary

| Issue | Backend response | Frontend fix |
|-------|------------------|--------------|
| Missing answer(s) | 422 VALIDATION_ERROR, `message` | Show all questions from task_block; display `message` on error. |
| Recording still analyzing | 409 RECORDING_1_PROCESSING, `message` | Disable Continue while processing and/or show `message` and "Try again". |
| Upload URL requested but session already task_block | 200 with `already_past_step`, `task_block` | Use `task_block` and show metric questions (step 2). |
| Recording-1 analysis failed (409 RECORDING_1_FAILED) | **Backend fallback:** metric-answers now succeeds with 200; `recording_1_fallback: true` and `message` explain that a general focus was used. | Show optional notice from `message`; user can continue to recording-2. |
| No way to leave step | — | Add "Abandon session" button that calls abandon API and then goes to step 0. |

Reference component with Abandon and error display: `docs/frontend-v2-deliverables/components/AnswerMetricQuestionsScreen.tsx`.

## Debugging 404 on metric-answers

When **POST** `/v2/homework/session/:id/metric-answers` returns **404** with `code: "SESSION_NOT_FOUND"` even though **GET** `/v2/homework/session/status` just returned an active session, use the following to track down the cause.

### BFF in the path

When the frontend uses the Next.js BFF (reference in `docs/homework-bff-routes/`):

- **GET status:** Browser → `GET /api/homework/session/status` (BFF) → BFF calls backend `GET /v2/homework/session/status` with header `Authorization: Bearer <token>` (no session_id in URL).
- **POST metric-answers:** Browser → `POST /api/homework/session/{sessionId}/metric-answers` (BFF) → BFF calls backend `POST /v2/homework/session/{sessionId}/metric-answers` with headers `Authorization: Bearer <token>` and `Content-Type: application/json`; body is forwarded as JSON. The `sessionId` comes from the Next.js route segment and is interpolated into the backend URL.

So the backend receives only the headers the BFF sends (e.g. Authorization, Content-Type for metric-answers).

### Exact request headers for both calls

To capture **exact** request headers:

- In the browser: DevTools → Network, select the request to **`/api/homework/session/status`** and the request to **`/api/homework/session/.../metric-answers`**, then copy "Request Headers". Those are what the BFF receives; the backend sees the same `Authorization` (and for metric-answers, `Content-Type` and body) as the BFF forwards.
- On the backend: When metric-answers returns 404, the handler logs safe request metadata (header names, `Content-Type`) plus `session_id` and `user_id` (see below). Check backend logs for that entry.

### Logged (session_id, user_id) on 404

When the backend returns 404 from metric-answers (session not found for that `session_id` + `user_id`), it writes a log entry (e.g. via `_agent_log`) with:

- `session_id` (string as received from the URL)
- `session_id_len`, `session_id_repr` (for encoding/whitespace checks)
- `user_id` (from the JWT)
- `header_names`, `content_type` (safe request metadata)

Use this to confirm what the backend received and to compare with the session returned by GET status.

### Confirming session_id strings match exactly

- **Server-side:** GET status logs the `session_id` it returns (string + length) when it serializes the active session. Compare that logged value with the `session_id` logged on the metric-answers 404; they should be identical.
- **Client-side:** The `session_id` used in the POST metric-answers URL must be exactly the same string as `session_id` (or `session.id`) from the last GET status response—no extra/missing characters, same casing.
- **Optional debug response:** In non-production, or when the request includes header `X-Debug-404: true`, the 404 response body includes a `debug` object with `session_id_received` and `user_id_from_token`. Use this to verify from the client what the backend saw without reading server logs.
