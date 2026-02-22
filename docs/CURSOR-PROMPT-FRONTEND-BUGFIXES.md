# Frontend Cursor prompt: willab bugfixes (production-ready)

You are a senior frontend engineer working on **willab** (willpower lab), the speech coaching app: Next.js frontend with BFF (API routes proxy to Flask backend). The app has a **status-driven homework flow** for students (warm-up → metric questions → final recording → post-questions → report). The flow can **skip steps** (e.g. no focus tasks → report after recording-1 only; or step 2 → report via complete-from-recording-1). Your task is to support **five backend bugfixes** and implement the **admin + student UI for the video feature** without breaking the API contract.

---

## Architecture context

- **BFF:** Next.js API routes under `src/app/api/homework/*` and `src/app/api/admin/*` proxy to the backend (`/v2/homework/*`, `/v2/admin/*`). Preserve request/response shapes; do not strip `status` or rename fields (e.g. `report_text`).
- **Student flow:** `HomeworkFlowCard.tsx` (or equivalent) drives the step from backend `status`. **Single source of truth:** top-level `status`. Use `applyStatusToState(res)` after mutations and on cold load. The flow is status-driven and can skip steps (e.g. `report_generating` then `completed` after one recording); do not enforce a strict 0→5 sequence. See `docs/HOMEWORK-AND-PERFORMANCE.md` for the full contract.
- **Admin:** Admin pages and API client for students, tasks, warm-ups, post-questions, speaker profile, and **send assignment**. Reference: `docs/frontend-admin-panel/` in the backend repo.
- **Key contracts:** Status values `none` | `recording_1_required` | `task_block` | `final_task_ready` | `post_questions` | `report_generating` | `completed`. Step = map from status only; flow can skip steps. Report data comes from POST post-answers, POST complete-from-recording-1, or GET report/session when available.

---

## Issues and your role

### 1. Performance score 2 always shows 30% (backend fix; frontend verify)

**Backend:** Fixes the scoring logic so `performance_score_2` is no longer hardcoded to 30%.

**Your role:**

- Ensure the **report step (step 5)** and any **dashboard/history** views that show `performance_score_2` or `performance_score_end` use the values returned by the API (e.g. from POST post-answers or GET session). No client-side override or default to 30%.
- After the backend fix, verify that after a full flow the displayed score matches the backend response (e.g. check Network tab: POST post-answers response body).

---

### 2. Report description only filler count + time in range (backend fix; frontend display)

**Backend:** Changes the report generation so the text contains only filler count and time in good range (or “not yet tracked”).

**Your role:**

- The report is still shown from the same field: **`report_text`** (from POST post-answers response, or from session when loading a completed session). No API contract change.
- Ensure the **report UI** (step 5) renders `report_text` as the main description. If you currently truncate or reshape it, stop; show the backend string as-is so the new concise format is visible.
- Optional: if you have a separate “metrics” or “stats” block, you can keep it; the main report copy should be the new short backend text.

---

### 3. Where “context” is stored/used (backend doc; frontend awareness)

**Backend:** Adds `docs/CONTEXT-FIELDS.md` (or equivalent) describing `context_short`, `context_long`, `coach_notes`.

**Your role:**

- **Do not** send “context” to the backend in places the API doesn’t expect (e.g. do not add a new “context” field to requests unless the backend adds it).
- On the **report screen**, the text you show is `report_text` (backend’s `context_long` content). Admin views may show session detail including the same report text. No frontend change required unless you were misusing a context field; if so, align with the backend doc.

---

### 4. Homework email design (backend fix)

**Backend:** Improves the HTML and layout of the assignment email sent by POST send-assignment.

**Your role:** None. Email is sent server-side. Optionally, after the backend change, trigger a test send from the admin “Send assignment” button and confirm the received email looks correct.

---

### 5. Admin video upload/URL + student video (full-stack; frontend implementation)

**Backend (done by backend team):** Adds `tutor_video_url` to session; send-assignment accepts optional `video_url`; GET session/status returns `tutor_video_url` when set.

**Your role: implement the UI.**

#### 5a. Admin: send assignment with video URL

- **Place:** On the same screen/modal where the admin clicks “Send assignment” (e.g. student detail or homework config).
- **UI:** Add an optional field: “Video URL (optional)” — text input where the admin can paste a link (e.g. Loom, YouTube, Supabase Storage). Add a second optional field: “Video description (optional)” — textarea or input where the admin can write a short message to the student (e.g. what to focus on). Optional: “Upload video” that uploads to your storage and then pastes the resulting URL into this field (if backend adds an upload endpoint later, you can call it and set the field).
- **API:** When the user clicks “Send assignment”, call **POST /api/admin/students/[id]/send-assignment** with a body when needed, e.g. `{ "video_url": "<value>", "video_description": "<value>" }`. Both are optional; backend accepts up to 2000 chars for `video_description`. Send only non-empty fields.
- **BFF:** Ensure the route that proxies to **POST /v2/admin/students/<id>/send-assignment** forwards the request body (including optional `video_url` and `video_description`) to the backend.

#### 5b. Student: show video on homework page

- **When:** When the student is on the homework flow and the current session has a tutor video (e.g. `session.tutor_video_url` or the value returned in GET session/status in the session object).
- **Where:** Show the video in a sensible place: e.g. on **step 0** (no active session but show “Your coach left you a message” with the video), or at the top of the flow when there is an active session with `tutor_video_url`, or on **step 5** (report) as “Coach’s message”. Align with product: one clear place so the student sees it once per assignment.
- **How:** If the URL is to a public page (e.g. Loom, YouTube), you can use an iframe or a link “Watch video” that opens in a new tab. If it’s a direct video file URL, use a `<video>` tag or a link to open/download. Prefer a simple link/button if the URL might be any of these.
- **Data:** GET session/status returns the session object; ensure your type and state include `tutor_video_url` (optional string) and `tutor_video_description` (optional string). When you have an active session, read both and render the video block when `tutor_video_url` is non-empty; show `tutor_video_description` above or beside the video link when present.

**Acceptance:**

- Admin can paste a video URL and optionally a video description, then send assignment; the request includes `video_url` and/or `video_description` when provided.
- Student receives the email (with video link and description if set) and, after starting homework, sees the tutor video and description on the homework page when the backend returns `tutor_video_url` (and optionally `tutor_video_description`).

---

## Testing checklist

- [ ] **Score 2:** After backend fix, run a full flow and confirm the score shown on the report step matches the API (no 30% stuck).
- [ ] **Report:** After backend fix, confirm the report step shows the new short text (filler count + time in range or “not yet tracked”).
- [ ] **Context:** No unintended “context” usage on the frontend; report screen shows `report_text` only.
- [ ] **Email:** No frontend change; optional: trigger send and check inbox.
- [ ] **Video:** Admin can enter video URL and send assignment; student sees the video on the homework page when `tutor_video_url` is present in the session.

**Critical:** Keep the homework flow status-driven (applyStatusToState; flow can skip steps). Do not remove or rename API calls (e.g. keep using `report_text`). Add the video field and UI only where described; keep the rest of the contract unchanged.
