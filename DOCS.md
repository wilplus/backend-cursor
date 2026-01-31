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

## 5. Pre-Recording Questionnaire

- **Endpoint:** `POST /session/start`. Optional body: `{ "questionnaire": { "mood": "positive"|"negative", "readiness": 1-10, "inspiration_needed": true|false } }`.
- **Cursor:** `((readiness - 1) / 9) * mood_multiplier` (1.0 positive, 0.7 negative), range 0–1.
- **Mode:** `inspiration_needed === true` → `"guided"`, else `"open"`.
- **Questions:** From `question_service.py` (COMMANDS by tier); 3 questions per session. Production uses OpenAI for generation; dev can use template fallback.
- **Session columns:** `mood`, `readiness`, `inspiration_needed`, `cursor`, `mode` (see `supabase-schema-complete.sql`). No questionnaire → defaults cursor 0.5, mode `"open"`.

---

## 6. Frontend Fixes (Reference)

- **Admin feedback TypeScript:** Use `body: JSON.stringify(body)` and `Content-Type: application/json` when proxying to backend; do not pass a plain object as `body`.
- **Post-question IDs:** Backend returns real UUIDs in `post_questions[].id`. Submit answers with those UUIDs as `question_id`; no change to response shape except IDs are UUIDs.

---

## Quick reference

- **Schema:** `supabase-schema-complete.sql`
- **Architecture:** `ARCHITECTURE.md`
- **Taskmaster (AI):** `.cursor/rules/architecture-taskmaster.mdc` → read ARCHITECTURE.md first, then this file for implementation/ops details.
