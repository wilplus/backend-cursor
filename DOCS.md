# Implementation & Operations Guide

Single reference for setup, schema, admin flows, and frontend integration. For architecture and conventions, see **ARCHITECTURE.md**.

---

## 1. Questions in Code vs Database

| What | In Code | In Database |
|------|--------|-------------|
| **Pre-recording commands** (20 commands, 5 tiers) | ✅ `question_service.py` → `COMMANDS` | ❌ |
| **Pre-recording default questions** (3 questions) | ❌ | ✅ `pre_recording_questions` (seed only) |
| **Post-recording question sets** (20 sets × 3 questions) | ✅ `post_questions_service.py` → `POST_QUESTIONS_POOL` | ❌ |
| **Post-recording question instances** (per recording) | ❌ | ✅ `post_recording_questions` (rows created at upload) |

**Definitions** (commands, question sets) are in **code**. **Instances** (which questions were asked for a session/recording) are in the **database**.

**Intended:** Move command and question-set definitions into the DB so admins can edit after sessions or professional notes. That would require: DB tables (e.g. `pre_question_commands`, `post_question_sets` / `post_question_set_items`), one-time seed from current code, backend reading from DB with code fallback, and optional admin API to update tables.

---

## 2. Supabase Schema & Storage

### Recordings table

Required columns (ensure via `supabase-schema-complete.sql` or):

- **NOT NULL:** `id` (UUID), `user_id` (UUID), `audio_url` (TEXT), `duration` (INTEGER, seconds).
- **Optional but used:** `session_id`, `transcription_text`, `duration_seconds`, `words_per_minute`, `filler_words_count` (JSONB), `classification`, `confidence`, `storage_path`, `coaching_report`, `trend_sentence`, `created_at`, `updated_at`.

`duration` is INTEGER; `duration_seconds` is NUMERIC. `coaching_report` and `trend_sentence` are set when post-answers are submitted.

### Storage bucket

- **Bucket name:** `audio_recordings`.
- **Create:** Supabase Dashboard → Storage → New bucket → Name: `audio_recordings`, Public: ✅ (or use private bucket + signed URLs).
- **404 "Bucket not found"** → Create the bucket; backend uses signed URLs for playback.

---

## 3. Admin Feedback

### Backend (ready)

- **POST /admin/feedback** — Save general notes, custom instructions, max_words, specific_questions. Body: `user_id` (required), optional `recording_id`, `general_notes`, `custom_instructions`, `max_words`, `specific_questions[]`.
- **GET /admin/user/:userId/context** — Get admin notes for a user.
- **GET /admin/recordings** — List recordings; query params: `limit`, `offset`, `needs_feedback`.

Admin = JWT email in `admin_users` with `is_active = true`. Create admin: `INSERT INTO admin_users (email, role, is_active) VALUES ('your@email.com', 'super_admin', true);`

### Testing

1. Add your email to `admin_users`. 2. Get JWT (e.g. from frontend session). 3. `POST /admin/feedback` with `user_id`, `general_notes`, `custom_instructions`. 4. `GET /admin/user/:userId/context` to verify. 5. Upload recording → submit post-answers → check `coaching_report` includes admin context. Non-admin token → 403. Missing `user_id` → 400.

### Frontend integration

- **Feedback page route:** `{FRONTEND_URL}/recordings/:recordingId/feedback?user_id=:userId` (same URL as in admin email link).
- **API:** Send `body: JSON.stringify(data)` and `Content-Type: application/json` when calling backend (fetch expects body as string). TypeScript: use `body: JSON.stringify(body)` to avoid `BodyInit` type errors.
- **Response:** 200 → `{ "status": "success", "message": "Admin feedback saved successfully" }`. Errors: 400 INVALID_INPUT, 403 FORBIDDEN, 500.

---

## 4. Email & Feedback Link

- **Config:** `FRONTEND_URL` in `config.py` (e.g. `https://app.willonski.com` or `http://localhost:3000`). Set in Railway/env.
- **Link in email:** `{FRONTEND_URL}/recordings/{recording_id}/feedback?user_id={user_id}`.
- **Behaviour:** HTML email with “Provide Feedback” button; backend uses `FRONTEND_URL` only. Ensure frontend implements the feedback page at that path.

---

## 5. Auth & "Invalid Refresh Token" after login

**Error:** `AuthApiError: Invalid Refresh Token: Refresh Token Not Found` (400 on `token`).

This comes from **Supabase Auth** in the browser: something is trying to refresh the session with a refresh token that Supabase doesn’t have (stale, wrong project, or never set).

**Common cause:** The frontend calls backend **POST /auth/login**, gets `access_token` and `refresh_token`, but the **Supabase JS client** still has an old refresh token in its storage (e.g. localStorage). When the client refreshes the session (on load or later), it uses that old token → 400.

**Fix (frontend):**

1. **Set the Supabase session from the backend login response**  
   After a successful `POST /auth/login`, call:
   ```ts
   const { access_token, refresh_token } = res.data;
   await supabase.auth.setSession({ access_token, refresh_token });
   ```
   so the client’s stored session matches the tokens you just received.

2. **Optional: clear stale state before login**  
   Before calling backend login (or on 400 from refresh), sign out and clear storage:
   ```ts
   await supabase.auth.signOut({ scope: 'local' });
   ```
   then call `POST /auth/login` and then `setSession` as above.

3. **Same project**  
   Ensure the frontend uses the same **SUPABASE_URL** and **anon key** as the backend (same Supabase project). A token from project A will be “not found” on project B.

**Backend:** `POST /auth/login` returns `{ access_token, refresh_token, expires_in, user }`. No change required on the backend for this error.

---

## 6. Pre-Recording Questionnaire

- **Endpoint:** `POST /session/start`. Optional body: `{ "questionnaire": { "mood": "positive"|"negative", "readiness": 1-10, "inspiration_needed": true|false } }`.
- **Cursor:** `((readiness - 1) / 9) * mood_multiplier` (1.0 positive, 0.7 negative), range 0–1.
- **Mode:** `inspiration_needed === true` → `"guided"`, else `"open"`.
- **Questions:** From `question_service.py` (COMMANDS by tier); 3 questions per session. Production uses OpenAI for generation; dev can use template fallback.
- **Session columns:** `mood`, `readiness`, `inspiration_needed`, `cursor`, `mode` (see `supabase-schema-complete.sql`). No questionnaire → defaults cursor 0.5, mode `"open"`.

---

## 7. Frontend Fixes (Reference)

- **Admin feedback TypeScript:** Use `body: JSON.stringify(body)` and `Content-Type: application/json` when proxying to backend; do not pass a plain object as `body`.
- **Post-question IDs:** Backend returns real UUIDs in `post_questions[].id`. Submit answers with those UUIDs as `question_id`; no change to response shape except IDs are UUIDs.

---

## v1 Planned session flow (optional)

- **Migration:** Run `migrations/v1_planned_session.sql` in Supabase SQL Editor after `supabase-schema-complete.sql`. Adds: theme/planning columns on `recording_sessions`, `recordings.command_option_id`, `session_command_options`, `content_exposures`, `admin_session_overrides`, pre-question template columns, `performance_scores.self_rating_score`, and seeds 21 theme pre-question templates.
- **Full v1 schema (single script):** `docs/archive/supabase-full-schema-v1.sql` or `supabase-schema-full.sql` — idempotent, includes `recordings.command_option_id` for POST /recordings/upload. Use so schema matches the v1 upload contract.
- **Flow:** `POST /session/start` returns theme + 1 planned pre-question + 3 command options (A/B/C) + **`recommended_command_option_id`** (A|B|C). Use the recommended one for recording without showing a picker. Upload requires form field `command_option_id` (A|B|C). Backend stores it on each recording row. Post-set is chosen at upload by theme + anti-repeat. Q1 scale answer is stored as `performance_scores.self_rating_score`.
- **Rollout:** `recording_sessions.mode` is canonical; mirror writes to `structure`; read with `COALESCE(mode, structure)`.

---

## 3-step flow (new structure)

**Step 1: Pre-questions**  
1.1 Do you feel more like: [mood/energy]  
1.2 How ready is your body and mind to present? [readiness]  
1.3 Theme — default “choose a theme for me” (system picks); remove “optional” in UI  
1.4 Do you want to be guided [mode]  
~~1.5 How are you feeling today~~ — **removed** (backend does not plan this question)  
~~1.6 Choose your recording prompt~~ — **removed** (system uses recommended command; no A/B/C picker)

**Step 2: Command & recording**  
- Backend returns `recommended_command_option_id` (e.g. `"A"`). Frontend uses that for the recording step and sends it as `command_option_id` on upload. Do not show “choose A/B/C”.

**Step 3: Post-questions**  
3.1, 3.2, 3.3 — backend returns `post_questions` after upload; frontend renders them.

**Backend support:**  
- `POST /session/start` includes `recommended_command_option_id` (primary command).  
- Pre-question “How are you feeling today?” is excluded from planning.  
- Theme default: system chooses when user does not send `theme_code` (already supported).

**Gaps / frontend:**  
- Step labels 1.1–1.4 and 3.1–3.3: frontend must map API (theme, mode, pre_questions, post_questions) to these steps.  
- “Optional” copy for theme: remove in frontend; default = “choose a theme for me”.  
- Post-question content (3.1, 3.2, 3.3) comes from backend `post_questions` after upload; no backend gap.

**Report:** The coaching report references or summarizes the first set of questions (pre-recording answers) that determined the command choice when relevant.

**Post-questions (summary):** If the command was newly tested (user has selected this intent 0 or 1 time before), 50% of the time the backend adds an extra post-question: "Did you find this recording prompt useful?" (binary). Commands are rotated (anti-repeat at session start) so the 3rd time a new command is offered; after that, 50% of the time when the command is newly tested we ask if the prompt was good.

---

## Cleanup: incomplete sessions (not concluded with a report)

Incomplete flows (sessions that never got a report) are deleted after **10 days**, along with their recordings, pre/post answers, command options, and exposures.

**What gets deleted:**  
- `recording_sessions` where `status != 'completed'` and `created_at` is older than N days  
- Related: `recordings`, `pre_recording_answers`, `post_recording_answers`, `session_command_options`, `content_exposures`, `performance_scores` (via cascade)

**How to run (production):**  
- **Cron (recommended):** Daily run with `days=10`, e.g. `python3 run_cleanup_incomplete_sessions.py --days 10`  
- **Admin API:** `POST /admin/cleanup-incomplete-sessions?days=10` (requires admin auth)

**How to test without waiting 10 days:**  
1. **Dry-run (no delete):** See what would be deleted after 10 days:  
   `python3 run_cleanup_incomplete_sessions.py --days 10 --dry-run`  
2. **Short cutoff for testing:** Use a small `days` so “old” = e.g. 1 hour:  
   - Dry-run: `python3 run_cleanup_incomplete_sessions.py --days 0.04 --dry-run` (≈1 hour)  
   - Actually delete: `python3 run_cleanup_incomplete_sessions.py --days 0.04`  
3. **Admin API:**  
   - Dry-run: `POST /admin/cleanup-incomplete-sessions?days=0.04&dry_run=true`  
   - Delete: `POST /admin/cleanup-incomplete-sessions?days=0.04`  

Response includes `deleted_count` and `deleted_session_ids` (or what would be deleted when `dry_run=true`).

---

## Quick reference

- **Schema:** `supabase-schema-complete.sql` (base) or `supabase-schema-full.sql` / `docs/archive/supabase-full-schema-v1.sql` (full v1, includes `recordings.command_option_id`).
- **v1 migration:** `migrations/v1_planned_session.sql`
- **Architecture:** `ARCHITECTURE.md`
- **Taskmaster (AI):** `.cursor/rules/architecture-taskmaster.mdc` → read ARCHITECTURE.md first, then this file for implementation/ops details.
