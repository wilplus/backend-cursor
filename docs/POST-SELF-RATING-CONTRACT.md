# POST self-rating – contract and how to call it

Completion (report creation, session → completed, coach email) is triggered by **POST self-rating**. Use this when the session is in `report_generating` and the recording-1 job is done (`ready_for_self_rating: true` in GET status).

## Backend

- **URL:** `POST /v2/homework/session/<session_id>/self-rating`
- **Auth:** `Authorization: Bearer <supabase_access_token>`
- **Body (JSON):**
  - With rating: `{ "rating": 8 }` or `{ "student_rating_1_10": 8 }` (1–10)
  - Skip: `{ "skipped": true }`
- **Success (200):**
  - `{ "status": "ok", "session_completed": true, "student_rating_1_10": 8 }` or
  - `{ "status": "ok", "session_completed": true, "skipped": true }`
- If the job is still running: `session_completed: false` → poll GET status, then call POST self-rating again.

## BFF (Next.js)

- **URL:** `POST /api/homework/session/<sessionId>/self-rating`
- Same body as above. The BFF proxies to the backend with the user’s token.
- Route reference: `docs/homework-bff-routes/session/[sessionId]/self-rating/route.ts`

## Manual test (curl)

Replace `<SESSION_ID>` and `<ACCESS_TOKEN>` (from Supabase auth / cookie).

```bash
# With rating
curl -X POST "https://app.willonski.com/api/homework/session/<SESSION_ID>/self-rating" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"rating": 8}'

# Or skip
curl -X POST "https://app.willonski.com/api/homework/session/<SESSION_ID>/self-rating" \
  -H "Authorization: Bearer <ACCESS_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"skipped": true}'
```

After `session_completed: true`, call **GET** `/api/homework/session/<SESSION_ID>/report` until 200 to load the report.
