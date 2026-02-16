# Step 4: "See my report" / post-answers 500 and PGRST204

If the user reaches step 4 (Reflective questions), clicks **See my report**, and sees:

- **500** on `POST .../post-answers`
- A red error like: `Could not find the 'completed_at' column of 'v2_sessions' in the schema cache` (code `PGRST204`)

then the **database is missing the `completed_at` column** on `v2_sessions`. The backend uses it when marking a session completed and when computing the tutor feedback deadline.

## Fix

1. **Run the migration** in Supabase SQL Editor:
   - Open **migrations/add_tutor_feedback_deadline.sql**
   - Copy its contents and run them in the Supabase project that backs this app.

2. **Reload schema cache** (if your project uses Supabase/PostgREST):
   - In Supabase Dashboard: **Settings → API** (or **Project API**)
   - Use **Reload schema cache** if the option is available, so PostgREST picks up the new column.

3. Redeploy or retry: step 4 submit should then succeed.

## Why it happens

The backend:

- **Writes** `completed_at` when completing a session (post-answers success).
- **Reads** `completed_at` in `v2_get_last_completed_session()` (for tutor feedback deadline when there is no active session).

If the column was never added (e.g. `add_tutor_feedback_deadline.sql` was not run), any query that selects or updates `completed_at` on `v2_sessions` fails with PGRST204 or a 500.

## Migration order

If you are setting up from scratch, run after **v2_all_in_one.sql** and any other v2 session migrations:

- **migrations/add_tutor_feedback_deadline.sql** (adds `completed_at`)
- **migrations/add_tutor_feedback_sent_at.sql** (adds `tutor_feedback_sent_at`)

Both are idempotent (safe to run more than once).
