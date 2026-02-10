# Debug: 500 on POST recording-2

When **POST /v2/homework/session/<session_id>/recording-2** returns **500**, do the following.

---

## 1. Inspect the response body

The API returns JSON with **`code`** and **`error`** (and sometimes **`hint`**). In DevTools → Network → select the `recording-2` request → **Response** tab, check the body.

- **`error`** contains the exception message (e.g. PostgREST "Could not find the 'X' column").
- **`hint`** is set when the error looks like a schema/cache issue: run migrations and reload PostgREST.

---

## 2. Common causes and fixes

### A. Missing column on `recordings` (PGRST204)

If the **error** mentions a column of **`recordings`** not found in the schema cache (e.g. `performance_metrics_v2`, `metric_labels_snapshot_v2`, `session_v2_id`, `task_id`):

1. **Run the migration** that adds v2 columns to `recordings`:
   - **`migrations/add_recordings_v2_columns.sql`** (run in Supabase SQL editor).
2. **Reload PostgREST schema**: Supabase Dashboard → **Settings** → **API** → **Reload schema cache** (or restart the API if self-hosted).

### B. Missing column on `v2_sessions`

If the error mentions **`v2_sessions`** (e.g. we previously wrote `recording_id`; that was removed in code). Ensure you have **no** code or BFF still updating `recording_id` on `v2_sessions`. The table uses **`recording_1_id`** and **`recording_2_id`** only.

### C. Upload, transcription, or OpenAI failure

If the **error** is about storage, Whisper, or timeouts:

- Check backend logs for the full traceback (we log with `logger.exception(...)`).
- Confirm Supabase storage bucket exists and the backend has the right env (bucket name, keys).
- Confirm OpenAI API key is set and transcribe isn’t timing out.

### D. Session not in `final_task_ready`

If the session status isn’t **`final_task_ready`**, the handler returns **404**, not 500. So a 500 means the request passed the status check and failed later (upload, transcribe, DB insert, or session update).

---

## 3. Check backend logs

After reproducing the 500, check your server logs. The handler logs the full exception with `logger.exception("Homework recording-2 failed")`, so you should see the traceback and the exact line that failed.

---

## Summary

| Response body / logs | Action |
|----------------------|--------|
| PGRST204 / "column ... of 'recordings'" | Run **migrations/add_recordings_v2_columns.sql**, then **reload PostgREST schema**. |
| PGRST204 / "column ... of 'v2_sessions'" | Stop writing that column (e.g. `recording_id`); use `recording_1_id` / `recording_2_id` only. |
| Storage / OpenAI / timeout errors | Check env, keys, and backend logs. |
