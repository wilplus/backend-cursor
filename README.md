# Speech Analysis Coaching Backend API

Flask backend API for a speech-analysis coaching app, deployed on Railway.

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Copy `.env.example` to `.env` and fill in your configuration:
```bash
cp .env.example .env
```

3. Set environment variables:
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY`: Supabase service role key
- `SUPABASE_JWT_SECRET`: Supabase JWT secret
- `OPENAI_API_KEY`: OpenAI API key
- `RESEND_API_KEY`: Resend API key
- `RESEND_FROM_EMAIL`: Email address to send from
- `ADMIN_EMAIL`: Admin email to receive notifications
- `SENTRY_DSN`: Sentry DSN (optional)
- `ENV`: `production`, `development`, or `staging`
- `SEND_EMAILS`: `true` or `false`
- `FRONTEND_URL`: Frontend base URL for admin feedback links (e.g. `https://app.willonski.com` or `http://localhost:3000`)

## Running Locally

```bash
python app.py
```

## Deployment on Railway

1. Connect your repository to Railway
2. Set all environment variables in Railway dashboard
3. Railway will automatically detect the `Procfile` and deploy

## API Endpoints

### Auth
- `POST /auth/signup` - Sign up new user
- `POST /auth/login` - Login user
- `POST /auth/reset-password` - Trigger password reset

### Session
- `POST /session/start` - Start new session
- `POST /session/abandon` - Abandon active session
- `GET /session/status` - Get session status

### Questions
- `GET /questions/pre-recording` - Get pre-recording questions
- `POST /questions/pre-recording/answers` - Submit pre-answers
- `POST /questions/post-recording/answers` - Submit post-answers and generate report

### Recordings
- `POST /recordings/upload` - Upload recording and analyze
- `GET /recordings/<recording_id>` - Get recording details
- `GET /recordings/<recording_id>/audio-url` - Get signed audio URL

### User
- `GET /user/profile` - Get user profile
- `GET /user/recordings` - Get user recordings

## Development Mode

In non-production environments (`ENV != "production"`):
- Audio files are not stored
- OpenAI calls are skipped (mock responses)
- Emails are not sent if `SEND_EMAILS=false`

## Supabase migrations

Run the SQL migrations against your Supabase project (Dashboard → SQL Editor). **One file:** run **`migrations/v2_all_in_one.sql`** (includes v2_flow, speaker_profiles, show_exercise_step, homework_flow, homework_flow_schema_additions in order). Alternatively run the individual files in `migrations/` in that same order. Requires your base schema (e.g. `recording_sessions`, `recordings`). Then in Supabase go to **Settings → API** and use **Reload schema cache** if available.

## Documentation

- **ARCHITECTURE.md** — Stack, layout, core flows, database, conventions (source of truth for design).
- **DOCS.md** — Implementation and operations: schema, storage, admin feedback, email link, questionnaire, frontend integration.
- **docs/FRONTEND-SYNC-PROMPT.md** — Prompt and reference for frontend team: student flow, admin endpoints, request/response contract.
- **docs/ADMIN-PANEL-SYNC.md** — Backend contract for the simplified admin panel (two routes: students list + student profile with Homework Configuration, Speaker Profile, Reports History).
- **docs/API-PATHS-FRONTEND-TO-BACKEND.md** — How the frontend talks to the backend: frontend uses `/api/admin/*`, `/api/session/*`, `/api/homework/*` (no `v2`); BFF proxies to `BASE_URL/v2/...`. Backend keeps serving `/v2/*`; no change required.
- **docs/BACKEND_PROMPT.md** — Short handoff prompt for backend/LLM: frontend paths (no `v2`), BFF → `/v2/*`, no backend change required.
- **docs/homework-bff-routes/** — BFF route examples for the homework flow. If the student "Start homework" screen shows "Backend returned invalid JSON" (404 HTML), add these routes in the frontend so `/api/homework/*` proxies to `/v2/homework/*`. See `docs/homework-bff-routes/README.md`.
