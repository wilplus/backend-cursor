# Post-recording questions not being saved

## Cause

The homework flow saves post-recording answers by updating the session:

```python
db.v2_update_session(session_id, user_id, {"post_answers": answers, ...})
```

If the **`v2_sessions`** table does not have a **`post_answers`** column, that update either fails or the key is ignored, so answers are not persisted. Some schemas (e.g. `supabase-schema-willab-complete.sql`) create `v2_sessions` with only a few columns and add more in blocks that did not include `post_answers`.

## Fix (backend / DB)

1. **Run the migration** (Supabase SQL Editor or your Postgres client):

   ```sql
   -- migrations/v2_sessions_add_post_answers.sql
   ALTER TABLE v2_sessions ADD COLUMN IF NOT EXISTS post_answers JSONB;
   ```

2. Reload PostgREST schema if you use Supabase (e.g. restart or use “Reload schema” so the new column is visible to the API).

After this, `POST /v2/homework/session/:id/post-answers` will persist `post_answers` on the session.

## Request shape (frontend)

The backend expects:

```json
{
  "answers": [
    { "question_id": "<uuid from GET questions>", "answer_text": "user answer" }
  ]
}
```

- **question_id** must be one of the IDs returned by `GET /v2/homework/session/:id/questions` (and stored in the session’s `post_question_ids`).
- **answer_text** is the student’s answer string.

If the frontend sends a different key (e.g. `answer` instead of `answer_text`) or an empty `answers` array, the report may still be generated but stored answers may be wrong or empty.

## Verify

After running the migration:

1. Complete step 4 (post-questions) and submit.
2. Check the session row in `v2_sessions`: the `post_answers` column should contain the JSON array of `{ question_id, answer_text }` objects.
3. GET session/status for a completed session: the session object returned by the API will include `post_answers` if your backend selects `*` from `v2_sessions` (e.g. `v2_get_session` uses `select("*")`).
