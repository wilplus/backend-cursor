# Willab / Speech Coaching Backend — Architecture

**Purpose:** Source of truth for initial architecture. Use this so the AI (and humans) don't forget design decisions.

---

## Stack

- **Backend:** Flask (Python), deployed on Railway
- **Database & Auth:** Supabase (PostgreSQL, auth.users, Storage)
- **AI:** OpenAI (Whisper transcription, GPT-4o-mini for classification & coaching reports)
- **Email:** Resend
- **Frontend:** Separate app (e.g. app.willonski.com); `FRONTEND_URL` in config

---

## Project Layout

```
backend-cursor/
├── app.py              # Flask app, blueprints, health
├── auth.py             # JWT verification (Supabase HS256/ES256), require_auth
├── config.py           # ENV, Supabase, OpenAI, Resend, CORS, FRONTEND_URL
├── routes/
│   ├── auth.py         # signup, login, reset-password
│   ├── session.py      # start, abandon, status
│   ├── questions.py    # pre/post answers, report generation, performance scoring
│   ├── recordings.py   # upload, get, audio-url
│   ├── user.py         # profile, recordings
│   └── admin.py        # feedback, user context, recordings list
├── services/
│   ├── db.py           # Supabase client; all DB/storage access
│   ├── openai_service.py   # Whisper, classify_speech, generate_final_report
│   ├── question_service.py # Pre: COMMANDS, cursor, mode, select_commands, generate_question_from_command
│   ├── post_questions_service.py # Post: POST_QUESTIONS_POOL, select_post_question_set, generate_post_questions_from_set
│   ├── scoring_service.py  # Performance score, bonuses, final KPI
│   └── email_service.py    # Admin notification (Resend), feedback link
└── utils/
    └── metrics.py      # count_fillers, compute_wpm, compute_trend_sentence
```

---

## Core Flows

### 1. Session → Recording → Report

1. **Session start** (`POST /session/start`): Optional questionnaire → cursor, mode → pre_questions (from code or DB).
2. **Pre-answers** (if not skipped): Stored in `pre_recording_answers` + `pre_recording_questions`.
3. **Recording upload** (`POST /recordings/upload`): Audio → Storage, Whisper → transcript, metrics, classification; create `recordings` row; select post-question set from **code** (`POST_QUESTIONS_POOL`), create rows in `post_recording_questions`, return post_questions (with real UUIDs).
4. **Post-answers** (`POST /questions/post-answers`): Save answers, compute performance score, **fetch admin context**, generate final report (with admin notes + progress context), save coaching_report + trend_sentence, send admin email with feedback link.

### 2. Admin Feedback

- **Store:** `POST /admin/feedback` → `professional_notes`, `professional_notes_report_tech`, `professional_notes_specific_questions`.
- **Use:** Before `generate_final_report`, call `db.get_user_admin_context(user_id)` and pass into OpenAI prompt (general_notes, custom_instructions, max_words, specific_questions).
- **Progress:** `db.get_user_recording_history()` used to build progress context (trends, averages) in the same prompt.

### 3. Auth

- JWT from Supabase; `auth.py` supports HS256 (JWT secret) and ES256/RS256 (JWKS).
- Admin: `admin_users` table (email + is_active); admin routes use `require_admin` (email from token).

---

## Database (Supabase)

- **Auth:** `auth.users` (Supabase managed).
- **Sessions:** `recording_sessions` (status, cursor, mode, pre_questions_completed, recording_id, etc.).
- **Recordings:** `recordings` (audio_url, storage_path, transcription_text, coaching_report, trend_sentence, metrics, classification).
- **Questions:** `pre_recording_questions`, `post_recording_questions` (instances per session/recording); pre default list and post **pool** are still in **code** (see DOCS.md).
- **Scores:** `performance_scores` (per recording), `post_recording_answers`, `pre_recording_answers`.
- **Admin:** `professional_notes`, `professional_notes_report_tech`, `professional_notes_specific_questions`, `admin_users`.
- **Storage:** Supabase Storage bucket `audio_recordings`; use signed URLs for playback.

---

## Where Questions Live (Initial vs Intended)

- **Pre:** Command definitions → `services/question_service.py` (`COMMANDS`). Default pre questions → DB `pre_recording_questions` (seed in supabase-schema-complete.sql). Personalized pre questions are generated from COMMANDS in code.
- **Post:** Question **sets** (20 sets × 3 questions) → `services/post_questions_service.py` (`POST_QUESTIONS_POOL`). Per-recording question **instances** → DB `post_recording_questions` (created at upload).
- **Intended:** Move command definitions and question-set definitions into the DB so they can be updated after each session and when admins add professional notes (see DOCS.md).

---

## Key Conventions

- **Config:** All env in `config.py` (no raw `os.getenv` in business logic).
- **DB access:** Only via `services/db.py` (Supabase client).
- **Errors:** Use `jsonify({"code": "...", "error": "..."})` and appropriate HTTP status; Sentry for exceptions.
- **IDs:** Post-question IDs must be real UUIDs from `post_recording_questions` (no temporary ids like "set-2-q1" in API).
- **Email link:** `{FRONTEND_URL}/recordings/{recording_id}/feedback?user_id={user_id}` (e.g. app.willonski.com or localhost:3000).

---

## Important Files to Touch When Changing Behavior

- **Pre-questions / cursor:** `question_service.py`, `routes/session.py`, `db.get_pre_questions`, `pre_recording_questions` table.
- **Post-questions:** `post_questions_service.py`, `routes/recordings.py` (upload), `db.create_post_question`, `post_recording_questions` table.
- **Report content:** `openai_service.generate_final_report`, `db.get_user_admin_context`, `db.get_user_recording_history`.
- **Admin:** `routes/admin.py`, `professional_notes*` tables, `email_service` (feedback link).

---

## References

- Full schema: `supabase-schema-complete.sql`
- Implementation, schema, admin, email, questionnaire, frontend: **DOCS.md**
