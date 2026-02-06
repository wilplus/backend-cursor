# Willab — App Description (Frontend Perspective)

A detailed description of what the app does from the user’s and frontend’s point of view. Use this for product copy, onboarding, or frontend implementation.

---

## What the app is

**Willab** is a **speech coaching app**. Students complete a **homework flow**: two voice recordings plus optional reflective questions, and receive an **AI-generated coaching report** with a performance score and tailored feedback. Coaches/admins configure each student (warm-up tasks, focus tasks, questions) and can view reports and edit content.

There are **two main surfaces** in the frontend:

1. **Student app** — The homework flow: warm-up → first recording → metric questions → second recording → (optional) reflective questions → report.
2. **Admin panel** — Student list, per-student profile (homework config, speaker profile, reports), and global pools (tasks, questions, metrics).

All student actions go through **`/api/homework/*`** (BFF proxies to backend `/v2/homework/*`). All admin actions go through **`/api/admin/*`** (BFF proxies to `/v2/admin/*`). Auth is **Supabase**: the frontend sends `Authorization: Bearer <supabase_access_token>` (and for admin, the logged-in user must be in the backend’s admin list).

---

## Student experience (homework flow)

### Entry and session start

- The student opens the **Homework** page (or equivalent “main” screen).
- The app **does not** show a “Start homework” button. On load it:
  - Calls **GET /api/homework/session/status**. If there is an active session (`has_active_session` and `session`), it **resumes** that session and shows the **current step** (e.g. warm-up, metric questions, recording 2, questions, or report).
  - If there is **no** active session, it calls **POST /api/homework/session/start** in the same load (e.g. in `useEffect`) and immediately shows the **first step** (warm-up task + record button).
- The student is always in one of five steps; the UI should reflect **session status** and show the right screen (warm-up, task block, final task ready, post questions, or completed).

### Step 1: Warm-up task and first recording

- The student sees a **warm-up task**: a short text (e.g. “Read the following aloud at a comfortable pace”). This text comes from **`warm_up_task.text`** (from session start or from GET session status). The backend **chooses** the warm-up based on the student’s **last performance score** (from their previous report): it picks a warm-up whose difficulty fits that score (and uses ±3% matching and randomization when several fit). First-time students get the easiest warm-up; high scorers may get the hardest if they outperformed all warm-up levels.
- The student **records** their voice (e.g. via browser MediaRecorder). The frontend sends the audio with **POST /api/homework/session/<session_id>/recording-1** (multipart, field `audio`; optional `duration_seconds`).
- After upload, the backend returns: **performance_score_1**, **context_short** (a short summary of what was said), and **task_block** (see next step). The session moves to **task_block**.

### Step 2: Focus task and metric questions

- The student sees the **task block**:
  - **Context:** The **context_short** from the first recording (what the system “heard”).
  - **Focus task:** A chosen **focus task** (title + prompt text). The backend selects it based on **performance_score_1**: it picks a task whose difficulty matches that score (e.g. score 0.6 → task with that level or easier). The student is meant to keep this focus in mind for the **second** recording.
  - **Two metric questions:** The backend returns **metric_question_1** and **metric_question_2** (e.g. “How would you rate your pacing in that take?” and “How would you rate your vocal strength?”). The frontend **must** show both and collect two text (or scale) answers.
- The student submits **answer_1** and **answer_2** with **POST /api/homework/session/<session_id>/metric-answers** (body `{ answer_1, answer_2 }`).
- The backend returns **final_task**: a short, AI-generated instruction (exactly two sentences) that combines (1) the context from the first recording and the focus task, and (2) “Focus especially on [answer_1] and [answer_2].” The session moves to **final_task_ready**.

### Step 3: Final task and second recording

- The student sees the **final_task** text: a single, clear instruction for the second recording (e.g. “Based on your tendency to rush through emotional moments, your task is: deliver a confident product pitch emphasizing benefits. Focus especially on maintaining steady pacing and reducing filler words.”).
- The student **records** again and uploads with **POST /api/homework/session/<session_id>/recording-2** (multipart, `audio`). The backend returns **performance_score_2** and moves the session to **post_questions**.

### Step 4: Reflective questions (optional)

- The frontend calls **GET /api/homework/session/<session_id>/questions**. The backend returns **questions** only if the admin has set **exactly 3** reflective questions for this student (`assigned_post_question_ids`). If the list is empty or not exactly three, the backend returns **questions: []** and the frontend should **skip** this step (no question UI, go straight to report).
- If there are three questions, the student answers each (e.g. yes/no, scale 1–5, or free text). The frontend sends **POST /api/homework/session/<session_id>/post-answers** with body `{ answers: [ { question_id, answer_text } ] }`. Use **stable keys** and **local state** per question so inputs don’t re-mount on every keystroke (avoid “only one letter at a time” bug).

### Step 5: Report and completion

- After post-answers (or after recording 2 if there are no questions), the backend generates the **report** and returns **report_text**, **performance_score_end**, and **performance_metrics**. The session moves to **completed**.
- **Report content (homework):** A **three-paragraph** coaching report:
  1. **Performance overview:** Overall performance score (average of the two recordings), whether the student improved or declined from first to second recording, and strongest/weakest metrics.
  2. **Detailed metric analysis:** Comments on strength (vocal projection), fillers, and pacing; **comparison of the student’s self-ratings** (the two metric answers) **with the measured performance**; and any discrepancies (e.g. “You rated pacing 4/5 but measurements show rushing”).
  3. **Actionable next steps:** One thing to keep doing, one to improve, and one concrete exercise or technique. The tone is encouraging but honest; length about 150–250 words.
- The frontend shows the **report** and the **performance_score_end** (and optionally the **performance_metrics**). The student has finished this homework run; the next time they open Homework, a new session can start and the **warm-up will be chosen** using this **performance_score_end** as their “last score.”

### Resuming an in-progress session

- If the student leaves and comes back, the app calls **GET /api/homework/session/status**. If **has_active_session** is true, the **session** object contains **id** and **status** (warm_up, task_block, final_task_ready, post_questions). The frontend should **render the correct step** (and, if needed, refetch step-specific data like warm-up task or task block) so the student can continue without starting over.

### Errors and edge cases (frontend)

- **Warm-up task is null:** The student has no warm-up tasks (or none matching their level). Show a clear message; the fix is in the admin (add warm-up tasks for this student and set **max_performance_score** per task).
- **404 on “start” or “backend not connected”:** The frontend is calling `/api/homework/session/start` but the Next.js app has no BFF route for it (or the path is wrong, e.g. `/api/homework/start`). Add the BFF route that proxies to the backend and ensure the frontend uses **/api/homework/session/start** and **/api/homework/session/status**.
- **Render warm_up_task as text:** Display **warm_up_task.text** (string), never the whole **warm_up_task** object in React — otherwise you get “Objects are not valid as a React child” (React error #31).

---

## Admin experience

### Overview

- The admin logs in with credentials that exist in the backend’s **admin_users** table. All admin API calls use the same Supabase token but the backend returns **403** if the user is not an admin.
- The frontend calls **`/api/admin/*`** (e.g. `/api/admin/students`, `/api/admin/students/:id`). The BFF proxies these to the backend **`/v2/admin/*`** with the admin’s token.

### Students list

- **Route (example):** `/admin/students`.
- The frontend calls **GET /api/admin/students** (with optional **limit**, **offset**). The response includes **students**: each has **user_id**, **email** / **user_email**, **sessions_count**, **last_session_at**, **avg_performance** (if available). The UI shows a list (e.g. table or cards); clicking a row opens that student’s **profile**.

### Student profile (single page)

- **Route (example):** `/admin/students/:id`.
- The frontend loads the profile with **GET /api/admin/students/:id**. The response includes:
  - **user_id**, **email**
  - **overrides:** e.g. **assigned_post_question_ids** (exactly 3 question IDs for reflective questions), **assigned_next_task_ids** (focus tasks for this student), **assigned_warm_up_task_id** (optional; if unused, backend selects warm-up by last score)
  - **speaker_profile:** e.g. **coach_notes** (single “Context” field)
  - **warm_up_tasks:** list of warm-up tasks for this student (each has **id**, **text**, **order_index**, **max_performance_score**)
  - **last_report**, **last_report_preview**
  - **sessions:** list of homework sessions (e.g. **id**, **created_at**, **status**, **report_preview.report_text_preview**)

The profile page is organized into sections:

#### Homework configuration

- **Send homework:** Button that calls **POST /api/admin/students/:id/send-assignment** (no body). Used to notify or mark that homework is assigned.
- **Save:** Saves overrides via **PUT /api/admin/students/:id/overrides** (body: **assigned_next_task_ids**, **assigned_post_question_ids** (exactly 3 when set), optionally **assigned_warm_up_task_id**). This configures which focus tasks and which three reflective questions the student sees (and optionally a fixed warm-up).
- **Warm-up tasks:** List of warm-up tasks for this student. Each has **text** and **max_performance_score** (0–1). Admin can add (POST), edit (PUT), and delete (DELETE) via **/api/admin/students/:id/warm-up-tasks** and **.../warm-up-tasks/:task_id**. **max_performance_score** controls which students see this warm-up (backend selects warm-ups where student’s last score ≤ this value; closest match ±3%, then random).
- **Focus tasks:** The student’s **assigned_next_task_ids** (from the global task pool). Admin picks from **GET /api/admin/tasks** and saves via **PUT .../overrides** with **assigned_next_task_ids**.
- **Reflective questions:** The student’s **assigned_post_question_ids** (exactly 3). Admin picks from **GET /api/admin/post-recording-questions** and saves via **PUT .../overrides** with **assigned_post_question_ids**. If this list is **empty** (or not 3), the student sees **no** reflective questions in the homework flow.
- **Metric questions (1 & 2):** Global metric questions (e.g. pacing, vocal strength) are managed via **GET/POST/PUT/DELETE /api/admin/metric-questions**. They are shown in the task block after the first recording.
- **Metrics (e.g. 5 labels):** Global metric definitions (e.g. pace, strength, fillers) via **GET /api/admin/metrics** and **PUT /api/admin/metrics**.

#### Speaker profile

- **Context (coach_notes):** A single text area. Saved with **PUT /api/admin/students/:id/speaker-profile** (body **{ coach_notes }**). Used by the backend in report generation (e.g. admin observations).

#### Last report / reports history

- **Last report:** Shown from profile’s **last_report** (full text) and **last_report_preview** (e.g. 500 chars).
- **Reports history:** From **sessions**: each session has **report_preview.report_text_preview** and **created_at**. Admin can open a session to see full details (and optionally edit report) via **GET /api/admin/students/:id/sessions/:session_id** and **PATCH .../sessions/:session_id/report** (append/replace report content).

### Global pools (admin)

- **Tasks:** **GET/POST/PUT/DELETE /api/admin/tasks** — used as the pool for **assigned_next_task_ids** (focus tasks).
- **Post-recording questions:** **GET/POST/PUT/DELETE /api/admin/post-recording-questions** — used for **assigned_post_question_ids** (exactly 3 per student).
- **Metrics:** **GET/PUT /api/admin/metrics** — fixed set of metric labels (e.g. 5).
- **Metric questions:** **GET/POST/PUT/DELETE /api/admin/metric-questions** — the two questions shown after the first recording (e.g. pacing, vocal strength).

These are typically used from the student profile (e.g. modals or dropdowns) to pick tasks and questions; the profile page does not need separate “Exercises” or “Questions” top-level pages.

---

## Auth (frontend)

- **Login:** User signs in (e.g. Supabase Auth or your login UI). After a successful **POST /auth/login**, the frontend must call **supabase.auth.setSession({ access_token, refresh_token })** so the stored session matches the backend. Use the same Supabase project (URL and anon key) as the backend.
- **Token:** Every request to the BFF (and thus to the backend) sends **Authorization: Bearer <supabase_access_token>**. The BFF forwards this header.
- **Admin:** Same token; the backend checks whether the user is in **admin_users**. If not, admin endpoints return **403**. The frontend should show an appropriate message or redirect when receiving 403 on admin routes.

---

## Summary: what the frontend does

| Area | What the frontend does |
|------|-------------------------|
| **Homework page load** | Calls session/status; if no active session, calls session/start; shows current step (warm-up, task block, final task, questions, or report) with no “Start” button. |
| **Warm-up** | Shows warm_up_task.text; records audio; POSTs to session/:id/recording-1. |
| **Task block** | Shows context_short, focus_task, metric_question_1, metric_question_2; collects answer_1, answer_2; POSTs metric-answers. |
| **Final task** | Shows final_task text; records audio; POSTs to session/:id/recording-2. |
| **Questions** | If GET questions returns a non-empty list, shows 3 questions; collects answers; POSTs post-answers. If empty, skips to report. |
| **Report** | Shows report_text, performance_score_end, performance_metrics; session is completed. |
| **Resume** | Uses session/status to restore session and re-render the correct step. |
| **Admin** | Lists students; opens profile; edits overrides, warm-up tasks, speaker profile; sends assignment; views/edits sessions and reports; manages global pools (tasks, questions, metrics). |

This is the full picture of the app from the frontend perspective.
