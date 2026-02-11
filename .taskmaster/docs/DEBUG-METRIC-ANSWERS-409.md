# Debug summary: 409 after clicking "Confirm" on metric questions (step 2 → 3)

## Context for another LLM

- **App:** Homework flow (warm-up → 3 metric questions → final task recording → post-questions → report). Backend = Flask; frontend/BFF = Next.js (separate repo). Taskmaster = `.taskmaster/docs/APP_DESCRIPTION.md`.
- **User report:** After fixing the step-1 409 (recording-upload-url "1" called twice), the user could advance to step 2 (metric questions). They answer the 3 questions and click **"Confirm"**. Then **it stops working and 409 recurs**.
- **User hypotheses:** Final task generation (OpenAI) failed; context_short or score_1 / focus_task not in place; API failed to write the task. They also noted that previously they could sometimes reach the next step but with a "generic" task, so they suspect the blocker might be **similar to step 1** (e.g. double request, or frontend calling the wrong endpoint / not advancing after success).
- **Question:** Is the failure in the **backend** (metric-answers handler or OpenAI/DB) or in the **frontend** (e.g. calling recording-upload-url for "2" too early, or not refetching status after metric-answers)?

## Backend flow (metric-answers)

1. **POST /v2/homework/session/:id/metric-answers** (body: answer_1, answer_2, answer_3 or aliases).
2. Load session; if status ≠ `task_block` → **409** (or 200 idempotency if already `final_task_ready` with final_task_text).
3. Validate all three answers present; else 422.
4. Read `context_short`, `selected_task_id` from session; resolve focus_task (from score_1 at recording-1 time).
5. **OpenAI:** `generate_final_task(context_short, focus_title, focus_prompt, metric_answer_1, answer_2, answer_3)` → `final_task_text`.
6. **DB:** `v2_update_session(..., { metric_answers, status: "final_task_ready", final_task_text })`.
7. Return **200** `{ "final_task": final_task_text }`.

If the user then goes to "step 3" (final task recording), the frontend must call **recording-upload-url** with `{ "recording": "2" }` only when **session.status === "final_task_ready"**. If the frontend calls recording-upload-url "2" **before** metric-answers has returned 200 and/or before the client has refetched status, the backend will return **409** for recording-upload-url ("Session must be in final_task_ready for recording-2").

So **409 could come from two places:**
- **metric-answers** → 409 "Session must be in task_block for metric-answers" (e.g. double submit and status already final_task_ready).
- **recording-upload-url** (with "2") → 409 "Session must be in final_task_ready for recording-2" (session still task_block because metric-answers wasn’t called, failed, or client didn’t wait for it).

## Instrumentation added (backend)

- **metric-answers:** Logs with `hypothesisId` H1–H5 and H_upload.
  - **H1:** Entry (session_id, status, has_answer_1/2/3); 404 when session not found; 409 when status ≠ task_block (and not idempotency).
  - **H2:** Idempotency path (already final_task_ready, return 200 with existing final_task).
  - **H3:** After `generate_final_task` (final_task length, has_context_short).
  - **H4:** After `v2_update_session` (update_result_is_none).
  - **H5:** Success 200; or exception (error, type).
- **recording-upload-url:** When returning 409 for rec "1" or rec "2", log with **H_upload** (session_id, status) so we can see if the 409 the user sees is from this endpoint.

Log file: **NDJSON** at `backend-cursor/.cursor/debug.log` (one JSON object per line). Fields include `location`, `message`, `data`, `hypothesisId`, `timestamp`.

## How to interpret the logs

| Log message | hypothesisId | Interpretation |
|-------------|-------------|----------------|
| `metric-answers: entry` then `metric-answers: wrong status → 409` | H1 | Backend received metric-answers but session was not `task_block` (e.g. double submit, or frontend sent to wrong session). |
| `metric-answers: idempotency 200` | H2 | Session was already `final_task_ready`; backend returned 200 with existing final_task. If user still sees 409, the 409 is from another request (e.g. recording-upload-url). |
| `metric-answers: after generate_final_task` | H3 | OpenAI call succeeded. If this line is missing and we see `metric-answers: exception`, OpenAI or something before it failed. |
| `metric-answers: after v2_update_session` with `update_result_is_none: true` | H4 | Session update may have failed (e.g. 0 rows updated). |
| `metric-answers: success, returning 200` | H5 | Backend returned 200 with final_task. If user still sees 409, the 409 is from **another** request (likely recording-upload-url "2" called too early). |
| `metric-answers: exception` | H5 | Backend threw (OpenAI, DB, etc.); response would be 500, not 409. |
| `recording-upload-url: 409 rec=2 wrong status` | H_upload | The 409 is from **recording-upload-url** (user or frontend called it with "2" while session was not `final_task_ready`). So either metric-answers never succeeded, or the frontend didn’t wait for it / didn’t refetch status before requesting upload-url "2". |

## Conclusion (to be filled after log analysis)

- If logs show **metric-answers: success, returning 200** and then **recording-upload-url: 409 rec=2 wrong status** → **frontend issue**: e.g. calling recording-upload-url "2" before refetching status, or not advancing UI after metric-answers 200.
- If logs show **metric-answers: wrong status → 409** → could be frontend (double submit, wrong session) or race.
- If logs show **metric-answers: exception** → **backend issue** (OpenAI or DB); user would typically see 500 unless the client maps it to 409.

Run the flow once (answer 3 questions, click Confirm), then share the contents of `.cursor/debug.log` to confirm which of the above happened.
