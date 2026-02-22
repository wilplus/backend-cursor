# Frontend: Skip step overrides (Step 2 & Step 4)

The backend returns and accepts **snake_case** fields in the single `overrides` object. If the UI shows toggles as always "on" after refresh, the frontend is usually not reading or sending these fields.

## Contract

- **GET** `GET /v2/admin/students/<id>` (or your BFF proxy) returns:
  ```json
  { "overrides": { "skip_metric_questions": false, "skip_post_questions": false, ... } }
  ```
- **PUT** `PUT /v2/admin/students/<id>/overrides` body must include:
  ```json
  { "skip_metric_questions": true, "skip_post_questions": false, ... }
  ```
- Field names are **snake_case** (`skip_metric_questions`, `skip_post_questions`). The backend does **not** return camelCase.

## Common frontend bugs

1. **Reading wrong key**  
   Backend: `response.overrides.skip_metric_questions`  
   Wrong: `response.overrides.skipMetricQuestions` → `undefined` → UI falls back to default ("on").

2. **Wrong path**  
   Correct: `response.overrides.skip_metric_questions`  
   Wrong: `response.student.overrides...` or `response.skip_metric_questions`.

3. **Not sending on save**  
   The PUT body must include `skip_metric_questions` and `skip_post_questions` (booleans). If the save payload is built from a whitelist or a subset of overrides and these two are missing, they will never persist.

4. **State overwriting fetched data**  
   Initial state (e.g. `skip_metric_questions: false`) must be overwritten when the profile is loaded. If the effect that sets state from `profile.overrides` doesn’t set `skip_metric_questions` and `skip_post_questions`, the toggles will never reflect the API.

## Fix checklist (frontend)

- [ ] **Types:** `overrides` includes `skip_metric_questions?: boolean` and `skip_post_questions?: boolean`.
- [ ] **Initial state:** Draft state includes `skip_metric_questions: false`, `skip_post_questions: false`.
- [ ] **Load:** When setting draft from `profile.overrides`, set both from `o.skip_metric_questions` and `o.skip_post_questions` (use `=== true` so only explicit `true` is on; otherwise default to `false`).
- [ ] **Save:** PUT body includes `skip_metric_questions` and `skip_post_questions` (same snake_case).
- [ ] **UI:** Toggles are bound to the draft fields that are loaded and sent as above.

Reference implementation in this repo: `docs/frontend-admin-panel/app/admin/students/[id]/page.tsx` and `docs/frontend-admin-panel/lib/api/admin-client.ts`.

---

## Step 2: "Could not load questions" → skip to report (step 5)

When the user is on step 2 and questions fail to load (e.g. "Could not load questions. Try continuing or refresh."), the frontend should **skip straight to the report** instead of leaving them stuck.

- **Endpoint:** `POST /v2/homework/session/<session_id>/complete-from-recording-1` (no body).
- **When to call:** After recording 1 is done, when step 2 (metric questions) fails to load or the user taps "Continue" from the error state.
- **Success (200):** Response is the same shape as POST post-answers: `status: "completed"`, `report_text`, `performance_score_end`, `performance_metrics`, `question_1_analysis` / `question_1_score`, etc. Show the report (step 5) with this payload.
- **409 RECORDING_1_PROCESSING:** Recording is still being analyzed. Show "Your recording is still being analyzed. Please wait a moment and try again." and optionally retry or poll GET session/status until ready, then call this endpoint again.
- **409 INVALID_SESSION_STATE:** Session is not in step 2 or report-generating; refetch GET session/status and show the correct step.

---

## Progress bar / performance score on report (step 5)

All report responses (POST complete-from-recording-1, POST post-answers, GET report) include:

- **`performance_score_end`** — The score to show on the main progress bar (0–1 or display as 0–100%).
- **`recording_count`** — `1` or `2`.
- **`performance_score_1`** — Score from the first (warm-up) recording.
- **`performance_score_2`** — Score from the second recording; only present when `recording_count === 2`. When `recording_count === 1`, use `performance_score_1` (same as `performance_score_end`) for the bar.

**Frontend logic:**

- If **`recording_count === 1`:** Show one progress bar with `performance_score_end` (or `performance_score_1`; they are equal). Label e.g. “Your score” or “Performance (1 recording)”.
- If **`recording_count === 2`:** Show the main bar with `performance_score_end` (end score). Optionally show warm-up vs final: `performance_score_1` and `performance_score_2`.
