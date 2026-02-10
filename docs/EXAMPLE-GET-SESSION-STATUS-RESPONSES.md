# Example GET session/status responses (for frontend matching)

Two real-shaped responses from the backend so you can check field names, presence, and shape. IDs are redacted with placeholders.

---

## 1. Session in `task_block` (step 2)

```json
{
  "session": {
    "id": "9cf95976-c4a3-496d-bbe8-987113d966c4",
    "user_id": "5e33e0f1-0945-458c-8987-eadf43acf955",
    "status": "task_block",
    "created_at": "2026-02-10T12:00:00.000000Z",
    "warm_up_task_id": "warm-up-task-uuid-1",
    "warm_up_task_text": "How was your day so far?",
    "session_metric_question_1": "How clear was your message?",
    "session_metric_question_2": "How engaging did you sound?",
    "session_metric_question_3": "How well did you stay on topic?",
    "recording_1_id": "recording-uuid-1",
    "context_short": "The speaker's warm-up has a reflective tone and touches on the day so far.",
    "performance_score_1": 0.72,
    "selected_task_id": "focus-task-uuid-1",
    "metric_answers": null,
    "final_task_text": null,
    "recording_2_id": null,
    "performance_score_2": null,
    "post_question_ids": null,
    "context_long": null,
    "context_long_entries": [],
    "performance_score_end": null
  },
  "session_id": "9cf95976-c4a3-496d-bbe8-987113d966c4",
  "has_active_session": true,
  "warm_up_task": {
    "id": "warm-up-task-uuid-1",
    "text": "How was your day so far?"
  }
}
```

**Frontend mapping (step 2):**

- **step** → 2 from `session.status === "task_block"`.
- **sessionId** → `session_id` or `session.id`.
- **warmUpText** → `warm_up_task.text` or `session.warm_up_task_text`.
- **taskBlock** → Not present as a shaped object. Session has `session_metric_question_1/2/3` (text only). Frontend should call **GET task-block** when step === 2 and taskBlock empty; or build a minimal taskBlock from the three session_metric_question_* strings if you don’t need question ids.
- **finalTaskText** → `session.final_task_text` is null (step 2); leave empty.
- **reportText** / **performanceScoreEnd** → null; ignore for step 2.

**Possible mismatch:** Frontend may expect a top-level **`task_block`** object like `{ metric_question_1: { id, text }, ... }`. Backend does **not** send that in status; it only has `session.session_metric_question_1/2/3` (plain strings). So either call GET task-block for step 2 or map the three strings to your TaskBlockV2 shape (e.g. with synthetic or null ids).

---

## 2. Session in `final_task_ready` (step 3)

```json
{
  "session": {
    "id": "9cf95976-c4a3-496d-bbe8-987113d966c4",
    "user_id": "5e33e0f1-0945-458c-8987-eadf43acf955",
    "status": "final_task_ready",
    "created_at": "2026-02-10T12:00:00.000000Z",
    "warm_up_task_id": "warm-up-task-uuid-1",
    "warm_up_task_text": "How was your day so far?",
    "session_metric_question_1": "How clear was your message?",
    "session_metric_question_2": "How engaging did you sound?",
    "session_metric_question_3": "How well did you stay on topic?",
    "recording_1_id": "recording-uuid-1",
    "context_short": "The speaker's warm-up has a reflective tone and touches on the day so far.",
    "performance_score_1": 0.72,
    "selected_task_id": "focus-task-uuid-1",
    "metric_answers": {
      "answer_1": "Clear enough",
      "answer_2": "Quite engaging",
      "answer_3": "On topic"
    },
    "final_task_text": "Summarize your main point in one or two sentences and end with a clear call to action.",
    "recording_2_id": null,
    "performance_score_2": null,
    "post_question_ids": null,
    "context_long": null,
    "context_long_entries": [],
    "performance_score_end": null
  },
  "session_id": "9cf95976-c4a3-496d-bbe8-987113d966c4",
  "has_active_session": true,
  "warm_up_task": {
    "id": "warm-up-task-uuid-1",
    "text": "How was your day so far?"
  }
}
```

**Frontend mapping (step 3):**

- **step** → 3 from `session.status === "final_task_ready"`.
- **sessionId** → `session_id` or `session.id`.
- **warmUpText** → `warm_up_task.text` (still present for resume).
- **taskBlock** → Already filled from step 2 or from GET task-block; not needed to re-fetch for step 3.
- **finalTaskText** → `session.final_task_text` (use this for the Final task screen).
- **reportText** / **performanceScoreEnd** → null; ignore for step 3.

**Possible mismatch:** Frontend might expect **`final_task`** (object with e.g. `text`) instead of **`final_task_text`** (string). Backend only has **`session.final_task_text`** (string). So map `session.final_task_text` → **finalTaskText**; there is no `final_task.text` at top level.

---

## 3. Checklist for frontend

| Expectation | Backend reality | Action |
|-------------|-----------------|--------|
| Step from status | `session.status` is the only source (warm_up, task_block, final_task_ready, post_questions, completed). | Use it; no top-level `step`. |
| Session id | Top-level **session_id** and **session.id** (same value). | Use either. |
| warm_up_task | Top-level **warm_up_task**: `{ id, text }`. Also on session as warm_up_task_id, warm_up_task_text. | Use **warm_up_task.text** for warmUpText. |
| task_block (3 questions) | Not a shaped object in status. Session has **session_metric_question_1**, **session_metric_question_2**, **session_metric_question_3** (strings). | Call **GET task-block** when step 2 and taskBlock empty; or build from the 3 strings. |
| final_task | No **final_task** object. Session has **final_task_text** (string). | Map **session.final_task_text** → finalTaskText. |
| questions (step 4) | Session has **post_question_ids** (array of ids). No question list in status. | Call **GET questions** when step 4 and questions empty. |
| reportText | **session.context_long** (string, when completed). | Map to reportText. |
| performanceScoreEnd | **session.performance_score_end** (number, when completed). | Map directly. |
| Snake_case | All session fields and top-level payload use **snake_case** (session_id, warm_up_task, final_task_text, etc.). | Frontend must read snake_case or transform once. |

If you paste these two JSONs into your frontend types or tests and ensure you read **session.status**, **session_id** / **session.id**, **warm_up_task**, **session.final_task_text**, **session.context_long**, **session.performance_score_end**, and the three **session_metric_question_*** (or GET task-block), you’ll match the backend. The only common mismatches are expecting **task_block** or **final_task** as objects; the backend only has **session_metric_question_1/2/3** and **final_task_text**.

---

## 4. Contract realities: compatible vs incompatible

These two example payloads are **compatible with the flow** described in IMPLEMENT-THIS-TO-MAKE-FLOW-WORK.md, but they confirm contract realities the frontend must follow or it will show placeholders / call the wrong endpoints.

### Compatible (frontend can work as-designed)

| # | Item | Detail |
|---|------|--------|
| 1 | **Session id** | Backend provides both `session_id` (top-level) and `session.id` (nested), same value. Frontend plan `session_id ?? session?.id` is correct. |
| 2 | **Step / source-of-truth** | Backend provides `session.status` (nested only). Deriving step purely from `session.status` is correct and prevents INVALID_SESSION_STATE. |
| 3 | **Warm-up prompt** | Backend includes it in two places: top-level `warm_up_task: { id, text }` and nested `session.warm_up_task_text`. Frontend can reliably show warm-up text even on resume in later statuses. |
| 4 | **Final task text** | Backend uses **`session.final_task_text`** (string) in `final_task_ready`. Map that directly to `finalTaskText`. |

### Incompatibilities / “must-handle” gaps (where frontend often breaks)

| Id | Issue | Impact | Fix |
|----|--------|--------|-----|
| **A** | **No `task_block` object in status** | Backend does not send `task_block: { metric_question_1: {id,text}, ... }`. Only `session.session_metric_question_1/2/3` (plain strings). | If UI expects `statusRes.task_block`, step 2 looks empty. **Fix:** If the backend does **not** expose GET task-block, do not call it — use only status fields (`session_metric_question_1/2/3`) to build a minimal taskBlock (IDs null/synthetic). If GET task-block **does** exist, you can call it when step === 2 and task block is still missing. |
| **B** | **No `final_task` object** | Backend does not return `final_task: { text: "..." }`. Only `session.final_task_text: "..."`. | If UI looks for `final_task.text`, it shows a placeholder. **Fix:** Map `session.final_task_text → finalTaskText` only. |
| **C** | **Status does not include post-recording question objects** | Backend has `session.post_question_ids` (IDs only), not the question list. | Step 4 shows “no questions” if you don’t fetch. **Fix:** On `status === "post_questions"`, if questions state is empty, call GET questions (using sessionId). |
| **D** | **Report text field is `context_long`, not `report_text`** | Backend shape is `session.context_long` (string) when completed. | If frontend reads `report_text`, report is blank. **Fix:** Map `session.context_long → reportText`. |
| **E** | **Everything is snake_case** | Backend uses snake_case (`final_task_text`, `session_metric_question_1`, etc.). | If frontend assumes camelCase, you get silent `undefined` and fallbacks. **Fix:** Read snake_case everywhere, or transform once in `applyStatusToState()` / `normalizeStatusResponse()` and use normalized camelCase internally. |

### Additional watch-outs (common bug sources)

- **`has_active_session: false`** — Backend can return `{ "has_active_session": false, "session": null }`. Frontend must treat as: no sessionId, no recorder; require POST session/start before any recording or metrics.
- **Metric answers shape** — Backend shows `metric_answers: { "answer_1": "...", "answer_2": "...", "answer_3": "..." }`. If frontend stores answers as an array or different keys, normalize on submit/resume.

### Minimal mapping to implement (matches these payloads)

Use this in `applyStatusToState(res)` (or a single normalizer):

```ts
sessionId     = res.session_id ?? res.session?.id ?? null
status        = res.session?.status ?? null
warmUpText    = res.warm_up_task?.text ?? res.session?.warm_up_task_text ?? ""
// Step 2 task block (no shaped task_block in status):
q1            = res.session?.session_metric_question_1
q2            = res.session?.session_metric_question_2
q3            = res.session?.session_metric_question_3
finalTaskText = res.session?.final_task_text ?? ""
reportText    = res.session?.context_long ?? ""
performanceScoreEnd = res.session?.performance_score_end ?? null
```

Derive **step** from `status`: warm_up→1, task_block→2, final_task_ready→3, post_questions→4, completed→5.

### Bottom line

The payloads are **compatible**, but **not plug-and-play** unless the frontend stops expecting:

- a **`task_block`** object in status (use session_metric_question_1/2/3; only call GET task-block if the backend exposes it and task block is still missing),
- a **`final_task`** object (use **session.final_task_text**),
- a **questions list** in status (use GET questions for step 4),
- the name **`report_text`** (use **session.context_long**).

Implement the minimal mapping above in one place and drive step only from `session.status`; then the flow will match the backend.
