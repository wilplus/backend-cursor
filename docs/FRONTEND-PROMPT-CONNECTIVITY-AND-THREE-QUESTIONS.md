# Frontend prompt: fix connectivity and show the 3 metric questions

Use this in your **frontend** repo (Next.js app at app.willonski.com) to fix the “Backend server is not responding” error and to show the 3 metric questions on the right step.

---

## 1. Fix “Backend server is not responding”

The app shows this when it cannot reach the Flask backend.

**Do the following:**

1. **Backend URL**
   - Ensure `NEXT_PUBLIC_API_URL` is set to your backend base URL with no trailing slash, e.g. `https://flask-backend-production-ab37.up.railway.app`
   - All BFF requests should use this base (e.g. `fetch(\`${getBackendUrl()}/v2/homework/...\`)`). Do not add an extra `/` or path unless the backend expects it.

2. **CORS**
   - The Flask backend must allow your frontend origin (e.g. `https://app.willonski.com`) in CORS. If you see CORS errors in the browser console, add that origin to the backend’s allowed origins and redeploy.

3. **Health check**
   - Call `GET ${NEXT_PUBLIC_API_URL}/health` or your backend’s root from the browser or curl. If it fails, the backend is down or the URL is wrong — fix the backend or the env var.

4. **BFF routes**
   - Every student flow call must have a matching BFF route under `src/app/api/homework/` that forwards to the backend with `Authorization: Bearer <token>`. If any of these are missing, add them (see `docs/homework-bff-routes/` in the backend repo):
     - `POST session/start`
     - `GET session/status`
     - `GET session/[sessionId]/warm-up-task`
     - `GET session/[sessionId]/task-block`  ← **add this** so the 3 questions can be loaded when resuming
     - `POST session/[sessionId]/recording-1`
     - `POST session/[sessionId]/metric-answers`
     - `POST session/[sessionId]/recording-2`
     - etc.

5. **When to show the error**
   - Only show “Backend server is not responding” when a **real** request to the backend fails (e.g. session/status or session/start), not on page load before any request. That avoids false errors when the backend is slow or the user is offline only briefly.

---

## 2. When do the 3 questions appear?

They do **not** appear on the warm-up screen (step 1). They appear on **step 2**, after the user has submitted the first recording.

- **Step 1:** Warm-up task + “Start Recording” → user uploads recording 1.
- **Step 2:** Backend returns `task_block` with `context_short`, `focus_task`, and **metric_question_1**, **metric_question_2**, **metric_question_3** (each has `id` and `text`). Show “Answer these three questions” and use **metric_question_1.text**, **metric_question_2.text**, **metric_question_3.text** as the labels for three text inputs. Collect **answer_1**, **answer_2**, **answer_3** and POST to `POST /api/homework/session/<sessionId>/metric-answers` with body `{ answer_1, answer_2, answer_3 }`.

So: fix connectivity first so step 1 works (warm-up and recording-1). Then implement step 2 using the task block and the 3 question texts.

---

## 3. Implementing the “Answer these questions” screen (step 2)

**Data source**

- **Right after recording 1:** Use the **task_block** from the recording-1 response: `response.task_block` (with `metric_question_1`, `metric_question_2`, `metric_question_3`; each has `.text`).
- **On resume (e.g. user refreshes on step 2):** Call **GET /api/homework/session/<sessionId>/task-block** and use `response.task_block` the same way. Add the BFF route that proxies to the backend `GET /v2/homework/session/<sessionId>/task-block` (reference: `docs/homework-bff-routes/session/[sessionId]/task-block/route.ts` in the backend repo).

**UI**

- Title: e.g. “Answer these three questions”.
- For each of the 3 metric questions, show **metric_question_1.text**, **metric_question_2.text**, **metric_question_3.text** as the label (not “Metric question 1” etc.) and a single-line or multi-line input.
- Submit button: send `{ answer_1, answer_2, answer_3 }` to `POST /api/homework/session/<sessionId>/metric-answers`. On success, use `response.final_task` and move to step 3 (final task + second recording).

**Reference component**

- In the backend repo, `docs/frontend-v2-deliverables/components/AnswerMetricQuestionsScreen.tsx` is a reference React component that does the above. Copy it into your frontend and adapt imports and styling. Types: `TaskBlockV2`, `MetricAnswersResponseV2` in `docs/frontend-v2-deliverables/types-v2.ts`.

---

## 4. Checklist

- [ ] `NEXT_PUBLIC_API_URL` is correct and backend is reachable (e.g. health or session/status).
- [ ] CORS allows your frontend origin.
- [ ] All required BFF routes exist, including **GET session/[sessionId]/task-block**.
- [ ] Step 2 uses **task_block** from recording-1 response or from GET task-block; labels are **metric_question_1.text**, **metric_question_2.text**, **metric_question_3.text**.
- [ ] Submit sends **answer_1**, **answer_2**, **answer_3** to **POST session/:sessionId/metric-answers** and then shows **final_task** for step 3.
