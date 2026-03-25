# `video_shown` (student overrides)

Column: **`v2_student_overrides.video_shown`** — `SMALLINT` **`0`** or **`1`**, default **`1`**.

| Value | Meaning | When set |
|-------|---------|----------|
| **0** | Hide coach assignment video in `GET /v2/homework/session/status`; student should see **waiting / reviewing** UX for the assignment video slot. | When a homework session is marked **`completed`** (all completion paths). |
| **1** | Allow showing **`tutor_video_url`** / description when the rest of the contract says so. | When admin **`POST /v2/admin/students/:id/send-assignment`** succeeds (homework email to student). |

## SQL

Run in Supabase (idempotent):

**File:** `migrations/add_video_shown_to_student_overrides.sql`

Or paste:

```sql
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'v2_student_overrides'
      AND column_name = 'video_shown'
  ) THEN
    ALTER TABLE v2_student_overrides
      ADD COLUMN video_shown SMALLINT NOT NULL DEFAULT 1
      CHECK (video_shown IN (0, 1));
  END IF;
END $$;
```

## API

`GET /v2/homework/session/status` (step 0 and active session) includes:

- **`video_shown`**: `0` | `1`
- **`can_start_homework`**: `true` | `false` (only meaningful when **`has_active_session`** is false)
- **`session_start_blocked_reason`**: `null` | `"REVIEW_PENDING"` | `"WAITING_FOR_ASSIGNMENT"`

When **`video_shown === 0`**, the backend sets **`tutor_video_url`** and **`tutor_video_description`** to **`null`** even if a pending row exists (so the client cannot accidentally show the coach clip).

### Blocking auto-start

While **`review_pending`** is true or **`video_shown === 0`**, **`POST /v2/homework/session/start`** returns **409** with:

```json
{ "code": "SESSION_START_BLOCKED", "reason": "REVIEW_PENDING" | "WAITING_FOR_ASSIGNMENT", "error": "..." }
```

So the homework page must **not** call **`session/start`** on load when **`can_start_homework === false`** — otherwise the waiting screen flashes and the recorder step opens immediately.

## Frontend (recommended)

1. Read **`video_shown`** on every status response.
2. If **`video_shown === 0`**: do **not** show the coach assignment video block; prefer **waiting / review** UI (you can still use **`review_pending`** for copy).
3. If **`video_shown === 1`**: show coach video when **`tutor_video_url`** is non-empty (and keep **`assigned_exercises[].video_url`** as optional fallback for legacy).

`review_pending` and `video_shown` usually move together after deploy, but **`video_shown`** is the explicit DB-backed switch for the video vs waiting dichotomy.

## Copy-paste type (optional)

Extend step-0 state with:

```ts
video_shown: 0 | 1;
```

See also `docs/homework-bff-routes/homeworkApplyStep0State.ts` — include `video_shown` in `normalizeHomeworkStep0Payload`.
