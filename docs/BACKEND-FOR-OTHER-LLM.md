# Backend overview for another LLM

This document explains how the **Willab / Speech Coaching backend** works so a frontend or another service (e.g. another LLM) can integrate with it correctly. **Do not change backend code based on this file alone**—treat it as the source of truth for *how the backend behaves*, not as a spec for changing it unless the product owner asks.

---

## 1. Stack and entrypoints

- **Framework:** Flask (Python). Single app in `app.py`; routes are in blueprints under `routes/`.
- **Database & auth:** Supabase (PostgreSQL, `auth.users`, Storage). All DB access goes through `services/db.py` (Supabase client created with `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`).
- **AI:** OpenAI (Whisper for transcription; GPT-4o-mini for speech classification and coaching report generation). Used in `services/openai_service.py`.
- **Email:** Resend (admin notification emails with feedback link). `services/email_service.py`.
- **Config:** `config.py` reads from env (no raw `os.getenv` in business logic). Important: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET`, `OPENAI_API_KEY`, `FRONTEND_URL`, `CORS_ORIGINS`.

**Base URL:** All API routes are under the same origin (e.g. `https://your-backend.up.railway.app`). No version prefix (e.g. no `/v1`).

**Blueprints (prefixes):**

- `/auth` — signup, login, reset-password
- `/session` — start, abandon, status
- `/questions` — pre-answers, post-answers (and report trigger)
- `/recordings` — upload, get one, get audio URL
- `/user` — profile, my recordings
- `/admin` — feedback save, user context, recordings list, cleanup

**Health:** `GET /health` → `{"status": "ok"}`. `GET /health/jwks` checks JWKS connectivity for auth.

---

## 2. Authentication

- **Mechanism:** Supabase JWT in `Authorization: Bearer <access_token>`.
- **Verification:** Done in `auth.py`. Supports:
  - **HS256:** verified with `SUPABASE_JWT_SECRET`.
  - **ES256/RS256:** verified with Supabase JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`).
- **Token payload:** Must have `audience="authenticated"` and `issuer={SUPABASE_URL}/auth/v1`. After verification, the backend attaches:
  - `request.user_id` = `payload["sub"]` (Supabase auth user UUID).
  - `request.token_payload` = full payload (e.g. for admin check, `token_payload.get("email")`).
- **Protected routes:** Use the `@require_auth` decorator. Missing or invalid token → 401 with `{"code": "UNAUTHORIZED", "error": "..."}`.
- **Admin routes:** Use `@require_admin`. That implies `@require_auth`; then the backend checks that the token’s **email** exists in the `admin_users` table with `is_active = true`. If not → 403.

So: **every protected API expects a valid Supabase access token**. The frontend must send the token it got from Supabase Auth (e.g. after login or session refresh). User identity is always `request.user_id` (auth.users id).

---

## 3. Main user flow: session → recording → report

The core flow is **linear**: start session → (optional pre-questions) → record → upload → post-questions → report.

### 3.1 Session start — `POST /session/start`

- **Auth:** Required.
- **Body (JSON, optional):**
  - `session_id` — if present, backend **resumes** that session (same user). If the session already has a full plan (pre-question + 3 command options), it returns that plan immediately and does not re-plan.
  - `questionnaire` — optional. If provided on a **new** session, can include: `mood`, `readiness`, `inspiration_needed`, `theme_code`, `cursor`, `mode`. These influence theme choice, cursor, and mode (guided vs open).
- **What the backend does:**
  - **Resume path:** Load session by `session_id` and user; if already planned, return existing `pre_questions`, `command_options`, `recommended_command_option_id`, `biofeedback_profile`, etc.
  - **New or continue path:** Create or reuse an active session; ensure **theme** is set (from admin override, or client `theme_code`, or system random with anti-repeat); plan **one pre-question** from DB templates for that theme (excluding “How are you feeling today?”); plan **three command options** (A/B/C) from in-code `COMMANDS` filtered by theme, cursor, mode, with anti-repeat by intent. Each option has a fixed prompt text snapshot (from code). The backend also returns a **biofeedback_profile** (axes + scoring) keyed by theme (see Biofeedback below).
- **Response shape (important for frontend):**
  - `session_id`
  - `theme_recommended_code`, `theme_recommended_reason`, `theme_chosen_code`, `theme_chosen_source`
  - `pre_questions`: array of one item `{ id, code, question_text, question_type, order_index }`
  - `command_options`: array of three items `{ option_id ("A"|"B"|"C"), intent, tier, mode, prompt_text_snapshot, is_primary }`
  - `recommended_command_option_id`: which option to use for recording (e.g. `"A"`) — **frontend should not show an A/B/C picker**; use this and send it back on upload.
  - `cursor`, `mode`, `structure`
  - `biofeedback_profile`: `{ axes: [...], scoring: { update_hz, window_ms, center_threshold } }` for the dartboard UI (see Biofeedback below).

Themes in code: `presence_grounding`, `clarity_simplicity`, `pacing_rhythm`, `energy_conviction`, `confidence_comfort`, `structure_organization`, `story_narrative`. Command intents are mapped to exactly one theme (e.g. `slow_clarity` → `pacing_rhythm`). So the **theme drives** which pre-question pool and which command intents are eligible; the backend then picks one pre-question and three options (with fallbacks so there are always ≥3).

### 3.2 Pre-recording answers — `POST /questions/pre-recording/answers`

- **Auth:** Required.
- **Body:** Typically `session_id` (or `recording_session_id`) and `answers`: array of `{ question_id, answer_text }`. May include `snapshot_per_answer` for storing question text/type/code per answer.
- **What the backend does:** Saves rows to `pre_recording_answers`, linked to session and pre-recording question IDs. Updates session state (e.g. pre_questions_completed). No AI here; just persistence.

### 3.3 Recording upload — `POST /recordings/upload`

- **Auth:** Required.
- **Content-Type:** `multipart/form-data`.
- **Required form fields:**
  - `session_id` — UUID of the session.
  - `command_option_id` — `"A"`, `"B"`, or `"C"` (must match one of the options returned at session start).
  - `audio` — the audio file (e.g. webm).
- **Optional form fields:**
  - `duration_seconds` — can be used in dev; in production the backend uses Whisper’s duration.
  - `biofeedback_summary` — **JSON string**. If present and valid, stored on the recording as `biofeedback_summary` (JSONB). Expected shape: e.g. `{ center_ratio, time_in_center_ms, avg_distance, axis_stats }` for the dartboard KPI.
- **What the backend does:**
  1. Validates session and that `command_option_id` is one of the session’s three options.
  2. Persists the selected command on the session (option_id, intent, tier, mode, prompt snapshot).
  3. Uploads audio to Supabase Storage (`audio_recordings` bucket), path like `{user_id}/{session_id}/{uuid}.webm`.
  4. Transcribes with Whisper; gets transcript and duration.
  5. Computes WPM and filler count (from transcript) and runs speech classification (OpenAI).
  6. Creates the **recordings** row (transcript, duration, wpm, filler_words_count, classification, confidence, audio_url, storage_path, command_option_id, etc.). If `biofeedback_summary` was sent, stores it in the same row.
  7. Picks a **post-question set** by theme + anti-repeat; creates **post_recording_questions** rows for that set (3 questions); optionally adds a fourth “Did you find this recording prompt useful?” when the command intent was “newly tested” (selected 0 or 1 time before by this user).
  8. Returns `{ recording_id, status: "recording_uploaded", post_questions }`. **post_questions** is the list of questions the frontend must show; each has a real **id** (UUID), **question_text**, **question_type**, **question_set_id**, **order_index**. Frontend must submit answers using these UUIDs.

So: **one upload** creates the recording, attaches biofeedback summary if provided, and returns the exact post-questions (with UUIDs) to use for the next step.

### 3.4 Post-recording answers — `POST /questions/post-recording/answers`

- **Auth:** Required.
- **Body:** `recording_id`, `session_id`, `answers`: array of `{ question_id, answer_text }`. `question_id` must be one of the UUIDs returned in the upload response.
- **What the backend does:**
  1. Saves answers to `post_recording_answers`.
  2. Loads recording (transcript, wpm, filler count, etc.) and session (mood, etc.).
  3. **Performance score:** Normalizes filler count, pacing (from WPM), attitude (from classification/confidence), reflection (from first scale answer), awareness (from binary “did you notice fillers?”). Computes a weighted performance score and bonuses (resilience, awareness, progress, streak); then **final_kpi** = performance + bonuses capped at 1.0. Saves to `performance_scores` (and stores first scale answer as `self_rating_score` if applicable).
  4. Builds **progress/trend** (e.g. vs previous recording) and calls **OpenAI** to generate the **coaching report**. The prompt includes: transcript, pre/post answers, WPM, filler count, **admin context** (general_notes, custom_instructions, max_words, specific_questions from `get_user_admin_context`), and progress context. Report is supportive, non-commanding; if admin asked to “add X to the next coaching message,” that is included.
  5. Saves **coaching_report** and **trend_sentence** on the recording; marks session as completed.
  6. Sends **admin email** (Resend) with a link: `{FRONTEND_URL}/recordings/{recording_id}/feedback?user_id={user_id}`.

So: **post-answers** is when the “report” is generated and the session is completed. The frontend can then show the report and/or redirect.

---

## 4. Other user-facing endpoints

- **GET /session/status** — Returns active session summary (if any) for the current user (session_id, theme, cursor, mode, pre/post completed, etc.). Auth required.
- **POST /session/abandon** — Marks the current active session as abandoned. Auth required.
- **GET /questions/pre-recording** — Returns the single planned pre-question for the current session (from session start plan). Auth required; needs session context.
- **GET /recordings/:recording_id** — Returns one recording (metadata, transcript, wpm, filler count, classification, coaching_report, performance_score if any, biofeedback_summary if any). Auth required; user can only access their own.
- **GET /recordings/:recording_id/audio-url** — Returns a signed URL for playback (or public URL fallback). Auth required.
- **GET /user/profile** — Profile and aggregate stats for the current user. Auth required.
- **GET /user/recordings** — Paginated list of the current user’s recordings. Auth required.

---

## 5. Admin endpoints

- **POST /admin/feedback** — Body: `user_id` (required), optional `general_notes`, `custom_instructions`, `max_words`, `specific_questions` (array of `{ question_text, question_type }`). Writes to `professional_notes`, `professional_notes_report_tech`, and `professional_notes_specific_questions`. Admin only.
- **GET /admin/user/:userId/context** — Returns admin context for that user: `user_id`, `general_notes`, `custom_instructions`, `max_words`, `specific_questions`. Used by the “Provide Feedback” page. Admin only. (Backend may also include `user_email` when implemented.)
- **GET /admin/recordings** — List of recordings (all users). Query params: `limit`, `offset`, `needs_feedback` (if true, filters to users without admin notes). Returns array of recording objects (backend may include `user_email` per recording when implemented). Admin only.
- **POST /admin/cleanup-incomplete-sessions** — Deletes incomplete sessions older than N days (query params: `days`, `dry_run`). Admin only.

Admin check: JWT email must exist in `admin_users` with `is_active = true`.

---

## 6. Data and definitions in code vs database

- **In code (no DB table for definitions):**
  - **Themes** and **theme → intent** mapping.
  - **COMMANDS** (intent, tier, cursor_range, mode) and **COMMAND_PROMPT_TEMPLATES** (prompt text per intent). Used to build the 3 options at session start.
  - **Post-question sets:** 20 sets × 3 questions in `POST_QUESTIONS_POOL` (`post_questions_service.py`). Which set is used is chosen at upload by theme + anti-repeat.
  - **Biofeedback profiles:** Theme → axes + scoring in `services/biofeedback_service.py` (`get_biofeedback_profile(theme_code)`).
- **In DB:**
  - **Pre-recording question templates:** `pre_recording_questions` (theme_code, question_text, question_type, code, active). One is chosen per session by theme + anti-repeat.
  - **Session and planning:** `recording_sessions` (theme_chosen_code, cursor, mode, planned_pre_question_id, etc.), `session_command_options` (the 3 options with prompt snapshot).
  - **Recording instances:** `recordings` (all metadata, transcript, metrics, coaching_report, trend_sentence, biofeedback_summary), `performance_scores` (performance, final_kpi, bonuses, raw scores).
  - **Answer instances:** `pre_recording_answers`, `post_recording_answers` (with question_id pointing to DB question rows).
  - **Post-question instances:** Rows in `post_recording_questions` are **created at upload** for the chosen set (and optional extra “prompt useful?” question). So the IDs the frontend gets in the upload response are real UUIDs from this table.

So: **command and question-set definitions live in code**; **which pre-question and which 3 commands were chosen**, and **which post-questions were created**, are stored in the DB per session/recording.

---

## 7. Performance score (KPI) — no user “categories”

- **When:** Computed in `POST /questions/post-recording/answers` (after transcript and post-answers exist).
- **Inputs:** Filler count (from transcript), WPM (from transcript + duration), classification/confidence (from OpenAI on transcript), first post-answer (scale 1–5), second (binary e.g. “did you notice fillers?”), session mood, previous performance (optional).
- **Formula (conceptually):** Normalize inputs to 0–1; weighted performance = 0.30×filler_score + 0.25×pacing + 0.25×attitude + 0.20×reflection; add small bonuses (resilience, awareness, progress, streak); **final_kpi** = min(1.0, performance + bonuses). Details in `services/scoring_service.py`.
- **Storage:** One row per recording in `performance_scores` (performance, final_kpi, bonuses, raw_scores, optional self_rating_score).
- **Important:** The backend does **not** assign users to “categories” or bands (e.g. beginner/advanced) based on KPI. It only stores a per-recording score. Any categorization would be a future or frontend concern.

---

## 8. Biofeedback (dartboard) — v1

- **Purpose:** Support a live “dartboard” UI: two axes (e.g. strength/loudness and pace), target center and radius per axis, and a score based on “time in center.”
- **Session start:** Response includes **biofeedback_profile**:
  - **axes:** list of `{ code, label_left, label_right, metric, target: { center, radius } }`. Example metrics: `loudness_db`, `speech_rate_proxy`, `steadiness_proxy`. Theme determines which two axes (e.g. `pacing_rhythm` → pace + strength).
  - **scoring:** `update_hz`, `window_ms`, `center_threshold`.
- **Client responsibility:** Compute metrics in the browser (e.g. WebAudio RMS for loudness, VAD/voiced-frame density for pace proxy). Normalize each axis to [-1, 1] with `(value - center) / radius`; ball position = (nx, ny); “in center” e.g. when distance from (0,0) ≤ 0.4. Accumulate time_in_center and avg_distance; at end of recording send **biofeedback_summary** in the upload form as a JSON string.
- **Upload:** Optional form field **biofeedback_summary** (JSON). Backend stores it on `recordings.biofeedback_summary` (JSONB). No validation of shape beyond “valid JSON object”; frontend can send e.g. `{ center_ratio, time_in_center_ms, avg_distance, axis_stats }`.
- **Theme → profile:** Defined in `services/biofeedback_service.py`. See `docs/biofeedback-theme-axes.md` for theme codes and axis metrics. Default profile (unknown theme) is strength + pace.

---

## 9. Errors and conventions

- **JSON errors:** Backend returns JSON bodies, e.g. `{"code": "SOME_CODE", "error": "human-readable message"}`. HTTP status: 400 (validation, bad input), 401 (auth), 403 (admin), 404 (not found), 500 (server error).
- **IDs:** `session_id`, `recording_id`, `question_id` are UUIDs. `command_option_id` is literal `"A"`, `"B"`, or `"C"`. Post-question IDs must be the UUIDs from the upload response, not placeholders.
- **CORS:** Configured in `config.CORS_ORIGINS` (comma-separated). Credentials are supported; frontend must send credentials if using cookies, and must send `Authorization: Bearer <token>` for protected routes.
- **Email link:** Always `{FRONTEND_URL}/recordings/{recording_id}/feedback?user_id={user_id}`. Backend does not host any UI; frontend must implement that route.

---

## 10. Summary for integration

1. **Auth:** Send Supabase access token in `Authorization: Bearer <token>`. User id = token `sub`.
2. **Flow:** Call `POST /session/start` (optionally with questionnaire). Use returned `pre_questions`, `command_options`, `recommended_command_option_id`, and `biofeedback_profile`. Do not show A/B/C picker; use recommended option.
3. **Pre-answers:** Submit to `POST /questions/pre-recording/answers` with session and answers.
4. **Record:** Capture audio (and optionally run dartboard logic). On stop, upload with `POST /recordings/upload` (session_id, command_option_id, audio; optionally biofeedback_summary as JSON string).
5. **Post-questions:** Use the **post_questions** from the upload response (real UUIDs). Submit answers to `POST /questions/post-recording/answers`. Then show the report (stored on the recording; can be fetched with GET recording if needed).
6. **Admin:** Use admin endpoints with same Bearer token; backend allows access only if token email is in `admin_users`. Feedback page URL is fixed as above.

If something is ambiguous (e.g. a field name or when a field is present), the **backend code and DOCS.md / ARCHITECTURE.md** are the source of truth; this file is a condensed guide for another LLM to understand behavior and integrate correctly.
