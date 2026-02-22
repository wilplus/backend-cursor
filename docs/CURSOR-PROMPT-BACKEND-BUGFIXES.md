# Backend Cursor Prompt: willab (willpower lab) — Five Bug Fixes

You are a senior backend engineer maintaining **willab** (willpower lab), a speech coaching application with a **Flask** backend deployed on Railway. The app uses Supabase (auth, storage, DB), OpenAI (transcription, report generation), and Resend (emails). Your task is to debug and fix five specific issues without breaking the 5-step homework flow or the session state machine.

**Frontend pairing:** For issue 5 (video), the frontend implements admin UI (paste/upload video URL, send with assignment) and student UI (show video on homework page). Use **`docs/CURSOR-PROMPT-FRONTEND-BUGFIXES.md`** for the frontend team; ensure GET session/status and send-assignment contract match that prompt.

**Codebase note:** In this repo there is **no** `recording_2_job.py`. Recording-2 is processed **synchronously** in `routes/homework.py` (transcribe → `compute_metrics_v2` → store). For issue 1, look in `routes/homework.py` (POST recording-2 and POST post-answers) and `services/metrics_v2.py`.

---

## Architecture Context

- **Framework:** Flask. Routes: `/v2/homework/*` (student flow), `/v2/admin/*` (admin).
- **Key modules:** `routes/homework.py`, `routes/v2_routes.py`, `services/db.py`, `services/openai_service.py`, `services/email_service.py`, `services/metrics_v2.py`, `services/recording_1_job.py`. Migrations: `v2_all_in_one.sql` + coaching migrations.
- **Homework flow (do not break):** Step 0 (no session) → 1 (warm-up recording) → 2 (metric answers) → 3 (final recording) → 4 (post-questions) → 5 (report). Status values: `warm_up`, `task_block`, `final_task_ready`, `post_questions`, `completed`.
- **Scoring:** `performance_score_1` (recording 1 + 3 metrics), `performance_score_2` (recording 2 + 5 metrics), `performance_score_end` (formula). Report is generated in **POST post-answers**.
- **Email:** Resend API; triggered by **POST /v2/admin/students/<id>/send-assignment**.

---

## Critical Constraints

1. **Do not break the 5-step homework flow or session state machine.** All status transitions and API contracts must remain valid.
2. **Do not change request/response shapes** for existing endpoints without coordinating with the frontend (paths, field names, status values).
3. Align with taskmaster/docs: `docs/app-description.md`, `docs/HOMEWORK-FLOW-0-TO-5-CHECKLIST.md` (or equivalent in your repo).

---

## Issue 1: Performance score 2 always shows 30%

**Objective:** Fix backend scoring so `performance_score_2` reflects the actual recording-2 analysis, not a hardcoded or wrong default.

**Investigation steps:**

1. **Locate where `performance_score_2` is set:**
   - Search for `performance_score_2` in the codebase (e.g. `services/metrics_v2.py`, or the handler that runs after recording-2 upload — in this repo, **POST recording-2** in `routes/homework.py`).
   - Check for any fallback or default such as `0.3` or `30` (percent) when analysis fails or is missing.

2. **Check the scoring formula:**
   - Recording 2 is typically scored on 5 metrics (e.g. clarity, pace, filler words, time in range, etc.). Verify:
     - Weights or aggregation (e.g. average, weighted average).
     - That the result is stored as a 0–1 value (frontend displays `score * 100` as percent).
   - Ensure no branch (e.g. "analysis pending" or "error") overwrites the computed score with a fixed 0.3.

3. **Synchronous path (this repo):**
   - Recording-2 is processed in-request in `routes/homework.py`. Confirm the handler writes the computed score from `compute_metrics_v2` (or equivalent) to the session/recording row and that the POST recording-2 response and GET status later return it. Also check **POST post-answers**, which may recompute and update `performance_score_2` — ensure that path does not force 0.3.

**Expected behavior:** After recording 2 is processed, `performance_score_2` (and `performance_score_end` if it depends on it) reflects the real analysis (e.g. 0.75 → 75% in the UI), not always 30%.

**Fix:** Remove or replace any hardcoded 0.3/30; ensure the scoring pipeline writes the computed value; add a clear comment where the final `performance_score_2` is assigned.

---

## Issue 2: Report description should only show filler word count and time in good range

**Objective:** Simplify the report text generated after POST post-answers so it contains **only**:
- Filler word count (e.g. "12 filler words detected").
- Time in good vocal range (e.g. "Time in good vocal range: 45 seconds (75% of recording).")

**Investigation steps:**

1. **Locate report generation:**
   - Search for `generate_final_report`, `context_long`, or where the report text is built (likely `openai_service.py` or a dedicated report module).
   - Identify the OpenAI (or other) prompt that generates the narrative. The prompt currently likely asks for a longer description; it must be changed to request only the two items above.

2. **Data available for the report:**
   - Filler count: should come from transcription/analysis (e.g. filler word detection step).
   - Time in good range: should come from recording-2 metrics (e.g. time spent in target dB range). If this metric is not yet computed, add it in the metrics pipeline and pass it into the report generator; if not feasible in this sprint, the backend can return a placeholder line (e.g. "Time in good vocal range: not yet available") and the frontend will display it.

3. **Storage:**
   - Report text is stored as `context_long` (session) or equivalent and returned as `report_text` in POST post-answers and GET report. Ensure the simplified text is written to the same field so the frontend does not need to change.

**Expected behavior:** Step 5 report section shows something like: *"12 filler words detected. Time in good vocal range: 45 seconds (75% of recording)."* No extra narrative unless product explicitly asks for it later. If time-in-range is unavailable: *"12 filler words detected. Time in good vocal range: not yet tracked."*

**Fix:** Rewrite the report-generation prompt (and any aggregation logic) to output only these two items in a short, consistent format. Do not rename or remove `report_text` in the API response.

---

## Issue 3: Locate where "context" is stored and used

**Objective:** Document the data flow for "context" so the team knows what is stored where and what is shown to students vs admins.

**Investigation steps:**

1. **Search the codebase for:**
   - `context_short` — typically session-level (e.g. after recording-1 analysis); may be used for metric generation or internal state.
   - `context_long` — typically the full report text (step 5); returned as `report_text` to the frontend.
   - `coach_notes` — usually on `v2_speaker_profiles` (or similar); editable by admin, not shown to students in the homework flow.
   - Any OpenAI system prompt or payload that sends "context" (e.g. for report generation or metric answers).

2. **Document:**
   - Table/column where each is stored.
   - Which API endpoints read/write them (e.g. GET session/status, POST post-answers, GET report, admin speaker profile).
   - Which roles see which field (student sees `report_text`/`context_long` on step 5; admin may see `coach_notes` and report preview).

**Expected behavior:** A short internal doc or code comments that state, for example: "context_short = session summary for metrics; context_long = report text (exposed as report_text); coach_notes = admin-only speaker notes."

**Fix:** Add comments in the relevant services (e.g. `db.py`, `openai_service.py`) and optionally a small doc (e.g. `docs/CONTEXT-FIELDS.md` or `docs/CONTEXT_FIELDS.md`) so future changes don't confuse these fields.

---

## Issue 4: Fix homework email design

**Objective:** Improve the layout and styling of the email sent when an admin clicks "Send Homework" (POST /v2/admin/students/<id>/send-assignment).

**Investigation steps:**

1. **Locate the email template:**
   - Find where the assignment email is built and sent (e.g. `email_service.send_assignment_email` or `send_assignment_to_student` in `services/email_service.py`).
   - Check whether the template is HTML (Resend supports HTML), plain text, or both.

2. **Current issues:**
   - Identify what's wrong (e.g. broken layout, missing branding, link not prominent, poor mobile display).

3. **Link to app:**
   - The "Start Homework" (or similar) link must point to the frontend (e.g. `FRONTEND_URL` or `https://app.willonski.com`). Verify the env var (e.g. `FRONTEND_URL`) is set in production and used in the template. Do not change the path the frontend expects (e.g. `/dashboard`).

**Expected behavior:** Email looks professional (clear CTA, readable font, optional logo/branding), and the link correctly opens the app (e.g. `{FRONTEND_URL}/dashboard`).

**Fix:** Update the template (HTML/text) in `email_service.py` (or wherever the assignment email is built). Use inline CSS if needed for email clients. After deployment, test by sending homework to a test student and checking in Gmail/Outlook.

---

## Issue 5: Add admin video upload/URL feature (backend part)

**Objective:** Allow admins to attach a **video URL** to an assignment. Backend must: accept and store the URL, and include it in the assignment email and in session/status so the student can see the video on the homework page.

**Investigation steps:**

1. **Storage decision:**
   - **Option A:** Store only a URL (admin pastes link to YouTube, Loom, Supabase Storage, etc.). No file upload in backend.
   - **Option B:** Backend accepts file upload, stores in Supabase Storage, returns a public or signed URL; store that URL.
   - For minimal change, Option A (URL only) is often enough: add a column e.g. `v2_sessions.tutor_video_url` or `v2_student_assignments.video_url` (or per-student assignment table if you have one). If the assignment is per-student and not per-session, store the latest assignment video URL and return it when the student has an active session or is on step 0.

2. **API contract:**
   - **POST /v2/admin/students/<id>/send-assignment**
     - Extend request body to accept optional `video_url` (string). Example: `{ "video_url": "https://..." }`.
     - Backend stores `video_url` (e.g. in assignment row or a new column). When creating or updating the "current assignment" for that student, persist this URL so it can be returned with GET session/status or equivalent. If sessions are created on **session/start**, store a "pending video for next session" per user and copy it into `v2_sessions.tutor_video_url` when the student starts a new session.
   - **GET /v2/homework/session/status** (or the endpoint that returns current session/assignment for the student)
     - Include `tutor_video_url` (or `video_url`) in the session object when the backend has one for the current student/session. Frontend will show it on step 0 or step 5.

3. **Email:**
   - In the assignment email template, if `video_url` is present, add a line or button: "Watch a message from your coach: {url}" (or similar). Use the same URL; no need to re-upload.

4. **Migrations:**
   - Add the new column(s) (e.g. `tutor_video_url` on the table that backs "current assignment" or session). If using "pending video for next session", add a place to store it (e.g. user overrides table or small pending-video table). Run migration in dev and production.

**Expected behavior:** Admin can send homework with an optional video URL. Student receives the email with the link and sees the video on the homework page (step 0 or 5) when the backend includes it in the status/report response.

**Fix:** Implement storage, POST send-assignment body handling, GET status (or report) including `tutor_video_url`, and email template update. Coordinate with frontend so they send `video_url` in the POST body and render `tutor_video_url` from the response.

---

## Testing Checklist (Backend)

- [ ] **Score 2:** Complete a full flow including recording 2; confirm `performance_score_2` in DB and API response is not stuck at 0.3/30%.
- [ ] **Report text:** POST post-answers returns `report_text` with only filler count and time-in-range (or placeholder); GET report returns the same.
- [ ] **Context:** Comments or doc clarify `context_short`, `context_long`, `coach_notes` and where they are used.
- [ ] **Email:** Send homework to a test account; open email; verify layout and that "Start Homework" link goes to the correct frontend URL.
- [ ] **Video URL:** POST send-assignment with `video_url`; verify it is stored; verify GET session/status (or equivalent) returns it; verify email contains the link. Frontend will verify student-facing display.

Do not change status values, step semantics, or existing API paths/field names used by the frontend without aligning with the frontend prompt and contracts.
