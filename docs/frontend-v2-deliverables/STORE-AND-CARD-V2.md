# Store + SessionCardV2 — Full V2 Flow

Use this to wire **session-store-v2** and **SessionCardV2** to the real v2 backend (universal questions → exercise → task → intent → recording → 5 metrics + post-questions → report).

---

## 1. V2 state machine (suggested)

Keep your existing v2 store states or align to this sequence:

- `idle` — no session or not yet started
- `universal_questions` — showing 3 universal questions (mood, readiness, mode_preference)
- `exercise` — showing exercise (video/description + "Did you like it?"); **skip** if `plan.exercise === null`
- `task` — showing task(s): either one auto-selected task or 3 options to choose from
- `intent` — showing intended emotion + 3 keywords inputs
- `recording_ready` — ready to record (task + intent done)
- `recording` — user is recording
- `recorded` — blob ready, not yet uploaded
- `uploading_processing` — upload + transcription in progress
- `post_questions` — showing 3 post-recording questions
- `finalizing` — submitted post-answers, report generating
- `completed` — report and metrics shown

---

## 2. Store state to add (session-store-v2)

Add these to your v2 store (names can match your style):

```ts
// From backend
universalQuestions: UniversalQuestionV2[] | null;
plan: UniversalAnswersPlanV2 | null;       // set after universal-answers
sessionId: string | null;
taskId: string | null;                       // selected task id for upload
postQuestionsV2: PostRecordingQuestionV2[];  // from plan
// User inputs
universalAnswers: { mood: number; readiness: number; mode_preference: number } | null;
intendedEmotion: string;
keywords: string[];
// After upload
uploadResultV2: UploadRecordingResponseV2 | null;  // recording_id, performance_metrics, metric_labels_snapshot
// After post-answers
reportText: string | null;
performanceScoreV2: number | null;
performanceMetricsV2: PerformanceMetricsV2 | null;
metricLabelsSnapshotV2: Record<string, { left_label: string; right_label: string }> | null;
// UI state
errorV2: string | null;
```

---

## 3. Store actions to add

Call **v2Api** from `client-v2.ts` (not v1 endpoints) for these:

| Action | When | API call |
|--------|------|----------|
| `fetchUniversalQuestions` | When entering v2 flow (e.g. universal_questions state) | `v2Api.getUniversalQuestions()` |
| `fetchSessionStatusV2` | On v2 init (mount of SessionCardV2) | `v2Api.getSessionStatus()` |
| `startSessionV2` | If no active session | `v2Api.sessionStart()` |
| `submitUniversalAnswers` | User submits mood, readiness, mode_preference | `v2Api.postUniversalAnswers(sessionId, { mood, readiness, mode_preference })` → set `plan`, then transition to `exercise` or `task` (skip exercise if `plan.exercise === null`) |
| `submitExerciseFeedback` | User clicks Like / Don't like | `v2Api.postExerciseFeedback(sessionId, exerciseLiked)` → transition to `task` |
| `submitSelectTask` | User picks one of 3 options (only in "choose" mode) | `v2Api.postSelectTask(sessionId, taskId)` → set `taskId`, transition to `intent` |
| `submitIntent` | User submits emotion + 3 keywords | `v2Api.postIntent(sessionId, { intended_emotion, keywords })` → transition to `recording_ready` |
| `uploadRecordingV2` | When user stops recording (or on "Submit" after recording) | Build FormData with session_id, task_id, audio blob; call `v2Api.uploadRecording(sessionId, taskId, blob)` → set `uploadResultV2`, transition to `post_questions` |
| `submitPostAnswersV2` | User submits 3 post-answers | `v2Api.postPostAnswers(sessionId, answers)` → set report + metrics, transition to `completed` |

**Resume logic (v2 init):**

1. Call `v2Api.getSessionStatus()`.
2. If `!has_active_session` → set state to `idle` (and optionally call `v2Api.sessionStart()` on "Start").
3. If there is an active session:
   - Set `sessionId` from response.
   - Derive step from backend `session.status` or from what’s already in the session (e.g. if `universal_answers` exists, you’re past universal questions; if `selected_task_id` or `task_option_ids` exist, you have a plan; if `recording_id` exists, you’re at post_questions; if `report_id` exists, completed).
   - If you don’t have `plan` in store but session has already passed universal_answers, you may need to refetch or store plan in session from a previous response; for a clean resume you can store `plan` in localStorage under `willab:v2:plan:${sessionId}` after universal-answers and restore it on resume.

---

## 4. SessionCardV2 UI by state

| State | What to render |
|-------|----------------|
| `idle` | "Start session" button → call `startSessionV2`, then go to `universal_questions`. |
| `universal_questions` | Fetch questions once (`fetchUniversalQuestions`); form: mood slider 0–1, readiness 1–10, mode 0 = "Guide me" / 1 = "I'll choose". Submit → `submitUniversalAnswers`. |
| `exercise` | Show `plan.exercise` (title, video if present, description). Buttons: "I liked it" / "I didn't" → `submitExerciseFeedback` → go to `task`. |
| `task` | If `plan.selected_task`: show one task (title + prompt_text). If `plan.task_options`: show 3 cards, user picks one → `submitSelectTask`. Then "Next" or auto → `intent`. |
| `intent` | Show `plan.intent_prompts.intended_emotion` and `plan.intent_prompts.keywords`. Inputs: text + 3 keyword fields. Submit → `submitIntent` → `recording_ready`. |
| `recording_ready` | Show selected task again + "Start recording". Button → start recording, state → `recording`. |
| `recording` | Your existing `AudioRecorder`; on stop → state `recorded`, keep blob in store. |
| `recorded` | "Submit recording" (or auto-upload). Call `uploadRecordingV2(sessionId, taskId, blob)` → state `uploading_processing`. |
| `uploading_processing` | Spinner; when upload resolves → set `uploadResultV2`, state `post_questions`. |
| `post_questions` | Show 3 questions from `plan.post_recording_questions` (or `postQuestionsV2`). One is emotion_achieved_check (yes/no). Form: question_id + answer_text per question. Submit → `submitPostAnswersV2` → state `finalizing`. |
| `finalizing` | Brief spinner; when post-answers response returns → set report + metrics, state `completed`. |
| `completed` | Show `reportText`, and 5 metric bars using `performanceMetricsV2` + `metricLabelsSnapshotV2` (left_label / right_label per metric). |

---

## 5. Client-v2 base URL

In `client-v2.ts` you have `getBase()` returning `""` so that `fetch("/api/...")` is same-origin (no v2 in path). If your app is deployed with a path prefix, use that:

```ts
const getBase = () => (typeof window !== "undefined" ? "" : "");
```

Keep BFF under the same origin so cookies/credentials work.

---

## 6. Draft persistence (v2)

Keep using v2-only keys so v1 is untouched:

- `willab:v2:draft:universal_answers:${sessionId}`
- `willab:v2:draft:post_answers:${sessionId}`
- `willab:v2:plan:${sessionId}` (optional, for resume)

---

You now have: **types**, **client**, **BFF routes**, and **store + card behavior**. Copy the deliverables into the frontend repo and adjust imports (e.g. `@/lib/api/types-v2`, `@/lib/api/client-v2`) and auth (getAuth) to match your project.
