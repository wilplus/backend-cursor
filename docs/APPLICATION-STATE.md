# Detailed description of the current application state

This document describes the **backend-cursor** application as it exists today: identity, stack, structure, current student flow, admin, legacy parts, and how to restore removed steps.

---

## 1. Project identity and tech stack

| Layer | Technology |
|-------|------------|
| **Backend** | Flask (Python 3), served by Gunicorn in production |
| **Hosting** | Railway (Procfile; env vars in dashboard) |
| **Database & auth** | Supabase (PostgreSQL via Supabase client; JWT auth) |
| **Storage** | Supabase Storage (bucket `audio_recordings` for recordings) |
| **AI** | OpenAI: Whisper (transcription), GPT-4o-mini (context/reports) |
| **Email** | Resend (e.g. lesson-complete to coach, send-assignment to student) |
| **Frontend** | Separate app (Next.js); `FRONTEND_URL` in config (e.g. `app.willonski.com` or `http://localhost:3000`) |

**Key dependencies** (from `requirements.txt`): Flask 3.0, flask-cors, gunicorn, python-dotenv, PyJWT, cryptography, supabase, httpx, openai, sentry-sdk[flask], resend, numpy.

**Config** (`config.py`): All configuration is read from environment (`.env` locally). Required: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `OPENAI_API_KEY`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `ADMIN_EMAIL`, `FRONTEND_URL`. Optional: `SENTRY_DSN`, `ENV`, `SEND_EMAILS`, `CORS_ORIGINS`, `TUTOR_FEEDBACK_WINDOW_HOURS`, etc.

---

## 2. Application entry and blueprints

- **Entry:** `app.py` creates the Flask app, sets `MAX_CONTENT_LENGTH` for large uploads (e.g. 25MB), registers CORS and blueprints, and defines health routes (`/`, `/health`, `/api/health`, `/health/jwks`).
- **Blueprints registered:**
  - `auth_bp` → `/auth`
  - `recordings_v2_bp` → `/v2/recordings`
  - `user_bp` → `/user`
  - `admin_bp` → `/admin` (legacy admin)
  - `v2_bp` → `/v2` (so admin routes are under `/v2/admin/*`)
  - `homework_bp` → `/v2/homework` (student homework flow)

The **student-facing product flow** is homework only, under **`/v2/homework/*`**. Legacy routes (`/session`, `/recordings`, `/questions`, `/admin`) still exist but the main flow is v2 homework.

---

## 3. Current student homework flow (simplified — steps 2–4 removed)

**Important:** Steps 2 (metric questions), 3 (final task + recording 2), and 4 (post-questions) have been **fully removed** from the codebase (temporary). The flow is:

**Start → (optional warm-up) → Recording 1 → Report**

### 3.1 Public status vocabulary

The frontend must use only the **top-level `status`** returned by the API (not raw DB status). Possible values:

- `none` — no active session
- `recording_1_required` — warm-up step; user should record
- `report_generating` — recording 1 submitted; report is being generated (backend job running)
- `completed` — session done; report available

(Internal DB statuses still include `warm_up`, `task_block`, `completing_from_recording_1`, `completed`, etc.; they are mapped to the public vocabulary in `routes/homework.py` via `_public_status()`.)

### 3.2 Student endpoints (all under `/v2/homework`, auth: `Authorization: Bearer <supabase_access_token>`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/v2/homework/session/start` | Start a new session. Body `{}`. Returns `session_id`, `status: "warm_up"`, optional `warm_up_task`. |
| GET | `/v2/homework/session/status` | Get current session or none. Returns `has_active_session`, `session` (with public `status`), optional `tutor_feedback_deadline`, `tutor_feedback_message`, `tutor_video_url`, `tutor_video_description`. When **no active session**, may include **`assigned_exercises`**: `[ { id, title, video_url, description } ]` — display below Start homework button. |
| POST | `/v2/homework/session/<session_id>/abandon` | Delete the session; user has no active session afterward. |
| GET | `/v2/homework/session/<session_id>/warm-up-task` | Get warm-up task for the session (optional step). |
| POST | `/v2/homework/session/<session_id>/recording-upload-url` | Get a storage path and bucket for direct upload. Body `{ "recording": "1" }`. Only `"1"` is supported. If session is already `completing_from_recording_1` or `completed`, returns 200 with `already_submitted: true` (no 409). |
| POST | `/v2/homework/session/<session_id>/recording-1` | Submit recording 1. Either multipart with `audio` file (and optional `duration_seconds`), or JSON with `storage_path` and `duration_seconds`. Creates a minimal recording row, sets session to `task_block` then immediately to `completing_from_recording_1`, enqueues a background job, and returns `status: "report_generating"`, `recording_id`, `recording_1_processing: true`, `message`. |
| POST | `/v2/homework/session/<session_id>/complete-from-recording-1` | If the frontend is stuck (e.g. “Could not load questions”), complete the session from recording 1 only and return the report payload. Session must be `task_block` or `completing_from_recording_1`; recording 1 must be processed. |
| GET | `/v2/homework/session/<session_id>/report` | Get report for a **completed** session. See **§3.5 GET report payload** for full shape. |

**Removed (no longer exist):**  
`GET task-block`, `POST metric-answers`, `POST recording-2`, `GET questions`, `POST post-answers`.

### 3.3 Recording-1 background job

After `POST recording-1`, a **background job** (in-process thread in `services/recording_1_job.py`) runs:

1. Downloads audio from Supabase Storage, transcribes with Whisper.
2. Computes WPM, filler count, `performance_score_1`, `recording_1_performance_profile` (pace/filler level), selects a focus task (for future use; not shown in current flow).
3. Generates `context_short` (OpenAI).
4. Updates the recording row and session (`performance_score_1`, `context_short`, `recording_1_processing_status: "completed"`, etc.).
5. Because the session is already `completing_from_recording_1`, the job calls **`complete_session_recording_1_only()`** from `services/homework_completion.py`, which builds a **fixed-format report** (no LLM), appends to context long, creates a report row, marks the session **completed**, updates coaching memory (if table exists), and sends the lesson-complete email to the coach.

So the user sees: submit recording → `report_generating` → (poll status or refresh) → `completed` → GET report.

### 3.4 Report for “recording 1 only”

The report is built in `services/homework_completion.py` by `_build_report_recording_1_only()`: short transcript excerpt (max 2 sentences), metrics (pace, fillers, strength), and a fixed coach message (e.g. “Your coach has 24 hours to analyse…”). No LLM is used for this report. After completion, the backend also generates a **coach_insight** (two sentences from GPT-4o-mini) and stores it on the session for the report view.

### 3.5 GET report payload (frontend contract)

`GET /v2/homework/session/<session_id>/report` returns 200 with: `report_text`, `scores` (warmup, final, overall 0–100), `final_recording` (id, audio_url for playback), `performance_history` (chart), and optionally: **`recording`** (id, audio_url, **transcription_text** full transcript, **filler_words_count** { total, breakdown }, words_per_minute), **`context_short`**, **`coach_insight`** (two AI sentences: context+fillers, progress+relevancy), tutor_feedback_*.

**Frontend:** Show full transcription, filler words (breakdown + total), recording playback, keep chart, show coach_insight as 2-sentence coach block.

---

## 4. Admin (v2)

All admin routes are under **`/v2/admin/*`** (Blueprint `v2_bp` with prefix `/v2`). Admin identity: JWT must correspond to an email in `admin_users` with `is_active = true`; otherwise 403.

**Main areas:**

- **Students:** `GET/PUT` students, profile, overrides (`assigned_post_question_ids`, `assigned_next_task_ids`, etc.), speaker profile, warm-up tasks, focus tasks, post-recording questions. **Send assignment:** `POST .../send-assignment` with optional `video_url` and `video_description` (see `docs/FRONTEND-VIDEO-AND-DESCRIPTION.md`).
- **Sessions/reports:** `GET` student session, `GET/POST/PATCH` report.
- **Pools and config:** Tasks, post-recording questions pool, metric questions pool, metric definitions, metrics, warm-up pool, focus pool, exercises.

Details are in `.cursor/rules/architecture-taskmaster.mdc` (Admin section).

---

## 5. Legacy (v1) and other routes

- **Legacy:** `/session`, `/recordings`, `/questions`, `/admin` (e.g. `POST /admin/feedback`, `GET /admin/user/:userId/context`) still exist. The main product flow is **not** these; it is `/v2/homework`.
- **Auth:** `/auth` (e.g. login) — JWT from Supabase; `auth.py` supports HS256 and ES256/RS256 (JWKS).
- **User:** `/user` (user info).
- **Recordings v2:** `/v2/recordings` (other recording-related endpoints if any).

---

## 6. Auth

- **Student and admin v2:** `Authorization: Bearer <supabase_access_token>`.
- **Validation:** JWT verified in `auth.py` (HS256 or JWKS for Supabase). `require_auth` decorator sets `request.user_id`.
- **Frontend:** After login, frontend must call `supabase.auth.setSession({ access_token, refresh_token })` so the backend and frontend stay in sync.

---

## 7. Database and storage

- **DB:** All access via `services/db.py` (Supabase client). No direct SQL in route handlers.
- **Tables (v2):** Defined in `migrations/v2_all_in_one.sql` plus later migrations (e.g. `v2_student_coaching_memory`, `recording_1_performance_profile`, `add_tutor_feedback_deadline.sql`, `add_tutor_feedback_sent_at.sql`, `add_tutor_video_url.sql`, `add_tutor_video_description.sql`, `add_skip_metric_and_post_questions_overrides.sql`, etc.). Order and checklist: see architecture rule and `docs/HOMEWORK-AND-PERFORMANCE.md`.
- **Storage:** Bucket `audio_recordings` in Supabase. Backend uploads/downloads and creates signed URLs; path pattern for homework: `{user_id}/{session_id}/{uuid}.webm`.

---

## 8. Services (key files)

| Service | Role |
|---------|------|
| `services/db.py` | All Supabase access: sessions, recordings, overrides, tasks, reports, coaching memory, etc. |
| `services/openai_service.py` | Whisper transcription, `generate_context_short`, and (when full flow existed) `generate_final_task`, `generate_final_report`. |
| `services/email_service.py` | Resend: lesson-complete to admin, send-assignment to student (with optional video link/description). |
| `services/homework_completion.py` | `complete_session_recording_1_only()`: report from recording 1 only, mark completed, email, coaching memory. |
| `services/recording_1_job.py` | In-process queue and worker: transcribe, score, context, focus task; then call `complete_session_recording_1_only` when status is `completing_from_recording_1`. |
| `services/metrics_v2.py` | `compute_performance_score_1`, `build_recording_1_performance_profile`, etc. |
| `services/v2_flow_service.py` | Focus task selection (e.g. `select_focus_task_for_performance_score_1`); used by recording-1 job. |
| `services/video_url_validation.py` | Validation of admin-provided video URL/description. |

---

## 9. Frontend / BFF expectations

- **Paths:** Frontend does **not** use `v2` in its own paths. It calls **`/api/homework/*`** and **`/api/admin/*`**. A Next.js BFF proxies these to the backend (`BASE_URL/v2/homework/*`, `BASE_URL/v2/admin/*`).
- **Reference:** BFF route examples live in **`docs/homework-bff-routes/`** (and admin in `docs/frontend-admin-panel/`). Frontend must call e.g. **`POST /api/homework/session/start`** (not `/api/homework/start`).
- **Recording-upload-url:** Backend accepts only `recording: "1"`. If the session is already past recording 1 (`completing_from_recording_1` or `completed`), backend returns **200** with `already_submitted: true` and `storage_path: null` so the frontend does not get 409; frontend should then refetch status and show report state instead of uploading again.
- **No recording-metrics-chunk:** Backend does not expose a real-time metrics chunk endpoint; any “glow” or wheel is client-side only. BFF may expose a no-op 204 for legacy clients.

---

## 10. What was temporarily removed and how to restore

**Removed:**

- Steps 2–4: metric questions (GET task-block, POST metric-answers), final task + recording 2 (POST recording-2), post-questions (GET questions, POST post-answers).
- Helpers and constants used only by those steps (e.g. `_complete_homework_session`, `_build_task_block_for_session`, `_is_recording_1_ready`, `_recording_1_processing_failed`, `DEFAULT_FINAL_TASK_WHEN_SKIP_METRICS`).
- Recording-upload-url for `recording: "2"`; only `"1"` is supported now.

**Restore:**

- **`docs/BRING_IT_BACK.md`** — step-by-step: restore from git history (Option A) or re-add code from **`docs/TEMPORARY-REMOVED-STEPS-2-3-4-BACKUP.md`** (Option B).
- After restoring, update the homework module docstring and `.cursor/rules/architecture-taskmaster.mdc` to describe the full flow again.

---

## 11. Conventions and “when changing”

- **Config:** Only in `config.py`; env via `.env` / Railway.
- **DB:** Only via `services/db.py`.
- **Homework flow:** Implemented in `routes/homework.py`; completion and report-from-recording-1 in `services/homework_completion.py` and `services/recording_1_job.py`.
- **Admin (v2):** `routes/v2_routes.py` and `services/db.py` (students, overrides, pools, etc.).
- **Single source of truth:** `.cursor/rules/architecture-taskmaster.mdc` is the main architecture and API reference; this document is a detailed **state** snapshot.

---

## 12. Summary

- **App:** Flask backend for a coaching/homework product; student flow is **start → recording 1 → report** (steps 2–4 removed).
- **Stack:** Flask, Supabase (DB + auth + storage), OpenAI, Resend; frontend separate (Next.js), talking via BFF to `/v2/homework` and `/v2/admin`.
- **Current student journey:** Start session → optional warm-up → get upload URL → upload recording 1 → backend returns `report_generating` → job generates report and marks session completed → user sees report via GET report; upload-url returns 200 with `already_submitted` if called again after submit.
- **Admin:** Full v2 admin under `/v2/admin` (students, overrides, tasks, questions, send-assignment with optional video, etc.).
- **Restore full flow:** Use `docs/BRING_IT_BACK.md` and `docs/TEMPORARY-REMOVED-STEPS-2-3-4-BACKUP.md`.
