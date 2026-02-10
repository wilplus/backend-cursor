# Debug: 404 on recording-upload-url / "Homework flow not available"

When the frontend shows **"Homework flow is not available yet"** and the Network tab shows **404** on **recording-upload-url**, the request is not reaching a handler that returns 200.

---

## Backend already implements this (this repo)

The Flask app **does** have the route:

- **Method/path:** `POST /v2/homework/session/<session_id>/recording-upload-url`
- **Where:** `routes/homework.py` → `homework_recording_upload_url`, blueprint prefix `/v2/homework`
- **Auth:** `@require_auth` (sets `request.user_id`)
- **Body:** JSON `{ "recording": "1" }` or `"2"`
- **Response 200:** `{ "storage_path": "<user_id>/<session_id>/<uuid>.webm", "bucket": "<AUDIO_BUCKET_NAME>" }`
- **Validation:** Session must exist; for `"1"` status must be `warm_up`, for `"2"` must be `final_task_ready`. Returns 404 if session not found or wrong status.

So a 404 in production means either **(1)** the BFF has no route for that path (Next returns 404), or **(2)** the deployed backend is an old build without this route (Flask returns 404), or **(3)** the BFF proxies to the wrong URL/path.

---

## 1. No SQL or DB change needed

The **recording-upload-url** endpoint does **not** use any new tables or columns. It only:

- Checks that the session exists and is in the right status (warm_up or final_task_ready)
- Generates a `storage_path` and returns it with `bucket`

So you do **not** need to run any new SQL or migration for this. If 404 appears, it’s a **routing or deployment** issue.

---

## 2. Where the 404 can come from

### A) BFF has no route for `recording-upload-url` (very common)

The browser calls something like:

- `POST https://app.willonski.com/api/homework/session/<sessionId>/recording-upload-url`

If the **Next.js BFF** does **not** define a route for that path, Next returns **404** before any request is sent to Flask.

**Fix:** Add a BFF route that handles:

- **Path:** `/api/homework/session/[sessionId]/recording-upload-url` (or your exact path)
- **Method:** POST
- **Behavior:** Forward the request to the Flask backend at  
  `POST {BACKEND_URL}/v2/homework/session/<sessionId>/recording-upload-url`  
  with the same body `{ "recording": "1" }` or `"2"` and auth headers, then return the backend response.

So: confirm that the BFF has a **route file** for `recording-upload-url` (e.g. under `pages/api/homework/session/[sessionId]/recording-upload-url.ts` or `app/api/homework/session/[sessionId]/recording-upload-url/route.ts`) and that it proxies to the backend URL above.

### B) Backend not deployed with the new route

The Flask app must include the **recording-upload-url** route. Full URL on the backend is:

- **POST** `https://<your-flask-host>/v2/homework/session/<session_id>/recording-upload-url`

If the **deployed** app on Railway (or wherever) was built from an older commit that doesn’t have this route, the backend will return **404**.

**Fix:** Deploy the latest backend (the one that adds `recording-upload-url` and the direct-to-storage flow). After deploy, test with:

```bash
curl -X POST "https://<BACKEND_URL>/v2/homework/session/<SESSION_ID>/recording-upload-url" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <JWT>" \
  -d '{"recording":"1"}'
```

You should get **200** and `{ "storage_path": "...", "bucket": "audio_recordings" }`. If you get 404, the running app doesn’t have the route.

### C) BFF proxies to the wrong path

If the BFF **does** have a route but forwards to the wrong backend path, the backend can return 404.

- Backend path must be: **/v2/homework/session/:sessionId/recording-upload-url**
- Not: `/v2/homework/recording-upload-url` or `/api/.../recording-upload-url` on the backend (Flask has no `/api` prefix).

---

## 3. "Homework flow is not available yet"

That message is likely from the **frontend** when:

- A required API call fails (e.g. 404 on recording-upload-url), or
- Some other “homework available” check fails (e.g. session status, config).

So fixing the 404 (BFF route + backend path + deployment) should remove the failure that triggers “homework flow not available.” If the message is shown in another case (e.g. “no warm-up task”), that’s a separate check in the frontend.

---

## 4. Checklist

| Check | Action |
|-------|--------|
| BFF route exists for `.../recording-upload-url` | Add route that proxies POST to backend `/v2/homework/session/:id/recording-upload-url`. |
| Backend deployed with new code | Redeploy Flask so the app has the `recording-upload-url` route. |
| Backend URL in BFF | BFF uses the same `BACKEND_URL` as for other homework routes (e.g. recording-1). |
| No new SQL | No migration needed for recording-upload-url. |

Once the BFF route exists and the backend is deployed with the new route, the 404 and “homework flow not available” (when caused by this call) should go away.
