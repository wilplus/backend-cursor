# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- **Backend:** Flask 3 (Python 3.12), gunicorn on Railway.
- **Data/Auth/Storage:** Supabase (Postgres + Auth + Storage); Cloudflare R2 (optional) for coach/reference/user video and audio buckets.
- **AI:** OpenAI (Whisper transcription, GPT-4o-mini for scoring/reports).
- **Email:** Resend. **Errors:** Sentry. **Payments:** Stripe (credits webhook).
- **ffmpeg:** Required at runtime for audio extraction; `nixpacks.toml` + `apt.txt` install it on Railway and `bin/railway-web.sh` pins `FFMPEG_PATH`.

## Commands

```sh
# Install
pip install -r requirements.txt

# Run locally (debug auto-on outside ENV=production); listens on 0.0.0.0:5000
python app.py

# Run gunicorn the way Railway does (uses bin/railway-web.sh; needs $PORT)
PORT=5000 sh bin/railway-web.sh

# Unit tests — files prefixed test_*.py at repo root use unittest.TestCase.
# Many guard imports with skipIf when app deps aren't installed, so a clean env will silently skip.
python -m unittest discover -s . -p 'test_*.py' -v
python -m unittest test_homework_regressions          # single module
python -m unittest test_homework_regressions.HomeworkRouteRegressionsTests.test_self_rating_completes_from_task_block_when_recording_finished

# Manual / smoke scripts (NOT pytest; they hit a live backend or Supabase). Examples:
python test_integration.py        # expects backend at http://localhost:5000 and SUPABASE_* in .env
python test_jwks.py               # probes Supabase JWKS endpoint
python get_token.py               # exchange Supabase credentials for an access token

# Migrations: do NOT auto-run. Open each SQL file in Supabase SQL Editor in order
# (see migrations/README.md). run_migration.py is a helper that prints SQL or
# uses DATABASE_URL+psycopg2 to apply a single named file.
python run_migration.py

# Maintenance scripts (read services/db.py; require Supabase env)
python run_cleanup_v2_sessions.py --dry-run        # delete stale incomplete homework sessions
python run_cleanup_incomplete_sessions.py          # legacy session cleanup
```

There is no linter or formatter wired into the repo; do not invent one.

## Architecture

### Request flow

`app.py` builds the Flask app, sets `MAX_CONTENT_LENGTH` to the max of `MAX_AUDIO_SIZE_MB` (25) and `MAX_REFERENCE_VIDEO_SIZE_MB` (500), configures CORS from `config.CORS_ORIGINS` (merged from `CORS_ORIGINS` env + `FRONTEND_URL` origin), registers blueprints, and serves `/health*` plus a `/api/admin/students*` 308 redirect alias to `/v2/admin/students*` (frontend BFFs may call either).

Blueprints (registered in `app.py`):

| Prefix | Module | Purpose |
|---|---|---|
| `/auth` | `routes/auth.py` | Supabase JWT login helpers |
| `/v2/recordings` | `routes/recordings.py` | Recording fetch/transcript |
| `/user` | `routes/user.py` | User profile, media upload |
| `/admin` | `routes/admin.py` | **Legacy v1 admin** (feedback, professional notes) — still live |
| `/v2/admin/*` | `routes/v2_routes.py` | **Current admin** (students, tasks, overrides, copilot, reference videos) |
| `/v2/homework/*` | `routes/homework.py` | **Student flow** (only product flow today) |
| `/v2/internal/*` | `routes/internal_webhooks.py` | Stripe webhook, annotation export cron, internal credits |

All `/v2/*` requests authenticate with `Authorization: Bearer <supabase_access_token>` verified in `auth.py` (HS256 via `SUPABASE_JWT_SECRET`, or ES256/RS256 via JWKS at `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`). Admin endpoints additionally require the caller's email to appear in `admin_users` with `is_active = true`.

### Layering rules

- **Config** lives only in `config.py` (loaded once via `python-dotenv`). All env vars are read there and exposed as `Config` attributes; never call `os.getenv` outside `config.py`.
- **DB access** goes only through `services/db.py` (the `db` singleton uses the Supabase service-role key and bypasses RLS). Routes must not touch Supabase directly.
- **External services** each live behind a service module: `openai_service`, `email_service`, `audio_storage` / `user_media_storage` / `coach_video_storage` (Supabase or R2 depending on env), `ffmpeg_audio_extract`, `stripe_checkout_webhook`, etc.
- Error responses use `jsonify({"code": "<STABLE_CODE>", "error": "<human msg>"})` with the matching HTTP status. Stable codes are part of the API contract — the frontend BFF and Sentry alerts key off them.

### The homework state machine (`routes/homework.py`)

One **active session per student**, identified by `v2_sessions.id`. Active = status in `('task','task_block','final_task_ready','post_questions','completing_from_recording_1')`. `completed` is not active. The frontend renders steps from `session.status` — not a fixed 0→5 sequence. Steps can skip (e.g. straight to report after recording-1 via complete-from-recording-1; admin overrides can bypass step 2 or 4).

Endpoints under `/v2/homework`:

1. `POST /session/start` — picks task via `db.v2_get_assigned_task_for_user` (first row by `order_index`). Returns 402 `INSUFFICIENT_CREDITS` only when `credits <= 0`; 409 `SESSION_START_BLOCKED` when waiting for coach (`can_start_homework=false`); 422 `NO_TASK_CONFIGURED`.
2. `POST /session/<id>/recording-1` — multipart `audio`. Kicks `services/recording_1_job.py` background work: Whisper transcribe → score (`scoring_service`) → `recording_1_performance_profile` (via `services/metrics_v2.build_recording_1_performance_profile`) → focus task pick via `services/v2_flow_service.score_and_pick_focus_task` (uses `v2_student_coaching_memory.recurring_issues` + `v2_focus_tasks.targets`/`difficulty`, excludes last 5 used).
3. `POST /session/<id>/metric-answers` — generates `final_task_text` (OpenAI, 2-sentence template).
4. `POST /session/<id>/recording-2` — Whisper + 5-metric scoring → `performance_score_2`.
5. `GET /session/<id>/questions` + `POST /session/<id>/post-answers` — only if admin assigned exactly 3 post questions; otherwise `questions: []` and the step is skipped. Post-answers writes the final report, marks the session `completed`, deducts **5 credits once** (`v2_charge_homework_completion_credits_once`, idempotent via `homework_credits_charged_at`), then calls `db.v2_upsert_student_coaching_memory(user_id, session_id)` to refresh `last_5_scores` / `recent_focus_task_ids` / `recurring_issues`.
6. `GET /session/status` is the single canonical status read (never creates a session). Returns `credits`, `tutor_video_url`, `tutor_video_description` (when `video_shown == 1`), and on completed sessions the report payload.

`POST /session/<id>/self-rating` accepts the 1–5 rating that closes a recording-1-only path (steps 2–4 are currently disabled; see `docs/TEMPORARY-REMOVED-STEPS-2-3-4-BACKUP.md`).

### Background work & long-running jobs

Flask + gunicorn (2 workers, `--timeout 1800`) handles uploads. Heavy work is fired from request handlers via `threading.Thread`/job helpers in `services/`:

- `recording_1_job.py` — transcription/scoring/profile for recording 1.
- `copilot_video_pipeline.py` — admin copilot video generation (gated by `COPILOT_VIDEO_PIPELINE_ENABLED`).
- `reference_video_upload_worker.py` — admin reference video Whisper extract.
- `session_concatenation.py`, `coach_video_storage.py` — coach feedback video assembly.

Stale jobs are reaped on app boot by `_startup_cleanup` → `db.mark_stale_upload_jobs_failed(stale_minutes=30)`. Crons run as separate Railway services: `bin/railway-annotation-export-cron.sh` POSTs to `/v2/internal/annotation-export` daily (see `Dockerfile.annotation-cron`).

### Storage routing

Audio defaults to Supabase Storage bucket `audio_recordings`. Setting `R2_AUDIO_BUCKET_NAME` + `R2_AUDIO_PUBLIC_BASE_URL` switches `services/audio_storage.py` to R2. Coach feedback videos use `COACH_FEEDBACK_VIDEO_BUCKET` (Supabase) or R2 when `R2_ACCOUNT_ID`/`R2_ACCESS_KEY_ID`/`R2_SECRET_ACCESS_KEY` are set. User-uploaded media uses `R2_USER_MEDIA_BUCKET` and falls back to the coach video bucket. Always go through the storage service modules — they handle signed URLs and the R2/Supabase split.

### Feature flags

Several routes are gated by env-flag attributes on `Config`. Default behavior matters when reading code:

- `DIAGNOSE_SESSION_STATE_ENABLED` (default off) — populate `ai_suggested_profile`/`ai_suggested_task_id` on session completion.
- `GUEST_FUNNEL_ENABLED` (default off) — `/v2/public/shaky-voice/*` anonymous upload + claim flow.
- `FEW_SHOT_TENANT_SCOPED` (default off), `COACHING_ATTEMPTS_DUAL_WRITE` (default on), `LEARNER_PROFILE_INJECTION_ENABLED` (default off), `LONGITUDINAL_FIRST_QUESTION_ENABLED` (default on), `BASELINE_SUMMARY_ENABLED` (default on), `LEARNER_MIRROR_ENABLED` (default off), `COPILOT_VIDEO_PIPELINE_ENABLED` (default off) — see inline comments in `config.py` for rollout rationale before flipping.

### Migrations

Files live in `migrations/`; there are >100 of them and ordering matters. `migrations/README.md` is the canonical order. The current v2 baseline is `v2_schema_unified.sql`; subsequent migrations are additive (`add_*.sql`). After running SQL, **reload PostgREST schema cache** in Supabase (Settings → API → Reload schema cache), otherwise PostgREST returns `42703` for new columns. The backend uses `SUPABASE_SERVICE_ROLE_KEY` and bypasses RLS, but `migrations/enable_rls_public_tables.sql` should be applied so anon clients can't read public tables directly.

## Conventions (from `.cursor/rules/architecture-taskmaster.mdc` and `.taskmaster/docs/`)

- **Deploy branches:** Backend integration on `staging`, production from `main`. Frontend integration on `develop`, production from `main`. Do not push directly to `main`.
- **Frontend never calls `/v2/*` directly.** The Next.js BFF maps `/api/admin/*` → `/v2/admin/*` and `/api/homework/*` → `/v2/homework/*`. Reference BFF routes are checked into `docs/homework-bff-routes/` and `docs/frontend-admin-panel/` to be copied into the frontend repo.
- **Status, not step numbers, drive the UI.** `session.status` is the single source of truth; the homework flow has no fixed sequence — overrides and AI-generated paths can skip steps.
- **Task table naming:** the homework tables are `public.tasks` and `public.tasks_pool` (plural). Older code/comments may still say `warm_up` — `rename_warmup_to_tasks_and_drop_focus.sql` + `rename_homework_session_status_warm_up_to_task.sql` are the renames.
- **`docs/HOMEWORK-AND-PERFORMANCE.md`** is the deepest reference for the homework flow, scoring, and migration order. **`.taskmaster/docs/APP_DESCRIPTION.md`** is the product spec.

## When changing things

- **Homework flow** → `routes/homework.py`, `services/db.py` (homework_sessions, tasks/tasks_pool, task_block, metrics), `services/openai_service.py` (report generation).
- **Coaching / focus task selection** → `services/v2_flow_service.py` (`score_and_pick_focus_task`, `RECURRING_ISSUE_TARGETS`), `services/metrics_v2.py` (`build_recording_1_performance_profile`), `services/recording_1_job.py`, `db.v2_upsert_student_coaching_memory` / `v2_select_student_focus_task_for_score`.
- **Admin (v2)** → `routes/v2_routes.py` + matching `services/db.py` helpers for students, overrides, speaker_profiles, tasks/tasks_pool, post-questions, metric-questions.
- **Legacy admin / report regen** → `routes/admin.py`, `openai_service.generate_final_report`, `db.get_user_admin_context`, professional_notes tables.
- **New env var** → add to `config.py` (with the same default-comment pattern other flags use) and update `.env.example`.
