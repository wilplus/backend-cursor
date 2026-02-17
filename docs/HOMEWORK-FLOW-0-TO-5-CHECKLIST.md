# Homework flow: make it work from step 0 to step 5

Use this checklist so the session flow works end-to-end no matter what. Check each item in order.

---

## 1. Database (Supabase)

Run these in the **Supabase SQL Editor** for the project this app uses (idempotent; safe to run more than once):

| Order | Migration | Purpose |
|-------|------------|---------|
| 1 | `migrations/v2_all_in_one.sql` | Base v2 schema |
| 2 | Coaching migrations (see architecture rule) | coaching_memory, performance_profile, etc. |
| 3 | **`migrations/add_tutor_feedback_deadline.sql`** | Adds `completed_at` on `v2_sessions` (required for step 4 → 5; avoids 500 / PGRST204) |
| 4 | **`migrations/add_tutor_feedback_sent_at.sql`** | Adds `tutor_feedback_sent_at` |
| 5 | **`migrations/add_index_v2_sessions_completed_lookup.sql`** | Optional: index to speed up coaching-memory "last 4 completed" query |

After adding columns: **Supabase Dashboard → Settings → API → Reload schema cache** (if available).

---

## 2. Backend (this repo)

- **Session expiry:** In-app expiry by age is already disabled (`v2_session_expired` always returns `False`). Incomplete sessions are not deleted on status/start. No change needed unless you reverted it.
- **Env:** `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `OPENAI_API_KEY`, `FRONTEND_URL`, etc. set where the backend runs (e.g. Railway).

---

## 3. BFF (Next.js API routes in your frontend app)

Every **dynamic** route under `src/app/api/homework/session/[sessionId]/` must use **synchronous params**. Otherwise production can return 404 for those routes.

For each of these files, ensure the handler looks like this (no `Promise`, no `await` on params):

- `session/[sessionId]/abandon/route.ts`
- `session/[sessionId]/metric-answers/route.ts`
- `session/[sessionId]/post-answers/route.ts`
- `session/[sessionId]/recording-1/route.ts`
- `session/[sessionId]/recording-2/route.ts`
- `session/[sessionId]/recording-upload-url/route.ts`
- `session/[sessionId]/questions/route.ts`
- `session/[sessionId]/task-block/route.ts`
- `session/[sessionId]/warm-up-task/route.ts` (if you have it)

**Correct pattern:**

```ts
export async function POST(
  request: NextRequest,
  { params }: { params: { sessionId: string } }
) {
  const { sessionId } = params;
  // ...
}
```

**Wrong (causes 404 in production):** `params: Promise<{ sessionId: string }> | { sessionId: string }` or `await (params as Promise<...>)`.

Reference routes in this repo: `docs/homework-bff-routes/session/[sessionId]/` (already fixed). Copy from there or align your frontend routes.

After changing: **redeploy the frontend** (e.g. Vercel) and use **Clear cache and deploy** if 404s persist.

---

## 4. Frontend UI (each step)

| Step | What must work |
|------|----------------|
| **0** | On load: `GET /api/homework/session/status`. If no active session, call `POST /api/homework/session/start`. Use `session.status` (or equivalent) to derive current step. |
| **1** | Warm-up text from status/start; recording-1 upload; then show step 2 (metric questions) using `task_block` from recording-1 response or status. |
| **2** | **Metric questions:** Use `task_block` from the recording-1 response when available. If you're on step 2 (status `task_block`) but don't have `task_block` in state (e.g. after refresh), either call **GET** `/api/homework/session/:id/task-block` and use its `task_block`, or build it from the session: `{ metric_question_1: { text: session.session_metric_question_1 }, metric_question_2: { text: session.session_metric_question_2 }, metric_question_3: { text: session.session_metric_question_3 } }`. The backend now persists these to the session when recording-1 succeeds, so GET status will include them. **Abandon** button and **Continue** + error display as above. |
| **3** | Show `final_task` from metric-answers response; recording-2 upload (60–300 s); then advance to step 4. |
| **4** | If no reflective questions, call `POST .../post-answers` with `answers: []` and go to step 5. Otherwise show questions, collect answers, submit post-answers. Show API error on 4xx/5xx. |
| **5** | Show report from post-answers response (`report_text`, `performance_score_end`, etc.). No need to call status (completed sessions are not returned by status). |

Use the **same `sessionId`** for all session-scoped requests (from the last status or start response). After any step-advancing call (start, recording-1, metric-answers, recording-2, post-answers), you can call **GET session/status** and set the current step from `session.status` so the UI stays in sync.

---

## 5. Quick verification

1. **Backend:** `GET https://YOUR_BACKEND_URL/v2/homework/session/status` with a valid `Authorization: Bearer <token>` returns 200 (body may be `has_active_session: false`).
2. **BFF:** From the app, in Network tab: `POST .../api/homework/session/.../metric-answers` and `POST .../api/homework/session/.../abandon` return **200** or **4xx with JSON body**, not 404.
3. **DB:** In Supabase, `SELECT column_name FROM information_schema.columns WHERE table_name = 'v2_sessions' AND column_name = 'completed_at';` returns one row.

If all three pass, the flow should run from step 0 to step 5. If something still breaks, note which step and which request (URL + status code + response body) and use the step-specific docs (`METRIC-QUESTIONS-STEP.md`, `STEP-4-POST-ANSWERS-500.md`, etc.).
