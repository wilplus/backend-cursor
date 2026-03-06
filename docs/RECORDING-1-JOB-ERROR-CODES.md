# Recording-1 job: error codes and logging

When the recording-1 background job fails, it sets `recording_1_processing_status` to `"failed"` and, if the column exists, `recording_1_processing_error_code` to one of the stable codes below. The full exception and stack trace are logged with `logger.exception` (so they appear in Railway stdout / deploy logs).

## Error codes

| Code | Meaning |
|------|--------|
| `storage_error` | Failed to download audio from storage (e.g. Supabase bucket, missing file, network). |
| `transcription_failed` | Whisper/OpenAI transcription failed (API error, timeout, invalid audio). |
| `context_generation_failed` | OpenAI `generate_context_short` failed. |
| `db_error` | Failed to update `recordings` or `v2_sessions` (e.g. permission, constraint, connection). |
| `session_missing` | Session no longer exists (e.g. abandoned before job ran). Job skips; no `failed` status is set. |
| `unknown` | Any other exception (e.g. metrics computation, focus task lookup, signed URL, or unexpected error). Check the stack trace in logs. |

## Where they appear

- **Backend logs (Railway / stdout):** `recording_1_job: failed session_id=... error_code=... error=...` plus full traceback.
- **GET /v2/homework/session/status:** When `recording_1_processing_status === "failed"`, the response may include `recording_1_processing_error_code` so the frontend can show a specific message (e.g. “Transcription failed – try again”).
- **Sentry:** Exceptions are captured with `sentry_sdk.capture_exception`.

## Pipeline success

On success the job:

1. Downloads audio from storage  
2. Transcribes with OpenAI Whisper  
3. Computes WPM, fillers, performance_score_1, performance_profile  
4. Generates context_short (OpenAI)  
5. Selects focus task  
6. Updates `recordings` (transcript, wpm, fillers, etc.)  
7. Updates `v2_sessions`: `recording_1_processing_status: "completed"`, performance_score_1, context_short, etc.

After that, `GET session/status` returns `ready_for_self_rating: true` and the student can submit self-rating; completion (report + coach email) then runs via POST self-rating or GET report fallback.
