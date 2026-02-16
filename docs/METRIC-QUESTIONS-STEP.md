# Metric questions step (Step 2) – why it can get stuck

This doc explains why the homework flow can stop at the "Answer these questions" (metric questions) step and how to fix it.

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
| No way to leave step | — | Add "Abandon session" button that calls abandon API and then goes to step 0. |

Reference component with Abandon and error display: `docs/frontend-v2-deliverables/components/AnswerMetricQuestionsScreen.tsx`.
