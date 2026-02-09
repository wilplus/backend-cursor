# Homework flow — who does what (backend vs frontend)

Clear split: what **you** (backend/DB) do, and what the **frontend** must do for warm-up requirement and metric-answers validation.

---

## 1) What YOU do (backend / DB)

### 1.1 Run the migration (once per environment)

Run this in **Supabase SQL Editor** (or your Postgres client) so `v2_sessions` has the required columns:

```sql
-- Add missing v2_sessions columns (idempotent)
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS warm_up_task_id UUID;
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS warm_up_task_text TEXT;
ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS final_task_text TEXT;
```

- After running: reload PostgREST schema cache if needed (Supabase: Settings → API → reload, or restart project), so PGRST204 errors go away.
- If you still see PGRST204 for other columns, run the full **§1** block in `docs/MIGRATION-PLAN-MINIMAL-DIFF.md`.

### 1.2 Backend behavior (already implemented)

- **No warm-up:**  
  - **POST /v2/homework/session/start** (new session or resume): if the user has **no** warm-up tasks, backend returns **422** with:
  - `code`: `"NO_WARMUP_CONFIGURED"`
  - `message`: `"No warm-up tasks are configured for your account. Please contact your coach to get started."`
  - No session is created on new start; on resume, same 422 so user cannot proceed.

- **Metric answers:**  
  - **POST /v2/homework/session/{id}/metric-answers**: if any of the three answers is missing or empty, backend returns **422** with:
  - `code`: `"VALIDATION_ERROR"`
  - `message`: `"Please answer all three questions before continuing."`
  - `details`: `{ "field": "metric_answers" }`

You don’t need to change anything else on the backend for these two guardrails.

---

## 2) What the FRONTEND must do

### 2.1 Handle “no warm-up” (422 NO_WARMUP_CONFIGURED)

**When:** After calling **POST /v2/homework/session/start** (or **GET /v2/homework/session/status** if you treat resume the same).

**If response is 422 and `body.code === "NO_WARMUP_CONFIGURED"`:**

1. **Do not** show the homework flow (step 1, recorder, etc.). The user must not be able to “proceed” without a warm-up.
2. **Show** a clear, user-facing message, for example:
   - *“No warm-up tasks are configured for your account. Please contact your coach to get started.”*
3. **Options** to show:
   - “Contact your coach” (or link to support / coach).
   - “Log out” or “Back to dashboard” so they can leave the homework screen.
4. **Do not** create or assume an active session; backend did not create one (or should not be used for homework until warm-ups exist).

**Also:** If the app calls **GET /v2/homework/session/status** and the backend ever returns 422 for “no warm-up” on that path, handle it the same way (same message, no flow).

### 2.2 Require all three metric answers (step 2)

**When:** User is on step 2 (the “Answer these three questions” screen) and taps **Continue** (or equivalent).

**Option A — Validate before calling backend (recommended):**

1. Before **POST /v2/homework/session/{id}/metric-answers**, check that all three fields (answer_1, answer_2, answer_3 — or whatever the UI uses) are non-empty (after trim).
2. If any is empty:
   - Show message: *“Please answer all three questions before continuing.”*
   - Do **not** call the backend; keep user on step 2.
3. If all three are filled, send the request. If backend still returns 422 VALIDATION_ERROR, show the same message (Option B below).

**Option B — Handle backend 422:**

1. When calling **POST /v2/homework/session/{id}/metric-answers**, if response is **422** and `body.code === "VALIDATION_ERROR"`:
2. Show message: *“Please answer all three questions before continuing.”* (or use `body.message`).
3. Keep user on step 2; do not advance to step 3.

**Optional UX:** Disable the Continue button until all three answers are non-empty, and show a short hint like “Answer all three questions to continue.”

---

## 3) Quick reference

| Topic | You (backend/DB) | Frontend |
|--------|-------------------|----------|
| **Missing columns (PGRST204)** | Run migration (add `warm_up_task_id`, `warm_up_task_text`, `final_task_text`); reload schema | — |
| **No warm-up** | Return 422 `NO_WARMUP_CONFIGURED` on start/resume when no warm-up tasks | On 422: show message; do not show homework flow; offer contact coach / leave |
| **Metric answers** | Return 422 `VALIDATION_ERROR` if any answer empty | Validate before submit and/or on 422: show “Please answer all three questions”; keep on step 2 |

---

## 4) API response shapes (for frontend)

**422 NO_WARMUP_CONFIGURED (session start or resume):**
```json
{
  "code": "NO_WARMUP_CONFIGURED",
  "message": "No warm-up tasks are configured for your account. Please contact your coach to get started.",
  "details": {}
}
```

**422 VALIDATION_ERROR (metric-answers):**
```json
{
  "code": "VALIDATION_ERROR",
  "message": "Please answer all three questions before continuing.",
  "details": { "field": "metric_answers" }
}
```

Frontend should use `code` to decide behavior and `message` (or a fixed string) for the user-facing text.
