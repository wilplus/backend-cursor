# GET /status response shape (current)

For **OpenAPI YAML** and “no transcripts in GET /status”: this is what the homework session status endpoint returns **today**. Use it to define the spec so it matches reality and does not break the frontend.

**Endpoint:** `GET /v2/homework/session/status` (or your mounted path, e.g. `GET /api/homework/session/status`)  
**Auth:** Required (e.g. Bearer).

---

## Response: no active session

**Status:** 200

```json
{
  "session": null,
  "has_active_session": false
}
```

---

## Response: active session

**Status:** 200

```json
{
  "session": { ... },
  "session_id": "uuid",
  "has_active_session": true
}
```

`session` is the **full v2_sessions row** from `select("*")` on `v2_sessions`. So it includes every column present in the DB (snake_case). There are **no transcript fields** in this response; transcripts live on the `recordings` table. Session only has `recording_1_id` and `recording_2_id`.

### Session object shape (all keys that exist on v2_sessions)

| Key | Type | Notes |
|-----|------|--------|
| id | string (UUID) | |
| user_id | string (UUID) | |
| status | string | e.g. warm_up, task_block, final_task_ready, post_questions, completed |
| created_at | string (ISO timestamp) | |
| context_short | string \| null | |
| context_long | string \| null | |
| context_long_entries | array \| null | `[{ "at": "ISO8601", "text": "..." }, ...]` |
| selected_task_id | string (UUID) \| null | |
| recording_1_id | string (UUID) \| null | |
| recording_2_id | string (UUID) \| null | |
| performance_score_1 | number \| null | |
| performance_score_2 | number \| null | |
| performance_score_end | number \| null | |
| session_metric_question_1 | string \| null | |
| session_metric_question_2 | string \| null | |
| session_metric_question_3 | string \| null | |
| metric_answers | object \| null | e.g. { answer_1, answer_2, answer_3 } |
| question_1_analysis | string \| null | |
| question_1_score | number \| null | |
| question_2_analysis | string \| null | |
| question_2_score | number \| null | |
| question_3_analysis | string \| null | |
| question_3_score | number \| null | |
| pitch_variance_avg | number \| null | |
| report_id | string (UUID) \| null | |
| post_question_ids | array of UUIDs \| null | |
| warm_up_task_id | string (UUID) \| null | |
| warm_up_task_text | string \| null | |
| final_task_text | string \| null | |

**Not included:** No `transcription_text`, no nested `recording_1` / `recording_2` objects with transcript. So the “no transcripts in GET /status” decision is already the case; nothing to remove. For OpenAPI you can document this shape as-is. Post-MVP you can add optional `transcript_preview` (e.g. on session or via GET /recordings/{id}) without changing the current contract.

---

## Error response

**Status:** 500 on server error

```json
{
  "code": "V2_ERROR",
  "error": "string"
}
```

---

**Source:** `routes/homework.py` `homework_session_status()`, `db.v2_get_active_homework_session()` → `v2_sessions` `select("*")`.
